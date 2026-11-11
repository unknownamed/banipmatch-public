from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from backend.api.contracts import digest
from backend.api.result_integrity import verify_schedule
from backend.engine import solve
from backend.engine.metrics import calculate_metrics
from tools.dispatch_response import build_response_preview, bind_archived_approval, main


@pytest.fixture
def computed(snapshot):
    result = solve(snapshot, "B1", {"time_limit_seconds": 10, "seed": 42})
    assert verify_schedule(snapshot, result)
    result["validation_status"] = "passed"
    result["approval_eligible"] = True  # Same promotion as API jobs after independent verification.
    return result


def archived(snapshot, computed):
    # Synthetic approval ONLY for contract tests; never a user/operator approval.
    approval = {"approval_id": "A-test", "plan_id": snapshot["plan_id"], "version": 2,
                "run_id": "R-test", "method": "B1", "approved_by": "synthetic-test",
                "approved_at": snapshot["as_of"], "external_actions_performed": False}
    plan = {"plan_id": snapshot["plan_id"], "scenario_id": snapshot["scenario_id"], "version": 2,
            "approval_id": "A-test", "assignments": deepcopy(computed["assignments"]),
            "unassigned_job_ids": deepcopy(computed["unassigned_job_ids"])}
    results = {"run_id": "R-test", "scenario_id": snapshot["scenario_id"], "base_plan_version": 1,
               "input_sha256": digest(snapshot), "results": [deepcopy(computed)]}
    return results, plan, approval


def recalc_metrics(snapshot, result):
    result["metrics"] = calculate_metrics(snapshot, result["assignments"], result["unassigned_job_ids"], result["issues"], 0)


def test_real_calculation_preview_keeps_unassigned_and_fixed(snapshot, computed):
    preview = build_response_preview(snapshot, computed)
    assert not preview["delivery_authorized"] and not preview["external_actions_performed"]
    assert preview["stage"] == "review_before_approval"
    assert "J0" not in {c["job_id"] for c in preview["changes"]}
    assert preview["unassigned_job_ids"] == sorted(computed["unassigned_job_ids"])
    assert {i["job_id"] for i in preview["followups"]} >= set(computed["unassigned_job_ids"])
    removed = next(c for c in preview["changes"] if c["job_id"] == "J3")
    assert removed["kind"] == "removed_from_plan"
    assert "실제 운송 취소를 뜻하지" in removed["instruction"]
    assert any(c["job_id"] == "J3" for group in preview["vehicle_changes"] for c in group["changes"])


@pytest.mark.parametrize("key,value", [("result_origin", "illustrative_fixture"), ("validation_status", "not_run"), ("approval_eligible", False), ("method", "B0")])
def test_non_authoritative_results_are_blocked(snapshot, computed, key, value):
    computed[key] = value
    with pytest.raises(ValueError):
        build_response_preview(snapshot, computed)


def test_fixed_mutation_is_not_a_dispatch_instruction(snapshot, computed):
    computed["assignments"][0]["pickup_departure_at"] = "2026-11-07T00:00:00Z"
    with pytest.raises(ValueError):
        build_response_preview(snapshot, computed)


def test_reassignment_includes_original_and_new_vehicle(snapshot, computed):
    # Change the historical baseline, not the independently valid calculated schedule.
    row = next(a for a in snapshot["baseline_assignments"] if a["job_id"] == "J1")
    target = next(a for a in computed["assignments"] if a["job_id"] == "J1")["vehicle_id"]
    row.update(vehicle_id="T1" if target == "T2" else "T2", sequence=3)
    recalc_metrics(snapshot, computed)
    preview = build_response_preview(snapshot, computed)
    recipients = {g["vehicle_id"] for g in preview["vehicle_changes"] if any(c["job_id"] == "J1" for c in g["changes"])}
    assert recipients == {"T1", "T2"}


