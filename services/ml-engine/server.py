import os
import time
import json
import base64
import pickle
import asyncio
import threading
from collections import deque
import redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sklearn.ensemble import IsolationForest
import numpy as np

app = FastAPI()
REDIS_HOST = os.getenv("REDIS_HOST")
client = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

app.mount("/static", StaticFiles(directory="static"), name="static")

def load_model():
    blob = client.get("ml:model")
    if blob:
        try:
            return pickle.loads(base64.b64decode(blob)), "trained on real AIS data"
        except Exception:
            pass
    rng = np.random.RandomState(42)
    X_normal = np.column_stack([
        rng.uniform(-0.1, 0.1, 200), rng.normal(0, 0.5, 200).clip(-3, 3), np.zeros(200)
    ])
    X_anomalous = np.column_stack([
        rng.uniform(-1.0, -0.4, 50), rng.uniform(-20, -3, 50), rng.randint(0, 2, 50)
    ])
    m = IsolationForest(contamination=0.15, random_state=42)
    m.fit(np.vstack([X_normal, X_anomalous]))
    return m, "synthetic fallback"

model, model_source = load_model()
model_cache = {}
print(f"Anomaly model loaded — {model_source}")

def model_for(vessel_id):
    if vessel_id in model_cache:
        return model_cache[vessel_id]
    m = model
    blob = client.get(f"ml:model:{vessel_id}")
    if blob:
        try:
            m = pickle.loads(base64.b64decode(blob))
        except Exception:
            pass
    model_cache[vessel_id] = m
    return m

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception:
                pass

manager = ConnectionManager()
loop_ref = None

recent_events = deque(maxlen=50)
last_telemetry_event = 0.0
HAZARD_STATUSES = {"Aground", "Not under command"}
# Workboats slow/stop constantly by profession — suppress speed-based
# anomalies for them (hazard statuses still fire)
WORKBOAT_TYPES = {"Tug", "Towing", "Towing (large)", "Pilot vessel", "Port tender", "Fishing"}
# Consecutive anomalous readings required before flagging
MIN_ANOMALY_STREAK = 5

def save_alert(vessel_id, mapping):
    client.hset(f"alert_state:{vessel_id}", mapping=mapping)
    client.expire(f"alert_state:{vessel_id}", 3600)

def get_all_alerts():
    alerts = []
    for key in client.scan_iter("alert_state:*"):
        data = client.hgetall(key)
        data["vessel_id"] = key.split(":", 1)[1]
        alerts.append(data)
    return alerts

def emit_event(kind, text, extra=None):
    event = {"kind": kind, "text": text, "timestamp": time.time()}
    if extra:
        event.update(extra)
    recent_events.appendleft(event)
    if loop_ref and manager.active_connections:
        asyncio.run_coroutine_threadsafe(
            manager.broadcast(json.dumps({"type": "event", "data": event})),
            loop_ref
        )

def sweep_stale_alerts():
    for key in client.scan_iter("alert_state:*"):
        data = client.hgetall(key)
        if data.get("resolved") == "1":
            continue
        vessel_id = key.split(":", 1)[1]
        state = client.hgetall(f"vessel_state:{vessel_id}")
        if not state or state.get("is_anomaly") != "1":
            client.hset(key, "resolved", "1")
            emit_event("cleared", f"{data.get('vessel_name') or vessel_id}: stopped reporting — alert auto-resolved",
                       extra={"vessel_id": vessel_id, "vessel_name": data.get("vessel_name")})

