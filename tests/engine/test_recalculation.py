from copy import deepcopy

import pytest

from backend.api.contracts import ApiError, digest
from backend.api.result_integrity import verify_schedule
from backend.engine import solve
from backend.engine.recalculation import (
    RecalculationError, compare_recalculation, validate_condition_revision,
)


def run(snapshot, run_id, method="B1", seconds=10):
    result = solve(snapshot, method, {"seed": 42, "time_limit_seconds": seconds})
    assert verify_schedule(snapshot, result)
    result.update(validation_status="passed", approval_eligible=True)
    return {"run_id": run_id, "scenario_id": snapshot["scenario_id"],
            "base_plan_version": snapshot["base_plan_version"],
            "input_sha256": digest(snapshot), "results": [result]}


def revised(snapshot):
    after = deepcopy(snapshot)
    after["jobs"][3]["ready_at"] = "2026-11-07T00:00:00Z"
    after["jobs"][3]["evidence"]["source_ref"] = "fixture:readiness-what-if"
    return after


def compare(before, after):
    return compare_recalculation(before, run(before, "before"), after, run(after, "after"),
                                 method="B1", reason="모의 준비시각 보완 시험")


def extra_vehicle(after, new_start=False):
    vehicle = deepcopy(after["vehicles"][1])
    vehicle["vehicle_id"] = "T3"
    vehicle["evidence"]["source_ref"] = "fixture:additional-vehicle"
    if new_start:
        vehicle["start_location_id"] = "X"
        location = deepcopy(after["locations"][0])
        location["location_id"] = "X"
        after["locations"].append(location)
        route = deepcopy(after["travel_times"][0])
        route["from_location_id"] = "X"
        route["minutes"] = 12
        after["travel_times"].append(route)
    after["vehicles"].append(vehicle)


def test_readiness_alone_does_not_promise_resolution(snapshot):
    output = compare(snapshot, revised(snapshot))
    assert output["job_transitions"]["remained_unassigned"] == ["J3"]
    assert output["job_transitions"]["became_assigned"] == []
    change = output["revision"]["changes"][0]
    assert (change["field"], change["entity_id"]) == ("ready_at", "J3")
    assert change["after_evidence"]["kind"] == "simulated"
    assert not output["delivery_authorized"] and not output["external_actions_performed"]


@pytest.mark.parametrize("new_start", [False, True])
def test_added_vehicle_can_resolve_work_but_not_prove_like_for_like_efficiency(snapshot, new_start):
    after = revised(snapshot)
    extra_vehicle(after, new_start)
    output = compare(snapshot, after)
    assert output["job_transitions"]["became_assigned"] == ["J3"]
    assert output["metric_deltas"]["unassigned_count"] == -1
    assert not output["same_assigned_jobs"]
    assert output["efficiency_delta"] is None
    assert output["revision"]["added_vehicles"][0]["vehicle_id"] == "T3"
    expected_routes = after["travel_times"][-1:] if new_start else []
    assert output["revision"]["added_travel_times"] == expected_routes


def test_later_readiness_exposes_new_unassigned_job(snapshot):
    after = deepcopy(snapshot)
    after["jobs"][2]["ready_at"] = "2026-11-07T06:00:00Z"
    output = compare(snapshot, after)
    assert output["job_transitions"]["became_unassigned"] == ["J2"]
    assert output["job_transitions"]["remained_unassigned"] == ["J3"]
    assert output["efficiency_delta"] is None


@pytest.mark.parametrize("field,value", [("ready_at", None), ("available_at", None)])
def test_input_repair_has_no_invented_zero_baseline(snapshot, field, value):
    before = deepcopy(snapshot)
    target = before["jobs"][3] if field == "ready_at" else before["vehicles"][1]
    target[field] = value
    after_result = run(snapshot, "after")
    output = compare_recalculation(before, None, snapshot, after_result, method="B1", reason="누락 자료 보완")
    assert output["before"]["status"] == "input_blocked"
    assert output["before"]["error"]["code"] == "INPUT_INCOMPLETE"
    assert output["metric_deltas"] is None and output["job_transitions"] is None
    with pytest.raises(RecalculationError):
        compare_recalculation(before, after_result, snapshot, after_result, method="B1", reason="시험")


