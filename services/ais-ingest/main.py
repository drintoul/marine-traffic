import os
import time
import json
import asyncio
import statistics
from collections import deque

import redis
import websockets

REDIS_HOST = os.getenv("REDIS_HOST")
API_KEY = os.getenv("AISSTREAM_API_KEY")
client = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

# Salish Sea: Olympia / Puget Sound through the Strait of Georgia
BOUNDING_BOXES = [[[47.0, -125.0], [49.9, -122.3]]]
AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

NAV_STATUS = {
    0: "Under way using engine", 1: "At anchor", 2: "Not under command",
    3: "Restricted manoeuverability", 4: "Constrained by draught", 5: "Moored",
    6: "Aground", 7: "Engaged in fishing", 8: "Under way sailing",
    9: "Reserved (HSC)", 10: "Reserved (WIG)", 11: "Power-driven vessel towing astern",
    12: "Power-driven vessel pushing ahead", 13: "Reserved", 14: "AIS-SART active",
    15: "Undefined",
}

SHIP_TYPES = {
    30: "Fishing", 31: "Towing", 32: "Towing (large)", 36: "Sailing", 37: "Pleasure craft",
    50: "Pilot vessel", 51: "Search & rescue", 52: "Tug", 53: "Port tender",
    55: "Law enforcement", 58: "Medical",
    **{c: "Passenger" for c in range(60, 70)},
    **{c: "Cargo" for c in range(70, 80)},
    **{c: "Tanker" for c in range(80, 90)},
}

# Rolling SOG history per vessel -> baseline "expected" speed
sog_history = {}
HISTORY_LEN = 40


def zone_for(lat, lon):
    if 49.28 <= lat <= 49.33 and -123.25 <= lon <= -123.13:
        return "Vancouver Harbour / English Bay"
    if 49.08 <= lat <= 49.24 and -123.30 <= lon <= -122.80:
        return "Fraser River Fairway"
    if lat < 48.55:
        return "Strait of Juan de Fuca"
    if lat < 48.9 and lon > -123.4:
        return "Puget Sound"
    return "Strait of Georgia"


def baseline_speed(mmsi, sog):
    hist = sog_history.setdefault(mmsi, deque(maxlen=HISTORY_LEN))
    hist.append(sog)
    return statistics.median(hist)


def handle_static_report(msg):
    data = msg["Message"]["ShipStaticData"]
    meta = msg.get("MetaData", {})
    mmsi = str(data.get("UserID") or meta.get("MMSI"))
    if not mmsi:
        return
    name = (meta.get("ShipName") or data.get("Name") or "").strip()
    mapping = {}
    if name:
        mapping["name"] = name
    imo = data.get("ImoNumber")
    if imo:
        mapping["imo"] = str(imo)
    draught = data.get("MaximumStaticDraught")
    if draught:
        mapping["draught"] = str(draught)
    stype = data.get("Type")
    if stype is not None:
        mapping["ship_type"] = SHIP_TYPES.get(stype, f"Type {stype}")
    if mapping:
        client.hset(f"vessel_meta:{mmsi}", mapping=mapping)


def handle_position_report(msg):
    data = msg["Message"]["PositionReport"]
    meta = msg.get("MetaData", {})
    mmsi = str(data.get("UserID") or meta.get("MMSI"))
    lat = meta.get("latitude") or data.get("Latitude")
    lon = meta.get("longitude") or data.get("Longitude")
    if not mmsi or lat is None or lon is None:
        return

    vessel_meta = client.hgetall(f"vessel_meta:{mmsi}")
    name = (meta.get("ShipName") or vessel_meta.get("name") or "").strip() or f"MMSI {mmsi}"
    if name and "name" not in vessel_meta:
        client.hset(f"vessel_meta:{mmsi}", "name", name)

    sog = float(data.get("Sog") or 0.0)
    vessel_id = f"MMSI-{mmsi}"

    payload = {
        "vessel_id": vessel_id,
        "vessel_name": name,
        "mmsi": mmsi,
        "imo": vessel_meta.get("imo") or "",
        "zone": zone_for(lat, lon),
        "lat": lat,
        "lon": lon,
        "speed_knots": round(sog, 1),
        "expected_speed_knots": round(baseline_speed(mmsi, sog), 1),
        "nav_status": NAV_STATUS.get(data.get("NavigationalStatus", 15), "Undefined"),
        "ship_type": vessel_meta.get("ship_type") or "Unknown",
        "draft_meters": float(vessel_meta.get("draught") or 0.0),
        "timestamp": time.time(),
    }
    client.xadd("maritime_telemetry_stream", {"data": json.dumps(payload)})


async def run():
    while True:
        try:
            async with websockets.connect(AISSTREAM_URL, ping_interval=20) as ws:
                await ws.send(json.dumps({
                    "APIKey": API_KEY,
                    "BoundingBoxes": BOUNDING_BOXES,
                    "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
                }))
                print("Connected to aisstream.io, ingesting live AIS data...")
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        mtype = msg.get("MessageType")
                        if mtype == "PositionReport":
                            handle_position_report(msg)
                        elif mtype == "ShipStaticData":
                            handle_static_report(msg)
                    except Exception as e:
                        print(f"Message handling error: {e}")
        except Exception as e:
            print(f"aisstream connection error: {e} — retrying in 10s")
            await asyncio.sleep(10)


if not API_KEY or API_KEY == "your_aisstream_api_key":
    print("AISSTREAM_API_KEY is not set — register free at https://aisstream.io and update .env")

print("Starting live AIS ingest service (Salish Sea bbox)...")
asyncio.run(run())
