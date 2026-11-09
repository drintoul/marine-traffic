from pydantic import BaseModel
from typing import Optional

class MaritimeTelemetryPayload(BaseModel):
    vessel_id: str
    vessel_name: str
    mmsi: str
    zone: str
    lat: float
    lon: float
    speed_knots: float
    expected_speed_knots: float
    nav_status: str
    draft_meters: float
    timestamp: float

class MaritimeAnomalyEvent(BaseModel):
    vessel_id: str
    anomaly_score: float
    is_anomaly: bool
    details: MaritimeTelemetryPayload