def test_same_work_keeps_tradeoff_and_exact_schedule_changes(snapshot):
    after = deepcopy(snapshot)
    after["jobs"][1]["ready_at"] = "2026-11-07T00:30:00Z"
    output = compare(snapshot, after)
    assert output["same_assigned_jobs"]
    assert output["efficiency_delta"] is not None
    assert "J1" in output["job_transitions"]["changed_assignments"]
    assert output["before"]["objective_proven"] is False


def test_fixed_risk_change_is_visible_and_not_simple_efficiency_gain(snapshot):
    snapshot["jobs"][2].update(frozen=True, freeze_reason="OPERATOR_FIXED")
    snapshot["vehicles"][1]["shift_end_at"] = "2026-11-07T01:00:00Z"
    after = deepcopy(snapshot)
    after["vehicles"][1]["shift_end_at"] = "2026-11-07T09:00:00Z"
    output = compare(snapshot, after)
    assert output["job_transitions"]["fixed_risks_removed"] == ["J2"]
    assert not output["same_fixed_risks"] and output["efficiency_delta"] is None


def test_different_calculation_budget_is_not_attributed_to_condition_change(snapshot):
    after = revised(snapshot)
    output = compare_recalculation(snapshot, run(snapshot, "old"), after, run(after, "new", seconds=5),
                                   method="B1", reason="시험")
    assert not output["same_solver_settings"] and output["efficiency_delta"] is None


@pytest.mark.parametrize("kind", ["baseline", "window", "policy", "fixed", "capacity", "equipment", "job_add", "vehicle_remove", "travel", "data_mode", "as_of", "version"])
def test_unsupported_changes_cannot_hide_in_revision(snapshot, kind):
    after = revised(snapshot)
    if kind == "baseline": after["baseline_assignments"][1]["vehicle_id"] = "T2"
    elif kind == "window": after["windows"][0]["closes_at"] = "2026-11-07T08:00:00Z"
    elif kind == "policy": after["policy"]["buffer_minutes"] = 0
    elif kind == "fixed": after["jobs"][0]["ready_at"] = "2026-11-06T23:00:00Z"
    elif kind == "capacity": after["vehicles"][0]["capacity_kg"] = 40000
    elif kind == "equipment": after["vehicles"][0]["equipment_types"] = ["DRY20"]
    elif kind == "job_add":
        extra = deepcopy(after["jobs"][1]); extra["job_id"] = "J4"; after["jobs"].append(extra)
    elif kind == "vehicle_remove": after["vehicles"].pop()
    elif kind == "travel": after["travel_times"][0]["minutes"] = 0
    elif kind == "data_mode": after["data_mode"] = "mixed"
    elif kind == "as_of": after["as_of"] = "2026-11-06T23:59:00Z"
    elif kind == "version": after["base_plan_version"] = 2
    with pytest.raises(RecalculationError):
        validate_condition_revision(snapshot, after, reason="지원하지 않는 수정")


@pytest.mark.parametrize("kind", ["capacity", "available_at", "missing_route", "null_route", "reverse_route", "unrelated_route"])
def test_added_vehicle_requires_complete_directed_input(snapshot, kind):
    after = revised(snapshot); extra_vehicle(after, True)
    if kind == "capacity": after["vehicles"][-1]["capacity_kg"] = None
    elif kind == "available_at": after["vehicles"][-1]["available_at"] = None
    elif kind == "missing_route": after["travel_times"].pop()
    elif kind == "null_route": after["travel_times"][-1]["minutes"] = None
    elif kind == "reverse_route": after["travel_times"][-1].update(from_location_id="O", to_location_id="X")
    elif kind == "unrelated_route": after["travel_times"][-1].update(to_location_id="D")
    with pytest.raises((RecalculationError, ApiError)):
        validate_condition_revision(snapshot, after, reason="차량 추가 시험")


