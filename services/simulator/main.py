import os
import time
import random
import json
import redis

REDIS_HOST = os.getenv("REDIS_HOST")
client = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

FLEET = [
    {"vessel_id": "IMO-9812345", "vessel_name": "MV PACIFIC LEADER", "mmsi": "316012345", "zone": "Strait of Georgia", "lat": 49.2000, "lon": -123.3500, "expected_speed": 16.5},
    {"vessel_id": "IMO-9234567", "vessel_name": "FRASER RIVER TUG #4", "mmsi": "316098765", "zone": "Fraser River Fairway", "lat": 49.1950, "lon": -123.0800, "expected_speed": 8.0},
]

print("Starting BC Maritime AIS Simulator (Speed-Adaptive)...")

while True:
    try:
        speed_multiplier = float(client.get("sim_speed") or 1.0)
    except Exception:
        speed_multiplier = 1.0

    for vessel in FLEET:
        is_disrupted = random.random() < (0.15 * speed_multiplier)
        speed_delta = -14.0 if is_disrupted else random.uniform(-0.5, 0.5)
        current_speed = max(0.0, vessel["expected_speed"] + speed_delta)

        status = "Under way using engine"
        if current_speed < 1.0:
            status = "Stopped / Unplanned Anchoring (Possible Drift)"

        payload = {
            "vessel_id": vessel["vessel_id"],
            "vessel_name": vessel["vessel_name"],
            "mmsi": vessel["mmsi"],
            "zone": vessel["zone"],
            "lat": vessel["lat"] + (random.random() - 0.5) * 0.005,
            "lon": vessel["lon"] + (random.random() - 0.5) * 0.005,
            "speed_knots": round(current_speed, 1),
            "expected_speed_knots": vessel["expected_speed"],
            "nav_status": status,
            "draft_meters": 11.4,
            "timestamp": time.time()
        }

        client.xadd("maritime_telemetry_stream", {"data": json.dumps(payload)})

    sleep_time = max(0.5, 5.0 / speed_multiplier)
    time.sleep(sleep_time)
