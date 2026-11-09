import json
import pickle
import base64
import time

import pytest
from conftest import load_module


@pytest.fixture
def trainer():
    return load_module("ml_train", "ml-engine/train.py")


def _pts(speeds, base_t=None):
    t = base_t or time.time() - 1000
    return [{"lat": 49.0, "lon": -123.0, "speed": s, "t": t + i * 10} for i, s in enumerate(speeds)]


def test_features_deviation(trainer):
    X = trainer.features_for_points(_pts([14.0] * 10 + [1.0]))
    assert X[-1][0] < -0.8          # big negative deviation vs baseline
    assert X[-1][2] == 1            # stopped flag set


def test_features_normal(trainer):
    X = trainer.features_for_points(_pts([14.0] * 10))
    assert abs(X[-1][0]) < 0.05     # no deviation
    assert X[-1][2] == 0


def test_features_accel(trainer):
    # 14 -> 0 kn over 10s should produce a large negative accel
    X = trainer.features_for_points(_pts([14.0] * 5 + [0.0]))
    assert X[-1][1] < -5


def test_moored_vessel_dev_clamped(trainer):
    # Baseline < 2 kn -> deviation forced to 0 (anchored is normal)
    X = trainer.features_for_points(_pts([0.0] * 10))
    assert X[-1][0] == 0.0


def test_retrain_stores_global_and_vessel_models(trainer):
    vid = "MMSI-111111111"
    for p in _pts([12.0] * 120):
        trainer.client.lpush(f"vessel_track:{vid}", json.dumps(p))
    r = trainer.retrain_to_redis()
    assert r["samples"] == 120
    assert r["vessel_models"] == 1
    blob = trainer.client.get("ml:model")
    assert blob and "IsolationForest" in str(type(pickle.loads(base64.b64decode(blob))))
    assert trainer.client.get(f"ml:model:{vid}")
    meta = json.loads(trainer.client.get("ml:model:meta"))
    assert meta["samples"] == 120 and meta["vessel_models"] == 1


def test_retrain_below_min_samples(trainer):
    for p in _pts([10.0] * 20):
        trainer.client.lpush("vessel_track:MMSI-222222222", json.dumps(p))
    assert trainer.retrain_to_redis()["samples"] == 0
    assert trainer.client.get("ml:model") is None


def test_short_vessel_no_individual_model(trainer):
    for p in _pts([10.0] * 5):
        trainer.client.lpush("vessel_track:MMSI-333333333", json.dumps(p))
    trainer.retrain_to_redis()
    assert trainer.client.get("ml:model:MMSI-333333333") is None
