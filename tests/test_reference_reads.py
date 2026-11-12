"""Synthetic provider responses only. No network, credentials or real samples."""
from datetime import datetime, timedelta, timezone
import json
import subprocess
import sys

import pytest

from backend.api.contracts import ApiError
from backend.api.storage_checks import storage_checks
from backend.references import CachePolicy, ReferenceReader, SampleResponse
from backend.references.__main__ import metadata


RECEIVED = "2026-11-10T01:00:00Z"


def hjnc(rows=None, **extra):
    rows = [{"VOY_NO": "SYNTHETIC-VOYAGE", "YARD_OPEN": "2026-11-10 00:00",
             "YARD_CLOSE": "2026-11-13 01:00", "ETB": "2026-11-13 11:00"}] if rows is None else rows
    return json.dumps({"stringContent": json.dumps(rows), "totalElements": len(rows),
                       "hasNext": False, **extra}).encode()


def road(**extra):
    row = {"startUnitCode": "101 ", "endUnitCode": "102", "stdDate": "20261110",
           "stdTime": "09:00", "timeAvg": "12.5", "timeMin": "10", "timeMax": "15",
           "sumTmUnitTypeCode": "SYNTHETIC", "startEndStdTypeCode": "2",
           "tcsCarTypeCode": "1", "tcsCarTypeDivCode": "1", **extra}
    return json.dumps({"code": "SUCCESS", "count": 1, "realUnitTrtmVO": [row]}).encode()


@pytest.fixture
def state():
    class Clock:
        now = datetime(2026, 11, 10, 1, 0, 10, tzinfo=timezone.utc)

        def __call__(self):
            return self.now

    clock = Clock()
    reader = ReferenceReader("hjnc", kind="simulated", sample_permission_ref="synthetic-test",
                             policy=CachePolicy(300, 600, "synthetic-test-only"), clock=clock)
    return clock, reader


def test_normal_projection_is_reference_only_and_per_item_provenance(state):
    _, reader = state
    result = reader.ingest(SampleResponse(hjnc(), RECEIVED))
    item = result["current"]["items"][0]
    assert item["values"]["YARD_OPEN"] == "2026-11-10 00:00"
    assert item["values"]["ETB"] != item["values"]["YARD_CLOSE"]
    assert item["provenance"] == {"kind": "simulated", "received_at": RECEIVED,
        "source_ref": "https://www.hjnc.co.kr/esvc/vessel/berthScheduleT", "observed_at": None}
    assert result["last_attempt"]["status"] == "received"
    assert result["current"]["freshness"] == "fresh"
    assert "coverage_not_established" in result["current"]["blockers"]
    assert result["engine_conversion"] == "blocked"
    assert result["approval_eligible"] is result["automatic_mock_fallback"] is False


def test_empty_clears_previous_sample_instead_of_reusing_obsolete_rows(state):
    _, reader = state
    reader.ingest(SampleResponse(hjnc(), RECEIVED))
    result = reader.ingest(SampleResponse(hjnc([]), "2026-11-10T01:00:01Z"))
    assert result["last_attempt"]["status"] == "empty"
    assert result["cached"]["items"] == ()
    assert result["last_success"]["item_count"] == 0


@pytest.mark.parametrize("partial", [hjnc(totalElements=24), hjnc(hasNext=True),
    hjnc([{"VOY_NO": "SYNTHETIC-MISSING"}]), hjnc([], totalElements=24)])
def test_partial_does_not_overwrite_last_coherent_sample(state, partial):
    _, reader = state
    reader.ingest(SampleResponse(hjnc(), RECEIVED))
    result = reader.ingest(SampleResponse(partial, "2026-11-10T01:00:01Z"))
    assert result["last_attempt"]["status"] == "partial"
    assert result["last_success"]["status"] == "partial"
    assert result["cached"]["received_at"] == RECEIVED
    assert len(result["cached"]["items"]) == 1


def test_failure_keeps_previous_receipt_but_stale_and_retention_have_exact_boundaries(state):
    clock, reader = state
    reader.ingest(SampleResponse(hjnc(), RECEIVED))
    clock.now = datetime(2026, 11, 10, 1, 5, tzinfo=timezone.utc)
    result = reader.refresh(lambda: (_ for _ in ()).throw(TimeoutError("SECRET URL")))
    assert result["last_attempt"]["status"] == "failed"
    assert result["last_success"]["received_at"] == RECEIVED
    assert result["cached"]["freshness"] == "stale"
    assert "SECRET" not in str(result)
    clock.now += timedelta(seconds=300)
    expired = reader.view()
    assert expired["cached"] is None
    assert expired["last_success"] == result["last_success"]


