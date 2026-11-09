import json

import pytest
from conftest import load_module


@pytest.fixture
def ais():
    return load_module("ais_ingest", "ais-ingest/main.py")


def test_zone_mapping(ais):
    assert ais.zone_for(49.29, -123.19) == "Vancouver Harbour / English Bay"
    assert ais.zone_for(49.15, -123.05) == "Fraser River Fairway"
    assert ais.zone_for(48.45, -123.3) == "Strait of Juan de Fuca"
    assert ais.zone_for(48.7, -122.9) == "Puget Sound"
    assert ais.zone_for(49.5, -123.8) == "Strait of Georgia"


def test_baseline_speed_is_rolling_median(ais):
    ais.sog_history.clear()
    for s in [14.0, 14.0, 14.0]:
        ais.baseline_speed("M1", s)
    assert ais.baseline_speed("M1", 14.0) == 14.0
    # One slow reading shouldn't move the median much
    assert ais.baseline_speed("M1", 3.0) == 14.0


def test_baseline_speed_caps_history(ais):
    ais.sog_history.clear()
    for _ in range(ais.HISTORY_LEN + 10):
        ais.baseline_speed("M1", 5.0)
    assert len(ais.sog_history["M1"]) == ais.HISTORY_LEN


def _static_msg(mmsi="366710820", name="WSF SEALTH", imo=7808152, draught=6.1, stype=60):
    return {
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": mmsi, "ShipName": name},
        "Message": {"ShipStaticData": {
            "UserID": mmsi, "ImoNumber": imo, "Name": name,
            "MaximumStaticDraught": draught, "Type": stype,
        }},
    }


def _position_msg(mmsi="366710820", lat=48.53, lon=-122.76, sog=16.6, nav=0):
    return {
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": mmsi, "latitude": lat, "longitude": lon},
        "Message": {"PositionReport": {
            "UserID": mmsi, "Sog": sog, "NavigationalStatus": nav,
        }},
    }


def test_static_report_caches_meta(ais):
    ais.handle_static_report(_static_msg())
    meta = ais.client.hgetall("vessel_meta:366710820")
    assert meta["name"] == "WSF SEALTH"
    assert meta["imo"] == "7808152"
    assert meta["draught"] == "6.1"
    assert meta["ship_type"] == "Passenger"


def test_position_report_emits_telemetry(ais):
    ais.handle_static_report(_static_msg())
    ais.handle_position_report(_position_msg())
    entries = ais.client.xrange("maritime_telemetry_stream")
    assert len(entries) == 1
    payload = json.loads(entries[0][1]["data"])
    assert payload["vessel_name"] == "WSF SEALTH"
    assert payload["speed_knots"] == 16.6
    assert payload["zone"] == "Strait of Juan de Fuca"
    assert payload["ship_type"] == "Passenger"
    assert payload["draft_meters"] == 6.1


def test_position_report_always_uses_mmsi_id(ais):
    # Regression: vessel_id must be stable regardless of when IMO arrives —
    # previously it flipped MMSI-x -> IMO-x causing duplicate vessels.
    ais.handle_position_report(_position_msg())          # no IMO known yet
    ais.handle_static_report(_static_msg())              # IMO arrives
    ais.handle_position_report(_position_msg(sog=15.0))  # report after IMO
    entries = ais.client.xrange("maritime_telemetry_stream")
    ids = {json.loads(e[1]["data"])["vessel_id"] for e in entries}
    assert ids == {"MMSI-366710820"}
    payload = json.loads(entries[-1][1]["data"])
    assert payload["imo"] == "7808152"


def test_position_report_missing_coords_skipped(ais):
    ais.handle_position_report({
        "MessageType": "PositionReport",
        "MetaData": {"MMSI": "123"},
        "Message": {"PositionReport": {"UserID": "123", "Sog": 5.0}},
    })
    assert ais.client.xlen("maritime_telemetry_stream") == 0
