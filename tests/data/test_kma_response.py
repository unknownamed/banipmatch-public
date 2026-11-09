import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.audit_kma_response import audit_response, kst_to_utc


RECEIPT = "2026-11-09T14:06:42Z"


def framed(*lines):
    return ("#START7777\n# header\n" + "\n".join(lines) + "\n#7777END\n").encode("cp949")


def sea(wh="1.2", ws="9.1", tm="202611092300"):
    return framed(f"B,{tm},22104,거제도,128.9,34.7667,{wh},335,{ws},11.5,19.4,12.9,1024.0,79.0, ,=")


def warning(level="예비", region="S1311100"):
    return f"S1311000,남해동부앞바다,{region},부산앞바다,202611081600,202611092358,풍랑,{level},발표, ,="


def test_actual_sea_layout_coordinates_do_not_shift_wind_or_wave_columns():
    report = audit_response(sea(), "sea", 200, RECEIPT, "22104")
    observation = report["observations"][0]
    assert observation["observed_at_utc"] == "2026-11-09T14:00:00Z"
    assert observation["received_minus_observed_seconds"] == 402
    assert (observation["wh_m_original"], observation["ws_m_s_original"]) == ("1.2", "9.1")
    assert report["station_mismatch_rows"] == report["future_observation_rows"] == 0
    assert report["engine_conversion"] == "not_performed"


@pytest.mark.parametrize("value", ["-99.0", "", "NaN", "bad"])
def test_missing_or_unknown_wind_is_preserved_and_never_zero_filled(value):
    observation = audit_response(sea(ws=value), "sea", 200, RECEIPT, "22104")["observations"][0]
    assert observation["ws_m_s_original"] == value
    assert observation["missing_or_invalid_nonnegative_fields"] == ["WS"]


def test_zero_is_valid_and_future_observation_is_flagged():
    report = audit_response(sea(wh="0", tm="202611100000"), "sea", 200, RECEIPT, "other")
    assert report["observations"][0]["missing_or_invalid_nonnegative_fields"] == []
    assert report["future_observation_rows"] == report["station_mismatch_rows"] == 1
    just_before = audit_response(sea(), "sea", 200, "2026-11-09T13:59:59.900000Z", "22104")
    assert just_before["future_observation_rows"] == 1


def test_preliminary_period_code_is_not_an_exact_effective_timestamp():
    report = audit_response(framed(warning(), warning("주의", "OTHER")), "warning", 200,
                            RECEIPT, regions=("S1311100",))
    assert report["row_count"] == 2
    assert report["selected_row_count"] == 1
    selected = report["selected_records"][0]
    assert selected["effective_at_utc"] is None
    assert selected["effective_time_original_kst"] == "202611092358"
    assert selected["effective_representation"] == "preliminary_period_code"
    normal = audit_response(framed(warning("주의")), "warning", 200, RECEIPT, regions=("S1311100",))
    assert normal["selected_records"][0]["effective_at_utc"] == "2026-11-09T14:58:00Z"


def test_application_required_error_and_framed_empty_have_distinct_states():
    error = json.dumps({"result": {"message": "활용신청이 필요한 API 입니다."}}, ensure_ascii=False).encode()
    assert audit_response(error, "sea", 403, RECEIPT, "22104")["status"] == "application_required"
    empty = audit_response(framed(), "warning", 200, RECEIPT, regions=("S1311100",))
    assert empty["status"] == "empty_framed_response"
    assert empty["selected_row_count"] == 0
    assert "not_proof" in empty["absence_interpretation"]


@pytest.mark.parametrize("raw", [b"", b"{\"error\":1}", b"#START7777\n", framed("#ERROR failed"),
                                  framed("wrong,column,count"), framed(warning("unknown"))])
def test_incomplete_error_and_changed_format_are_not_valid_empty_data(raw):
    with pytest.raises(ValueError):
        audit_response(raw, "warning", 200, RECEIPT, regions=("S1311100",))


def test_station_metadata_and_timezone_rollover():
    metadata = framed("22104 128.90000000 34.76670000 24000000 0.00 159 거제도 Geojedo 12B20000")
    report = audit_response(metadata, "station", 200, RECEIPT, "22104")
    assert report["stations"][0]["STN_KO"] == "거제도"
    assert kst_to_utc("202601010030") == "2025-12-31T15:30:00Z"
    with pytest.raises(ValueError):
        audit_response(sea(), "sea", 200, "2026-11-09T23:06:42", "22104")


def test_observed_warning_format_without_end_marker_requires_header_and_complete_row():
    raw = ("#START7777\n# REG_UP  REG_UP_KO REG_ID\n" + warning() + "\n").encode("cp949")
    report = audit_response(raw, "warning", 200, RECEIPT, regions=("S1311100",))
    assert report["selected_row_count"] == 1
    assert "not_established" in report["coverage"]
    with pytest.raises(ValueError):
        audit_response(raw[:-3], "warning", 200, RECEIPT, regions=("S1311100",))


def test_cli_preserves_inputs_outputs_and_hides_bad_argument_values(tmp_path):
    source, out = tmp_path / "sample.txt", tmp_path / "out.json"
    source.write_bytes(sea())
    script = Path(__file__).resolve().parents[2] / "tools/audit_kma_response.py"
    command = [sys.executable, str(script), "--input", str(source), "--kind", "sea",
               "--http-status", "200", "--received-at", RECEIPT, "--station", "22104", "--output"]
    assert subprocess.run(command + [str(out)], capture_output=True).returncode == 0
    saved = out.read_bytes()
    assert subprocess.run(command + [str(out)], capture_output=True).returncode == 1
    assert out.read_bytes() == saved
    assert subprocess.run(command + [str(source)], capture_output=True).returncode == 1
    assert source.read_bytes() == sea()
    failed = subprocess.run(command + [str(out), "--unknown", "private-value"], capture_output=True)
    assert failed.returncode == 2
    assert b"private-value" not in failed.stdout + failed.stderr