def test_old_sample_is_stale_immediately_and_cannot_extend_cache_age(state):
    _, reader = state
    result = reader.ingest(SampleResponse(hjnc(), "2026-11-09T01:00:00Z"))
    assert result["current"]["freshness"] == "stale"
    assert result["cached"] is None


@pytest.mark.parametrize("receipt,code", [("2026-11-10T01:01:00Z", "future_received_at"),
    ("2026-11-10 01:00:00", "invalid_received_at"), (RECEIVED, "out_of_order_sample"),
    ("2026-11-10T00:59:59Z", "out_of_order_sample")])
def test_invalid_or_regressing_receipts_cannot_replace_success(state, receipt, code):
    _, reader = state
    reader.ingest(SampleResponse(hjnc(), RECEIVED))
    result = reader.ingest(SampleResponse(hjnc(), receipt))
    assert result["last_attempt"]["error_code"] == code
    assert result["cached"]["received_at"] == RECEIVED


def test_default_reference_reader_retains_no_payload_and_requires_explicit_permissions(state):
    clock, _ = state
    with pytest.raises(ValueError):
        CachePolicy(retain_for_seconds=600)
    with pytest.raises(ValueError):
        ReferenceReader("hjnc", kind="reference", sample_permission_ref="")
    reader = ReferenceReader("hjnc", kind="reference", sample_permission_ref="test-authorization", clock=clock)
    result = reader.ingest(SampleResponse(hjnc(), RECEIVED))
    assert result["current"]["items"][0]["provenance"]["kind"] == "reference"
    assert result["cached"] is None
    assert reader.view()["current"] is None


def test_returned_views_cannot_mutate_cache_or_metadata(state):
    _, reader = state
    result = reader.ingest(SampleResponse(hjnc(), RECEIVED))
    result["cached"]["items"][0]["values"]["VOY_NO"] = "CHANGED"
    result["last_success"]["row_count"] = 999
    assert reader.view()["cached"]["items"][0]["values"]["VOY_NO"] == "SYNTHETIC-VOYAGE"
    assert reader.view()["last_success"]["row_count"] == 1


@pytest.mark.parametrize("responses,attempts", [([503, 200], 2), ([429, 503, 200], 3),
    ([401, 200], 1), ([403, 200], 1), ([404, 200], 1), ([503, 503, 503], 3)])
def test_bounded_http_retries_and_no_auth_retry(state, responses, attempts):
    _, reader = state
    calls, sleeps = [], []
    def load():
        calls.append(1)
        return SampleResponse(hjnc(), RECEIVED, responses[len(calls) - 1])
    result = reader.refresh(load, max_attempts=3, sleeper=sleeps.append)
    assert len(calls) == result["last_attempt"]["attempts"] == attempts
    assert len(sleeps) == attempts - 1


def test_transport_timeout_retries_are_bounded_and_loader_errors_are_sanitized(state):
    _, reader = state
    calls = []
    def load():
        calls.append(1)
        raise TimeoutError("SECRET")
    result = reader.refresh(load, max_attempts=3, sleeper=lambda _: None)
    assert len(calls) == 3
    assert result["last_attempt"]["error_code"] == "transport_error"
    result = reader.refresh(lambda: (_ for _ in ()).throw(ValueError("SECRET")), max_attempts=3)
    assert result["last_attempt"]["error_code"] == "loader_error"
    assert result["last_attempt"]["attempts"] == 1
    assert "SECRET" not in str(result)


@pytest.mark.parametrize("payload", [b"not JSON SECRET", b'{"stringContent":"not JSON SECRET"}',
    hjnc(totalElements=-1), hjnc([{"VOY_NO": "SYNTHETIC", "YARD_OPEN": "bad SECRET"}]), b"x" * 1_000_001])
def test_invalid_sample_never_retries_or_leaks_body(state, payload):
    _, reader = state
    result = reader.refresh(lambda: SampleResponse(payload, RECEIVED), max_attempts=3)
    assert result["last_attempt"]["status"] == "failed"
    assert result["last_attempt"]["attempts"] == 1
    assert "SECRET" not in str(result)


@pytest.mark.parametrize("change", [{}, {"sumTmUnitTypeCode": None}, {"timeAvg": "NaN"},
    {"timeAvg": "20"}, {"stdTime": "09  "}, {"endUnitCode": "103"}])