def test_small_time_difference_is_not_hidden_by_kpi_tolerance(snapshot, computed):
    snapshot["baseline_assignments"] = deepcopy(computed["assignments"])
    snapshot["baseline_unassigned_job_ids"] = deepcopy(computed["unassigned_job_ids"])
    row = next(a for a in snapshot["baseline_assignments"] if a["job_id"] == "J1")
    from datetime import datetime, timedelta
    row["pickup_departure_at"] = (datetime.fromisoformat(row["pickup_departure_at"].replace("Z", "+00:00")) + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recalc_metrics(snapshot, computed)
    assert "J1" not in computed["metrics"]["time_changed_job_ids"]
    assert "J1" in {c["job_id"] for c in build_response_preview(snapshot, computed)["changes"]}


def test_new_assignment_and_no_change_are_distinguished(snapshot, computed):
    snapshot["baseline_assignments"] = deepcopy(computed["assignments"])
    snapshot["baseline_unassigned_job_ids"] = deepcopy(computed["unassigned_job_ids"])
    recalc_metrics(snapshot, computed)
    assert build_response_preview(snapshot, computed)["changes"] == []
    snapshot["baseline_assignments"] = [a for a in snapshot["baseline_assignments"] if a["job_id"] != "J1"]
    snapshot["baseline_unassigned_job_ids"].append("J1")
    recalc_metrics(snapshot, computed)
    preview = build_response_preview(snapshot, computed)
    assert next(c for c in preview["changes"] if c["job_id"] == "J1")["kind"] == "newly_assigned"


def test_saved_approval_is_not_live_send_authority(snapshot, computed):
    output = bind_archived_approval(snapshot, *archived(snapshot, computed))
    assert output["stage"] == "archived_approval_review"
    assert output["approved_version"] == 2
    assert output["delivery_authorized"] is False


@pytest.mark.parametrize("kind", ["approval_id", "version", "run", "hash", "plan", "duplicate_result"])
def test_wrong_saved_approval_binding_rejected(snapshot, computed, kind):
    results, plan, approval = archived(snapshot, computed)
    if kind == "approval_id": plan["approval_id"] = "other"
    if kind == "version": approval["version"] = 3
    if kind == "run": results["run_id"] = "other"
    if kind == "hash": results["input_sha256"] = "0" * 64
    if kind == "plan": plan["assignments"] = []
    if kind == "duplicate_result": results["results"].append(deepcopy(computed))
    with pytest.raises(ValueError):
        bind_archived_approval(snapshot, results, plan, approval)


def test_preview_does_not_mutate_sources_and_is_deterministic(snapshot, computed):
    before = deepcopy((snapshot, computed))
    first = build_response_preview(snapshot, computed)
    assert (snapshot, computed) == before
    assert first == build_response_preview(snapshot, computed)
    first["vehicle_changes"][0]["changes"][0]["before"]["vehicle_id"] = "changed"
    assert (snapshot, computed) == before


def test_cli_never_overwrites_existing_output(snapshot, computed, tmp_path):
    for name, value in (("snapshot", snapshot), ("result", computed)):
        (tmp_path / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
    args = ["--snapshot", str(tmp_path / "snapshot.json"), "--result", str(tmp_path / "result.json"), "--output", str(tmp_path / "preview.json")]
    main(args)
    with pytest.raises(FileExistsError): main(args)


def test_handoff_artifact_hashes_and_preview_are_reproducible():
    root = Path(__file__).resolve().parents[1]
    bundle = root / "docs/experiments/dispatch-response-2026-11-10"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    for key in ("source", "tool"):
        assert sha256((root / manifest[key]).read_bytes()).hexdigest() == manifest[f"{key}_sha256"]
    for filename, expected in manifest["files"].items():
        assert sha256((bundle / filename).read_bytes()).hexdigest() == expected
    snapshot = json.loads((root / manifest["source"]).read_text(encoding="utf-8"))
    result = json.loads((bundle / "computed-result.json").read_text(encoding="utf-8"))
    preview = json.loads((bundle / "response-preview.json").read_text(encoding="utf-8"))
    assert build_response_preview(snapshot, result) == preview
