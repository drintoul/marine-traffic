import os
import json
import time
import base64
import pickle

import numpy as np
import redis
from sklearn.ensemble import IsolationForest

client = redis.Redis(host=os.getenv("REDIS_HOST"), port=6379, decode_responses=True)

MIN_SAMPLES = 100
MIN_VESSEL_SAMPLES = 50
MODEL_KEY = "ml:model"
META_KEY = "ml:model:meta"


def features_for_points(pts):
    X = []
    hist, prev = [], None
    for p in pts:
        hist.append(p["speed"])
        hist = hist[-40:]
        baseline = sorted(hist)[len(hist) // 2]
        dev = 0.0 if baseline < 2.0 else (p["speed"] - baseline) / baseline
        accel = 0.0
        if prev:
            dt = max(p["t"] - prev["t"], 5)
            accel = max(-30.0, min(30.0, (p["speed"] - prev["speed"]) / (dt / 60)))
        stopped = 1 if p["speed"] < 2.0 and baseline >= 5.0 else 0
        X.append([dev, accel, stopped])
        prev = p
    return X


def fit(X):
    model = IsolationForest(contamination=0.05, random_state=42)
    model.fit(np.array(X))
    return base64.b64encode(pickle.dumps(model)).decode()


def retrain_to_redis():
    all_X, vessel_models = [], 0
    for key in client.scan_iter("vessel_track:*"):
        vessel_id = key.split(":", 1)[1]
        pts = [json.loads(i) for i in client.lrange(key, 0, -1)]
        pts.reverse()
        X = features_for_points(pts)
        all_X.extend(X)
        if len(X) >= MIN_VESSEL_SAMPLES:
            client.set(f"{MODEL_KEY}:{vessel_id}", fit(X))
            vessel_models += 1

    if len(all_X) < MIN_SAMPLES:
        return {"samples": 0, "vessel_models": 0}
    client.set(MODEL_KEY, fit(all_X))
    client.set(META_KEY, json.dumps({
        "samples": len(all_X), "vessel_models": vessel_models, "trained_at": time.time()
    }))
    return {"samples": len(all_X), "vessel_models": vessel_models}


if __name__ == "__main__":
    r = retrain_to_redis()
    if r["samples"]:
        print(f"Global model: {r['samples']} samples · {r['vessel_models']} per-vessel models")
    else:
        print(f"Fewer than {MIN_SAMPLES} samples — model unchanged")