def background_stream_processor():
    global last_telemetry_event
    last_ids = {"maritime_telemetry_stream": "$", "maritime_advisory_stream": "$"}
    last_sweep = 0.0
    print("ML Engine background WebSocket broadcaster active...")
    while True:
        try:
            streams = client.xread(last_ids, count=10, block=1000)
            if not streams:
                if time.time() - last_sweep > 30:
                    last_sweep = time.time()
                    sweep_stale_alerts()
                continue
            for stream_name, messages in streams:
                for msg_id, data in messages:
                    last_ids[stream_name] = msg_id
                    payload = json.loads(data["data"])

                    if stream_name == "maritime_advisory_stream":
                        save_alert(payload["vessel_id"], {
                            "vessel_name": payload["vessel_name"],
                            "advisory": payload["advisory"],
                            "advisory_at": time.time(),
                        })
                        emit_event("advisory", f"LLM advisory issued for {payload['vessel_name']} ({payload['zone']})", extra={"advisory": payload["advisory"], "vessel_id": payload["vessel_id"], "vessel_name": payload["vessel_name"]})
                        continue

                    expected = payload["expected_speed_knots"]
                    speed_dev = (payload["speed_knots"] - expected) / max(expected, 1.0)
                    if expected < 2.0:
                        speed_dev = 0.0
                    is_stopped = 1 if payload["speed_knots"] < 2.0 and expected >= 5.0 else 0
                    hazard = payload["nav_status"] in HAZARD_STATUSES

                    track_key = f"vessel_track:{payload['vessel_id']}"
                    accel = 0.0
                    prev_pt = client.lindex(track_key, 0)
                    if prev_pt:
                        pp = json.loads(prev_pt)
                        dt = max(payload["timestamp"] - pp["t"], 5)
                        accel = max(-30.0, min(30.0, (payload["speed_knots"] - pp["speed"]) / (dt / 60)))

                    X_infer = np.array([[speed_dev, accel, is_stopped]])
                    m = model_for(payload["vessel_id"])
                    score = m.decision_function(X_infer)[0]
                    raw_anomaly = m.predict(X_infer)[0] == -1 or is_stopped == 1 or hazard
                    if payload.get("ship_type") in WORKBOAT_TYPES and not hazard:
                        raw_anomaly = False
                    # Departure exemption: was recently stopped and is now
                    # accelerating away — normal departure, not an anomaly
                    if raw_anomaly and accel > 0 and expected < 5.0:
                        recent = [json.loads(i)["speed"] for i in client.lrange(track_key, 0, 5)]
                        if recent and min(recent) < 2.0:
                            raw_anomaly = False

                    state_key = f"vessel_state:{payload['vessel_id']}"
                    prev = client.hgetall(state_key)
                    prev_anomaly = prev.get("is_anomaly")
                    streak = int(prev.get("anomaly_streak") or 0) + 1 if raw_anomaly else 0
                    is_anomaly = hazard or streak >= MIN_ANOMALY_STREAK
                    client.hset(state_key, mapping={
                        **payload,
                        "anomaly_score": float(score),
                        "anomaly_streak": streak,
                        "is_anomaly": "1" if is_anomaly else "0",
                        "last_updated": time.time()
                    })
                    client.expire(state_key, 300)
                    client.lpush(track_key, json.dumps({
                        "lat": payload["lat"], "lon": payload["lon"],
                        "speed": payload["speed_knots"], "t": payload["timestamp"]
                    }))
                    client.ltrim(track_key, 0, 199)
                    client.expire(track_key, 3600)

                    if is_anomaly and prev_anomaly != "1":
                        anomaly_event = {"vessel_id": payload["vessel_id"], "details": payload}
                        client.xadd("maritime_anomaly_stream", {"data": json.dumps(anomaly_event)})
                        save_alert(payload["vessel_id"], {
                            "vessel_name": payload["vessel_name"],
                            "lat": payload["lat"], "lon": payload["lon"],
                            "speed": payload["speed_knots"], "expected": expected,
                            "status": payload["nav_status"],
                            "timestamp": time.time(), "resolved": "0",
                        })
                        direction = "up to" if payload["speed_knots"] > expected else "down to"
                        emit_event("anomaly", f"{payload['vessel_name']} {direction} {payload['speed_knots']} kn — baseline ~{expected} kn", extra={
                            "vessel_id": payload["vessel_id"], "vessel_name": payload["vessel_name"],
                            "lat": payload["lat"], "lon": payload["lon"],
                            "speed": payload["speed_knots"], "expected": expected, "status": payload["nav_status"]
                        })
                    elif not is_anomaly and prev_anomaly == "1":
                        save_alert(payload["vessel_id"], {"resolved": "1"})
                        emit_event("cleared", f"{payload['vessel_name']}: returned to normal — {payload['speed_knots']} kn", extra={"vessel_id": payload["vessel_id"], "vessel_name": payload["vessel_name"]})
                    elif not is_anomaly and time.time() - last_telemetry_event > 2.0:
                        last_telemetry_event = time.time()
                        emit_event("telemetry", f"{payload['vessel_name']}: {payload['speed_knots']} kn, {payload['nav_status']} — {payload['zone']}")

                    vessels = get_all_vessels_internal()
                    if loop_ref and manager.active_connections:
                        asyncio.run_coroutine_threadsafe(
                            manager.broadcast(json.dumps({"type": "vessels_update", "data": vessels})),
                            loop_ref
                        )
        except Exception as e:
            print(f"Error in stream processor: {e}")
            time.sleep(2)