def test_road_mapping_never_invents_units_or_fills_missing_fields(state, change):
    clock, _ = state
    reader = ReferenceReader("road", kind="simulated", sample_permission_ref="synthetic-test",
                             direction=("101", "102"), clock=clock)
    result = reader.ingest(SampleResponse(road(**change), RECEIVED))
    assert result["current"]["status"] == ("partial" if change else "received")
    assert len(result["current"]["items"]) == (0 if change else 1)
    assert "duration_unit_unconfirmed" in result["current"]["blockers"]
    assert "minutes" not in str(result["current"]["items"])


def test_road_http_200_provider_error_is_not_empty_or_retried(state):
    clock, _ = state
    reader = ReferenceReader("road", kind="reference", sample_permission_ref="test-authorization",
                             direction=("101", "102"), clock=clock)
    result = reader.refresh(lambda: SampleResponse(b'{"code":"ERROR","message":"SECRET"}', RECEIVED),
                            max_attempts=3)
    assert result["last_attempt"]["error_code"] == "provider_error"
    assert result["last_attempt"]["attempts"] == 1
    assert result["last_success"] is result["current"] is result["cached"] is None
    assert "SECRET" not in str(result)


@pytest.mark.parametrize("source", ["kakao", "ors", "aisstream", "unknown"])
def test_unapproved_sources_have_no_adapter_or_cache_path(source):
    with pytest.raises(ValueError):
        ReferenceReader(source, kind="reference", sample_permission_ref="test-authorization",
                        policy=CachePolicy(300, 600, "not-a-provider-permission"))


def test_clock_regression_is_rejected(state):
    clock, reader = state
    reader.ingest(SampleResponse(hjnc(), RECEIVED))
    clock.now -= timedelta(seconds=1)
    with pytest.raises(ValueError):
        reader.view()


@pytest.mark.parametrize("mode", ["mixed", "observed"])
def test_existing_storage_guard_still_rejects_real_input(snapshot, mode):
    snapshot["data_mode"] = mode
    with pytest.raises(ApiError) as error:
        storage_checks(snapshot)
    assert error.value.code == "DEMO_DATA_ONLY"


def test_cli_reads_local_sample_without_printing_rows_or_overwriting_it(tmp_path):
    path = tmp_path / "sample.json"
    raw = hjnc()
    path.write_bytes(raw)
    run = subprocess.run([sys.executable, "-m", "backend.references", "--source", "hjnc",
                          "--kind", "simulated", "--input", str(path), "--received-at", "2000-01-01T00:00:00Z",
                          "--sample-permission-ref", "synthetic-test"], capture_output=True)
    assert run.returncode == 0, run.stderr.decode()
    output = json.loads(run.stdout)
    assert output["current"]["row_count"] == 1
    assert output["cache_enabled"] is False
    assert b"SYNTHETIC-VOYAGE" not in run.stdout
    assert path.read_bytes() == raw


def test_metadata_omits_provider_fields(state):
    _, reader = state
    output = metadata(reader.ingest(SampleResponse(hjnc(), RECEIVED)))
    assert "SYNTHETIC-VOYAGE" not in str(output)


def test_unrecognized_provider_fields_and_error_text_never_enter_retained_data(state):
    _, reader = state
    payload = json.loads(hjnc())
    rows = json.loads(payload["stringContent"])
    rows[0]["apiKey"] = payload["message"] = "SECRET-MUST-NOT-LEAK"
    payload["stringContent"] = json.dumps(rows)
    result = reader.ingest(SampleResponse(json.dumps(payload).encode(), RECEIVED))
    assert result["last_attempt"]["status"] == "received"
    assert "SECRET" not in str(result)
    assert "SECRET" not in str(reader.view())


def test_road_empty_with_zero_total_differs_from_missing_page(state):
    clock, _ = state
    for total, status in ((0, "empty"), (24, "partial")):
        reader = ReferenceReader("road", kind="simulated", sample_permission_ref="synthetic-test",
                                 direction=("101", "102"), clock=clock)
        result = reader.ingest(SampleResponse(json.dumps({"code": "SUCCESS", "count": total,
                                                         "realUnitTrtmVO": []}).encode(), RECEIVED))
        assert result["current"]["status"] == status
        assert result["current"]["items"] == ()


@pytest.mark.parametrize("option", [{"max_attempts": 0}, {"max_attempts": 4},
    {"max_attempts": True}, {"backoff_seconds": float("inf")}, {"backoff_seconds": -1}])
def test_invalid_retry_limits_are_rejected_before_loading(state, option):
    _, reader = state
    calls = []
    with pytest.raises(ValueError):
        reader.refresh(lambda: calls.append(1), **option)
    assert not calls
