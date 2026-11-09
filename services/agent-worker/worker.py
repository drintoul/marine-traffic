import os
import time
import json
import requests
import redis

REDIS_HOST = os.getenv("REDIS_HOST")
OLLAMA_HOST = os.getenv("OLLAMA_HOST")
client = redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

print("LLM Port Operations Agent started, listening to maritime anomalies...")

last_id = "0-0"
while True:
    try:
        streams = client.xread({"maritime_anomaly_stream": last_id}, count=5, block=3000)
        if not streams:
            continue
        for stream_name, messages in streams:
            for msg_id, data in messages:
                last_id = msg_id
                event = json.loads(data["data"])
                details = event["details"]

                draught = float(details.get('draft_meters') or 0)
                draught_line = f"\n                - Vessel Draught: {draught} meters" if draught > 0 else ""
                prompt = f"""
                You are an autonomous Port Operations and Vessel Traffic Services (VTS) Copilot for coastal British Columbia.
                A maritime navigation anomaly has been detected:
                - Vessel Name: {details['vessel_name']} (IMO: {details['vessel_id']}, MMSI: {details['mmsi']})
                - Operating Zone: {details['zone']}
                - Current Speed: {details['speed_knots']} knots (Expected: {details['expected_speed_knots']} knots)
                - Navigational Status: {details['nav_status']}{draught_line}

                Provide a concise 2-sentence operational advisory for marine pilots/harbour authorities and draft an automated safety broadcast notice.
                Respond in English only.
                """

                try:
                    response = requests.post(f"{OLLAMA_HOST}/api/generate", json={
                        "model": "qwen2.5:14b",
                        "prompt": prompt,
                        "stream": False
                    }, timeout=30)

                    if response.status_code == 200:
                        action_plan = response.json().get("response", "No response generated.")
                        print(f"\n--- PORT OPS ADVISORY FOR {details['vessel_name']} ---")
                        print(action_plan)
                        print("----------------------------------------------------\n")
                        client.xadd("maritime_advisory_stream", {"data": json.dumps({
                            "vessel_id": details["vessel_id"],
                            "vessel_name": details["vessel_name"],
                            "zone": details["zone"],
                            "advisory": action_plan,
                            "timestamp": time.time()
                        })})
                    else:
                        print(f"Failed to reach Ollama: {response.status_code}")
                except Exception as ollama_err:
                    print(f"Ollama connection error: {ollama_err}")

    except Exception as e:
        print(f"Worker error: {e}")
        time.sleep(2)