def get_all_vessels_internal():
    vessels = []
    keys = client.keys("vessel_state:*")
    for key in keys:
        data = client.hgetall(key)
        data["lat"] = float(data["lat"])
        data["lon"] = float(data["lon"])
        data["speed_knots"] = float(data["speed_knots"])
        data["expected_speed_knots"] = float(data["expected_speed_knots"])
        data["draft_meters"] = float(data["draft_meters"])
        data["is_anomaly"] = True if data["is_anomaly"] == "1" else False
        vessels.append(data)
    return vessels

@app.on_event("startup")
def startup_event():
    global loop_ref
    loop_ref = asyncio.get_running_loop()
    threading.Thread(target=background_stream_processor, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
def read_root():
    with open("static/index.html", "r") as f:
        return f.read()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    initial_vessels = get_all_vessels_internal()
    await websocket.send_text(json.dumps({"type": "vessels_update", "data": initial_vessels}))
    await websocket.send_text(json.dumps({"type": "events_init", "data": list(recent_events)}))
    await websocket.send_text(json.dumps({"type": "alerts_init", "data": get_all_alerts()}))
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/api/vessel/{vessel_id}/history")
def vessel_history(vessel_id: str):
    items = client.lrange(f"vessel_track:{vessel_id}", 0, 199)
    track = [json.loads(i) for i in reversed(items)]
    return {"vessel_id": vessel_id, "track": track}

class SpeedRequest(BaseModel):
    speed: float

@app.post("/api/speed")
def set_simulation_speed(req: SpeedRequest):
    client.set("sim_speed", req.speed)
    return {"status": "success", "sim_speed": req.speed}

@app.post("/api/clear")
def clear_all():
    deleted = 0
    for pattern in ("vessel_state:*", "vessel_track:*", "vessel_meta:*"):
        for key in client.scan_iter(pattern):
            client.delete(key)
            deleted += 1
    recent_events.clear()
    if loop_ref and manager.active_connections:
        asyncio.run_coroutine_threadsafe(
            manager.broadcast(json.dumps({"type": "clear_all"})), loop_ref
        )
    return {"status": "cleared", "keys_deleted": deleted}

@app.post("/api/retrain")
def retrain():
    global model, model_source
    import train as trainer
    r = trainer.retrain_to_redis()
    if r["samples"]:
        model, model_source = load_model()
        model_cache.clear()
    return {
        "samples": r["samples"], "vessel_models": r["vessel_models"], "model_source": model_source,
        "algorithm": "IsolationForest", "n_estimators": 100, "contamination": 0.05,
        "features": ["speed_dev", "accel_kn_per_min", "stopped"],
    }
