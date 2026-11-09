import os
import json
import base64
import pickle

import numpy as np
import pytest
from sklearn.ensemble import IsolationForest
from conftest import load_module, SERVICES


@pytest.fixture(scope="module")
def server():
    # server.py mounts StaticFiles(directory="static") at import — needs cwd
    cwd = os.getcwd()
    os.chdir(os.path.join(SERVICES, "ml-engine"))
    try:
        yield load_module("ml_server", "ml-engine/server.py")
    finally:
        os.chdir(cwd)


def test_load_model_synthetic_fallback(server):
    m, source = server.load_model()
    assert "synthetic" in source
    assert isinstance(m, IsolationForest)


def test_model_for_falls_back_to_global(server):
    server.model_cache.clear()
    assert server.model_for("MMSI-unknown") is server.model


def test_model_for_uses_vessel_model(server):
    rng = np.random.RandomState(0)
    vm = IsolationForest(random_state=0).fit(rng.uniform(-1, 1, (60, 3)))
    server.client.set("ml:model:MMSI-vip", base64.b64encode(pickle.dumps(vm)).decode())
    server.model_cache.clear()
    got = server.model_for("MMSI-vip")
    assert got is not server.model and isinstance(got, IsolationForest)
    server.model_cache.clear()


def test_get_all_vessels_internal(server):
    server.client.hset("vessel_state:MMSI-1", mapping={
        "vessel_id": "MMSI-1", "vessel_name": "TEST", "lat": "49.0", "lon": "-123.0",
        "speed_knots": "10", "expected_speed_knots": "12", "draft_meters": "0",
        "nav_status": "Underway", "is_anomaly": "1", "mmsi": "1", "zone": "Z",
        "timestamp": "1", "anomaly_score": "0.1", "last_updated": "1",
    })
    vessels = server.get_all_vessels_internal()
    assert len(vessels) == 1
    v = vessels[0]
    assert v["vessel_name"] == "TEST" and v["lat"] == 49.0 and v["is_anomaly"] is True


def test_root_serves_dashboard(server):
    from fastapi.testclient import TestClient
    r = TestClient(server.app).get("/")
    assert r.status_code == 200 and "BC Maritime" in r.text


def test_vessel_history_endpoint(server):
    from fastapi.testclient import TestClient
    for i in range(3):
        server.client.lpush("vessel_track:MMSI-9", json.dumps(
            {"lat": 49.0 + i * 0.001, "lon": -123.0, "speed": 10.0, "t": 1000 + i}))
    r = TestClient(server.app).get("/api/vessel/MMSI-9/history")
    assert r.status_code == 200
    track = r.json()["track"]
    assert len(track) == 3
    assert track[-1]["t"] == 1002          # oldest-first ordering
    assert track[-1]["lat"] == 49.002


def test_clear_endpoint_wipes_vessel_keys(server):
    from fastapi.testclient import TestClient
    server.client.hset("vessel_state:MMSI-1", "x", "1")
    server.client.lpush("vessel_track:MMSI-1", "{}")
    server.client.hset("vessel_meta:1", "name", "X")
    r = TestClient(server.app).post("/api/clear")
    assert r.status_code == 200
    assert not server.client.keys("vessel_state:*")
    assert not server.client.keys("vessel_track:*")
    assert not server.client.keys("vessel_meta:*")


def test_anomaly_model_flags_big_deviation(server):
    m, _ = server.load_model()
    assert m.predict(np.array([[-0.9, -10.0, 1]]))[0] == -1   # stopped, big drop
    assert m.predict(np.array([[0.0, 0.2, 0]]))[0] == 1        # normal cruising
