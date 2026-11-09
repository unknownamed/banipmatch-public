import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.audit_road_response import audit_response


def encoded(rows, count=None, code="SUCCESS"):
    return json.dumps({"code": code, "realUnitTrtmVO": rows,
                       "count": len(rows) if count is None and rows is not None else count,
                       "pageNo": 1, "numOfRows": 5}).encode()


def row(**overrides):
    return {"startUnitCode": "101 ", "endUnitCode": "102 ", "stdDate": "20261109",
            "stdTime": "00:15", "sumTmUnitTypeCode": None, "timeAvg": "10.75",
            "timeMin": "7.883333", "timeMax": "9.883333", **overrides}


def test_http_200_provider_error_is_not_empty_or_success():
    report = audit_response(encoded(None, 0, "ERROR"), "101", "102", 200)
    assert report["status"] == "provider_error"
    assert "row_count" not in report
    assert audit_response(b"bad", "101", "102", 503)["status"] == "http_error"
    empty = audit_response(encoded([]), "101", "102", 200)
    assert empty["status"] == "empty"
    assert empty["row_count"] == 0
    assert empty["engine_conversion"] == "blocked"


def test_quality_issues_do_not_become_engine_times():
    report = audit_response(encoded([row(), row(stdTime="00  ", timeAvg="8")], 239), "101", "102", 200)
    assert report["status"] == "sample_received"
    assert report["reported_count"] == 239
    assert report["row_count"] == 2
    assert report["issues"] == {"min_mean_max_inconsistent_rows": 1, "padded_unit_code_fields": 4}
    assert report["missing_or_nontext"]["sumTmUnitTypeCode"] == 2
    assert report["time_forms"] == {"hh_mm": 1, "hour_only_unresolved_bucket": 1}
    assert report["unit"] == report["source_time_zone"] == "unconfirmed"
    assert report["coverage"] == "not_established"
    assert "minutes" not in report


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", "-1", "bad"])
def test_unknown_negative_and_nonfinite_values_are_not_zero(value):
    report = audit_response(encoded([row(timeAvg=value, stdDate="20260230", stdTime="24:01")]), "102", "101", 200)
    assert report["issues"]["missing_or_invalid_time_value_rows"] == 1
    assert report["issues"]["invalid_date_rows"] == 1
    assert report["issues"]["requested_direction_mismatch"] == 2
    assert report["time_forms"] == {"missing_or_unrecognized": 1}


@pytest.mark.parametrize("rows,count", [(None, 0), ([1], 1), ([row()], 0)])
def test_malformed_success_envelope_is_rejected(rows, count):
    with pytest.raises(ValueError):
        audit_response(encoded(rows, count), "101", "102", 200)


def test_cli_does_not_overwrite_input_or_existing_output(tmp_path):
    source, output = tmp_path / "source.json", tmp_path / "report.json"
    raw = encoded([row()])
    source.write_bytes(raw)
    script = Path(__file__).resolve().parents[2] / "tools/audit_road_response.py"
    command = [sys.executable, str(script), "--input", str(source), "--start", "101", "--end", "102",
               "--http-status", "200", "--output"]
    assert subprocess.run(command + [str(output)], capture_output=True).returncode == 0
    saved = output.read_bytes()
    assert subprocess.run(command + [str(output)], capture_output=True).returncode == 1
    assert output.read_bytes() == saved
    assert subprocess.run(command + [str(source)], capture_output=True).returncode == 1
    assert source.read_bytes() == raw
    failed = subprocess.run(command + [str(output), "--unknown", "private-test-value"], capture_output=True)
    assert failed.returncode == 2
    assert b"private-test-value" not in failed.stdout + failed.stderr
