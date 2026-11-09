import csv
import io
import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools.audit_collected_samples import GATE_COLUMNS, audit_gate, audit_hjnc, build_audit


def gate_bytes(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(GATE_COLUMNS)
    writer.writerows(rows)
    return stream.getvalue().encode("cp949")


def gate_row(end="2026-01-01 10:23", work="00:23"):
    return ["PRIVATE-PLATE", "1번", "2026-01-01 10:00", "2번", end, work]


def hjnc_bytes():
    row = {"VOY_NO": "PRIVATE-VOYAGE", "YARD_OPEN": "2026-11-01 00:00",
           "YARD_CLOSE": "2026-11-04 01:00", "ETB": "2026-11-04 11:00"}
    return json.dumps({"content": [], "stringContent": json.dumps([row, row]),
                       "totalElements": 22, "hasNext": False}).encode()


def test_gate_keeps_empty_and_invalid_rows_out_of_statistics_without_hiding_counts():
    rows = [gate_row(), [""] * 6, gate_row(work="00:22"), gate_row(end="bad"),
            gate_row(end="2026-01-01 09:59"), gate_row(work="00:99")]
    rows[-1][1] = ""
    report = audit_gate(gate_bytes(rows))
    assert report["physical_data_rows"] == 6
    assert report["all_fields_empty_rows"] == 1
    assert report["nonempty_rows"] == 5
    assert report["invalid_time_rows"] == report["negative_elapsed_rows"] == 1
    assert report["invalid_work_time_rows"] == 1
    assert report["missing_by_column_nonempty"]["진입게이트"] == 1
    assert report["elapsed_minutes_nearest_rank"]["count"] == 3
    assert report["elapsed_vs_work_time_comparable_rows"] == 2
    assert report["elapsed_minus_work_minutes_histogram"] == {"0": 1, "1": 1}


def test_gate_nearest_rank_and_zero_duration_are_preserved():
    rows = [gate_row(end="2026-01-01 10:00", work="00:00"), gate_row(work="00:24")]
    report = audit_gate(gate_bytes(rows))
    assert report["elapsed_minutes_nearest_rank"] == {"count": 2, "min": 0, "max": 23,
                                                      "p50": 0, "p90": 23, "p95": 23}
    assert report["elapsed_minus_work_minutes_histogram"] == {"-1": 1, "0": 1}
    assert audit_gate(gate_bytes([[""] * 6]))["elapsed_minutes_nearest_rank"] is None


def test_bad_csv_structure_is_rejected():
    with pytest.raises(ValueError, match="열 수"):
        audit_gate(gate_bytes([gate_row() + ["unexpected"]]))
    with pytest.raises(ValueError, match="열/순서"):
        audit_gate(b"wrong,header\n")


def test_hjnc_nested_response_does_not_claim_complete_history_or_timezone():
    report = audit_hjnc(hjnc_bytes())
    assert report["row_count"] == 2
    assert report["duplicate_nonempty_voyage_ids"] == 1
    assert report["reported_total_matches_rows"] is False
    assert report["reported_has_next"] is False
    assert report["time_zone"] == "unconfirmed"
    assert report["change_history"] == "not_established"
    assert not any(report["missing_or_nontext"].values())
    with pytest.raises(ValueError):
        audit_hjnc(b'{"stringContent":"[1]"}')


def test_report_is_deterministic_and_does_not_include_identifiers():
    first = build_audit(hjnc_bytes(), gate_bytes([gate_row()]))
    assert first == build_audit(hjnc_bytes(), gate_bytes([gate_row()]))
    text = json.dumps(first)
    assert "PRIVATE-PLATE" not in text
    assert "PRIVATE-VOYAGE" not in text
    assert len(first["hjnc"]["sha256"]) == 64


def test_cli_preserves_raw_and_existing_output_and_returns_failure(tmp_path):
    h, g, out = (tmp_path / name for name in ("h.json", "g.csv", "out.json"))
    h.write_bytes(hjnc_bytes())
    g.write_bytes(gate_bytes([gate_row()]))
    script = Path(__file__).resolve().parents[2] / "tools/audit_collected_samples.py"
    command = [sys.executable, str(script), "--hjnc", str(h), "--gate-csv", str(g), "--output"]
    assert subprocess.run(command + [str(out)], capture_output=True).returncode == 0
    saved = out.read_bytes()
    assert subprocess.run(command + [str(out)], capture_output=True).returncode == 1
    assert out.read_bytes() == saved
    assert subprocess.run(command + [str(g)], capture_output=True).returncode == 2
    assert g.read_bytes() == gate_bytes([gate_row()])
    g.write_bytes(b"bad")
    target = tmp_path / "bad.json"
    assert subprocess.run(command + [str(target)], capture_output=True).returncode == 2
    assert not target.exists()