@pytest.mark.parametrize("kind", ["hash", "scenario", "version", "run", "duplicate_method", "illustrative", "unverified", "tamper_schedule", "tamper_metrics"])
def test_results_are_bound_and_independently_checked(snapshot, kind):
    after = revised(snapshot)
    old, new = run(snapshot, "old"), run(after, "new")
    if kind == "hash": new["input_sha256"] = old["input_sha256"]
    elif kind == "scenario": new["scenario_id"] = "different"
    elif kind == "version": new["base_plan_version"] = 2
    elif kind == "run": new["run_id"] = old["run_id"]
    elif kind == "duplicate_method": new["results"].append(deepcopy(new["results"][0]))
    elif kind == "illustrative": new["results"][0]["result_origin"] = "illustrative_fixture"
    elif kind == "unverified": new["results"][0]["validation_status"] = "not_run"
    elif kind == "tamper_schedule": new["results"][0]["assignments"][0]["pickup_departure_at"] = "2026-11-07T00:00:00Z"
    elif kind == "tamper_metrics": new["results"][0]["metrics"]["unassigned_count"] = 0
    with pytest.raises(ValueError):
        compare_recalculation(snapshot, old, after, new, method="B1", reason="시험")


def test_no_missing_result_or_fabricated_method(snapshot):
    after = revised(snapshot)
    with pytest.raises(RecalculationError):
        compare_recalculation(snapshot, None, after, run(after,"new"), method="B1", reason="시험")
    with pytest.raises(RecalculationError):
        compare_recalculation(snapshot, run(snapshot,"old"), after, run(after,"new"), method="B0", reason="시험")


def test_reason_required_noop_rejected_and_permutations_do_not_change_meaning(snapshot):
    after = revised(snapshot)
    with pytest.raises(RecalculationError): validate_condition_revision(snapshot, after, reason=" ")
    with pytest.raises(RecalculationError): validate_condition_revision(snapshot, snapshot, reason="변경 없음")
    for field in ["jobs", "vehicles", "windows", "locations", "baseline_assignments", "travel_times"]:
        after[field].reverse()
    assert len(validate_condition_revision(snapshot, after, reason="순서는 식별자가 아님")["changes"]) == 1


def test_return_values_are_detached_and_inputs_unchanged(snapshot):
    after = revised(snapshot)
    old_run, new_run = run(snapshot,"old"), run(after,"new")
    source = deepcopy((snapshot,after,old_run,new_run))
    first = compare_recalculation(snapshot,old_run,after,new_run,method="B1",reason="모의 시험")
    assert first == compare_recalculation(snapshot,old_run,after,new_run,method="B1",reason="모의 시험")
    first["revision"]["changes"][0]["after_evidence"]["source_ref"] = "mutated"
    first["after"]["issues"].clear()
    assert (snapshot,after,old_run,new_run) == source


def test_time_advance_allows_new_evidence_without_claiming_condition_only_gain(snapshot):
    after = revised(snapshot)
    after["as_of"] = "2026-11-07T00:01:00Z"
    after["jobs"][3]["evidence"]["received_at"] = after["as_of"]
    output = compare(snapshot, after)
    assert not output["same_reference_time"]
    assert output["revision"]["elapsed_reference_minutes"] == 1
    assert output["efficiency_delta"] is None
    assert output["same_assigned_jobs"]


@pytest.mark.parametrize("kind", ["future_evidence", "expired", "extend_expiry"])
def test_time_advance_does_not_rewrite_evidence_or_extend_input_authority(snapshot, kind):
    after = revised(snapshot)
    if kind == "future_evidence": after["jobs"][3]["evidence"]["received_at"] = "2026-11-07T00:01:00Z"
    elif kind == "expired": after["as_of"] = "2026-11-07T04:00:00Z"
    elif kind == "extend_expiry": after["policy"]["input_valid_until"] = "2026-11-07T04:00:00Z"
    with pytest.raises((RecalculationError, ApiError)):
        validate_condition_revision(snapshot, after, reason="시간 경계 시험")


@pytest.mark.parametrize("kind", ["settings", "worker", "boolean_seed"])
def test_two_missing_or_invalid_settings_are_not_evidence_of_equal_budget(snapshot, kind):
    after = revised(snapshot)
    old, new = run(snapshot,"old"), run(after,"new")
    for envelope in (old,new):
        meta = envelope["results"][0]["execution_metadata"]
        if kind == "settings": meta["solver_settings"] = {}
        elif kind == "worker": meta["worker_count"] = None
        else: meta["solver_settings"]["seed"] = True
    output = compare_recalculation(snapshot,old,after,new,method="B1",reason="시험")
    assert not output["same_solver_settings"] and output["efficiency_delta"] is None
