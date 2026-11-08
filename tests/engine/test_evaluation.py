"""Evidence boundaries: independent checks, fair pairing and failure retention."""
from copy import deepcopy
import json

import pytest

from backend.engine import solve
from tools import evaluate_engine as evaluation


def protocol_file(tmp_path, snapshot):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(snapshot), encoding="utf-8")
    protocol = dict(schema_version=1, base_git_head="e2d9151", methods=["B0", "B1", "B2", "B3"],
                    solver_seeds=[0, 17], cases=[dict(id="case", input="input.json", budget_seconds=3,
                                                   sha256=evaluation.sha256(source))],
                    engine_source_sha256={p.relative_to(evaluation.ROOT).as_posix(): evaluation.sha256(p)
                                          for p in (evaluation.ROOT / "backend/engine").glob("*.py")})
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(protocol), encoding="utf-8")
    return path


def test_independent_audit_rejects_tampered_metrics_and_fixed_record(snapshot):
    result = solve(snapshot, "B1", {"seed": 0, "time_limit_seconds": 3})
    assert evaluation.audit_result(snapshot, result)["schedule"] == "passed"
    changed = deepcopy(result)
    changed["metrics"]["movable_travel_minutes"] += 1
    assert evaluation.audit_result(snapshot, changed)["failed"]
    changed = deepcopy(result)
    frozen = {j["job_id"] for j in snapshot["jobs"] if j["frozen"]}
    row = next(a for a in changed["assignments"] if a["job_id"] in frozen)
    row["sequence"] += 100
    with pytest.raises(ValueError, match="고정"):
        evaluation.audit_result(snapshot, changed)
    assert result["validation_status"] == "not_run" and result["approval_eligible"] is False


def test_baseline_integrity_is_not_schedule_failure(snapshot):
    result = solve(snapshot, "B0", {"seed": 0, "time_limit_seconds": 3})
    assert evaluation.audit_result(snapshot, result) == dict(
        integrity="passed", schedule="baseline_not_applicable", failed=False)


def pair_record(method, unassigned=0, assigned=("A", "B")):
    return dict(case_id="case", input_sha256="hash", budget_seconds=3, seed=0, method=method,
                wall_ms=10, audit={"schedule": "passed"}, result=dict(assignments=[{"job_id": j} for j in assigned],
                metrics=dict(unassigned_count=unassigned, fixed_risk_count=0, movable_violation_count=0,
                             changed_job_ids=[], movable_travel_minutes=5)))


def test_pairing_excludes_unequal_throughput_and_flags_equal_count_different_jobs():
    a = pair_record("B2", 1, ("A",))
    b = pair_record("B3", 0)
    pair = evaluation.make_pairs([a, b])[0]
    assert not pair["equal_count_comparable"]
    assert "different_unassigned_count" in pair["exclusion_reason"]
    b = pair_record("B3", 1, ("B",))
    pair = evaluation.make_pairs([a, b])[0]
    assert pair["equal_count_comparable"] and not pair["identical_assigned_set"]
    b["audit"]["schedule"] = "failed"
    assert not evaluation.make_pairs([a, b])[0]["equal_count_comparable"]


def test_protocol_checks_input_and_engine_hashes(tmp_path, snapshot):
    path = protocol_file(tmp_path, snapshot)
    evaluation.load_protocol(path)
    source = tmp_path / "input.json"
    source.write_text(source.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(ValueError, match="hash"):
        evaluation.load_protocol(path)
    path = protocol_file(tmp_path, snapshot)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["engine_source_sha256"].pop(next(iter(data["engine_source_sha256"])))
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Engine source"):
        evaluation.load_protocol(path)


def test_exception_runs_preserved_and_nonzero(tmp_path, snapshot, monkeypatch):
    path = protocol_file(tmp_path, snapshot)
    def failing_solve(*args):
        raise RuntimeError("deliberate failure")
    monkeypatch.setattr(evaluation, "solve", failing_solve)
    output = tmp_path / "results"
    assert evaluation.run(path, output) == 1
    records = [json.loads(line) for line in (output / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(records) == 8 and all(r["error"]["type"] == "RuntimeError" for r in records)
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["failures"] == 8 and summary["equal_count_comparable"] == 0
    metadata = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["completed"] and metadata["completed_runs"] == 8
    assert metadata["protocol_sha256"] == evaluation.sha256(path)


@pytest.mark.parametrize("failure", ["mutation", "metric"])
def test_returned_raw_result_retained_on_mutation_or_failed_audit(tmp_path, snapshot, monkeypatch, failure):
    path = protocol_file(tmp_path, snapshot)
    good = solve(snapshot, "B1", {"seed": 0, "time_limit_seconds": 3})
    def corrupt_solve(value, method, config):
        result = deepcopy(good)
        result["method"] = method
        if failure == "mutation":
            value["scenario_id"] = "mutated"
        elif method != "B0":
            result["metrics"]["movable_travel_minutes"] += 1
        return result
    monkeypatch.setattr(evaluation, "solve", corrupt_solve)
    output = tmp_path / "results"
    assert evaluation.run(path, output) == 1
    records = [json.loads(line) for line in (output / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(records) == 8 and all("result" in r for r in records)
    adjusted = [r for r in records if r["method"] != "B0"]
    assert all(r["audit"]["failed"] for r in adjusted)
    if failure == "mutation":
        assert all("mutated input" in r["error"]["message"] for r in records)
    else:
        assert all(r["audit"]["schedule"] == "failed" and "error" not in r for r in adjusted)
    assert all(r["result"]["validation_status"] == "not_run" and not r["result"]["approval_eligible"] for r in records)


@pytest.mark.parametrize("malformed", [{"method": "B2"}, {"metrics": None}, None, ["not", "a", "result"]])
def test_malformed_results_preserved_without_breaking_summary(tmp_path, snapshot, monkeypatch, malformed):
    path = protocol_file(tmp_path, snapshot)
    monkeypatch.setattr(evaluation, "solve", lambda *args: deepcopy(malformed))
    output = tmp_path / "results"
    assert evaluation.run(path, output) == 1
    records = [json.loads(line) for line in (output / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(records) == 8 and all(r["result"] == malformed and r["audit"]["failed"] for r in records)
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["exceptions"] == summary["failures"] == 8
    assert summary["independently_validated"] == summary["objective_proven"] == 0
    assert summary["pairs"] == 2 and summary["equal_count_comparable"] == 0
    import csv
    pairs = list(csv.DictReader((output / "pairs.csv").open(encoding="utf-8-sig")))
    assert all("not_validated" in row["exclusion_reason"] and not row.get("changed_delta") for row in pairs)
    runs = list(csv.DictReader((output / "runs.csv").open(encoding="utf-8-sig")))
    assert all(not row["unassigned"] and not row["changed"] for row in runs)
    assert json.loads((output / "metadata.json").read_text(encoding="utf-8"))["completed"]
