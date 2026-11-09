import pytest
from conftest import load_module


@pytest.fixture
def worker():
    return load_module("agent_worker", "agent-worker/worker.py")


def _details(**over):
    d = {
        "vessel_id": "MMSI-1", "vessel_name": "TEST SHIP", "mmsi": "1",
        "zone": "Strait of Georgia", "lat": 49.0, "lon": -123.0,
        "speed_knots": 2.0, "expected_speed_knots": 14.0,
        "nav_status": "Underway", "draft_meters": 0.0, "timestamp": 0.0,
    }
    d.update(over)
    return d


def test_prompt_is_english_only(worker):
    assert "Respond in English only" in worker.build_prompt(_details())


def test_prompt_omits_zero_draught(worker):
    p = worker.build_prompt(_details(draft_meters=0.0))
    assert "Draught" not in p


def test_prompt_includes_draught_when_known(worker):
    p = worker.build_prompt(_details(draft_meters=11.4))
    assert "11.4 meters" in p


def test_prompt_contains_vessel_context(worker):
    p = worker.build_prompt(_details())
    assert "TEST SHIP" in p and "Strait of Georgia" in p and "MMSI-1" in p
