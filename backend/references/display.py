"""Strict public projection of operator-collected reference evidence, no raw data or secrets."""
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from backend.api.contracts import ApiError


class PublicModel(BaseModel):
    model_config = ConfigDict(extra='ignore', strict=True)


class Values(PublicModel):
    VOY_NO: str
    YARD_OPEN: str
    YARD_CLOSE: str
    ETB: str


class Provenance(PublicModel):
    kind: Literal['reference']
    source_ref: str
    received_at: str
    observed_at: str | None


class Item(PublicModel):
    values: Values
    provenance: Provenance


class Sample(PublicModel):
    status: Literal['received', 'empty', 'partial']
    items: list[Item] = Field(max_length=100)
    row_count: int
    reported_count: int | None
    excluded_rows: int
    blockers: list[str]
    received_at: str
    freshness: Literal['fresh', 'stale']


class Attempt(PublicModel):
    at: str
    status: Literal['received', 'empty', 'partial', 'failed']
    error_code: str | None
    attempts: int


class Success(PublicModel):
    received_at: str
    status: str
    row_count: int
    item_count: int


class Hjnc(PublicModel):
    model_version: str
    source: Literal['hjnc']
    source_ref: str
    kind: Literal['reference']
    checked_at: str
    last_attempt: Attempt | None
    last_success: Success | None
    current: Sample | None
    cached: None = None
    engine_conversion: Literal['blocked']
    approval_eligible: Literal[False]
    automatic_mock_fallback: Literal[False]


class Observation(PublicModel):
    station_id: str
    observed_at_utc: str
    original_time_kst: str
    wh_m_original: str
    ws_m_s_original: str
    gust_m_s_original: str
    missing_or_invalid_nonnegative_fields: list[str]


class Warning(PublicModel):
    region_id: str
    region_name: str
    published_at_utc: str
    effective_at_utc: str | None
    effective_time_original_kst: str
    effective_representation: str
    kind: str
    level: str
    command: str


class WeatherReport(PublicModel):
    row_count: int = 0
    observations: list[Observation] = []
    selected_records: list[Warning] = []
    future_observation_rows: int = 0
    station_mismatch_rows: int = 0


class Weather(PublicModel):
    source: str
    kind: Literal['sea', 'warning']
    source_ref: str
    status: str
    received_at: str | None
    http_status: int | None
    report: WeatherReport | None


class RoadPoint(PublicModel):
    label: str
    longitude: FiniteFloat = Field(ge=-180, le=180)
    latitude: FiniteFloat = Field(ge=-90, le=90)
    source_snap_m: FiniteFloat | None = Field(ge=0)
    destination_snap_m: FiniteFloat | None = Field(ge=0)


class RoadCell(PublicModel):
    origin: int = Field(ge=0, le=2)
    destination: int = Field(ge=0, le=2)
    duration_seconds: FiniteFloat | None = Field(ge=0)
    distance_meters: FiniteFloat | None = Field(ge=0)


class Road(PublicModel):
    source: Literal['openrouteservice']
    kind: Literal['reference']
    profile: Literal['driving-hgv']
    status: Literal['key_missing', 'received', 'partial', 'auth_error', 'rate_limited', 'http_error', 'invalid_response']
    received_at: str | None
    http_status: int | None
    retry_after_seconds: int | None = Field(ge=0, le=86400)
    points: list[RoadPoint] = Field(max_length=3)
    cells: list[RoadCell] = Field(max_length=9)
    engine_conversion: Literal['blocked']
    approval_eligible: Literal[False]
    automatic_mock_fallback: Literal[False]
    coordinates_are_approximate: Literal[True]
    realtime_traffic: Literal[False]
    truck_access_verified: Literal[False]


class LiveDisplay(PublicModel):
    schema_version: Literal['reference-display-1']
    kind: Literal['reference']
    checked_at: str
    engine_conversion: Literal['blocked']
    approval_eligible: Literal[False]
    automatic_mock_fallback: Literal[False]
    hjnc: Hjnc
    weather: list[Weather] = Field(max_length=2)
    ais: 'AisStatus | None' = None
    road: Road | None = None


class AisStatus(PublicModel):
    source: Literal['aisstream.io']
    started_at: str
    finished_at: str
    trial_bbox: list[float]
    max_seconds: int
    status: str
    connection_closed: bool
    subscription_confirmed: bool
    unique_position_mmsi_count: int
    valid_position_events: int
    voyage_link_verified: Literal[False]


LiveDisplay.model_rebuild()


def read_display(path: Path | None, *, now=None):
    if path is None:
        raise ApiError(503, 'REFERENCE_NOT_CONFIGURED', '실제 자료 수신 경로를 설정하지 않았습니다.')
    try:
        with path.open('rb') as f:
            raw = f.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError()
        result = LiveDisplay.model_validate(json.loads(raw))
        at = now or datetime.now(timezone.utc)
        for sample in (result.hjnc.current,):
            if sample:
                age = (at - datetime.fromisoformat(sample.received_at.replace('Z', '+00:00'))).total_seconds()
                if age < 0: raise ValueError()
                sample.freshness = 'stale' if age >= 300 else 'fresh'
        result.hjnc.checked_at = at.isoformat().replace('+00:00', 'Z')
        return result
    except Exception:
        raise ApiError(503, 'REFERENCE_UNAVAILABLE', '실제 자료를 읽지 못했습니다. 모의로 대체하지 않습니다.') from None
