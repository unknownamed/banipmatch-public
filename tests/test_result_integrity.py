from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from backend.api.contracts import validate
from backend.api.result_integrity import check_result_integrity, verify_schedule
from backend.engine import solve
from backend.engine.metrics import calculate_metrics


def at(minutes):
    return (datetime(2026, 11, 7, tzinfo=timezone.utc) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_case(snapshot, *, available, fixed_rows, movable_departure=None):
    result = solve(snapshot, "B1", {"time_limit_seconds": 10, "seed": 42})
    snapshot = deepcopy(snapshot)
    prototype = deepcopy(snapshot["jobs"][1])
    snapshot["jobs"] = []
    snapshot["vehicles"] = snapshot["vehicles"][:1]
    snapshot["vehicles"][0]["available_at"] = at(available)
    snapshot["windows"][0]["closes_at"] = at(360)
    snapshot["policy"]["input_valid_until"] = at(360)
    assignments = []
    for index, (departure, service) in enumerate(fixed_rows):
        job = deepcopy(prototype)
        job.update(job_id=f"F{index}", frozen=True, freeze_reason="FIXED_RESERVATION", service_minutes=service)
        snapshot["jobs"].append(job)
        assignments.append({"job_id": job["job_id"], "vehicle_id": "T1", "sequence": index + 1,
                            "pickup_departure_at": at(departure), "gate_arrival_at": at(departure + 30),
                            "return_at": at(departure + 50 + service)})
    job = deepcopy(prototype)
    job.update(job_id="M1", service_minutes=20)
    snapshot["jobs"].append(job)
    baseline_movable = {"job_id": "M1", "vehicle_id": "T1", "sequence": len(fixed_rows) + 1,
                        "pickup_departure_at": at(movable_departure if movable_departure is not None else 250),
                        "gate_arrival_at": at((movable_departure if movable_departure is not None else 250) + 30),
                        "return_at": at((movable_departure if movable_departure is not None else 250) + 70)}
    snapshot["baseline_assignments"] = deepcopy(assignments) + [baseline_movable]
    snapshot["baseline_unassigned_job_ids"] = []
    if movable_departure is not None:
        assignments.append(deepcopy(baseline_movable))
    unassigned = [] if movable_departure is not None else ["M1"]
    issues = []
    if unassigned:
        issues.append({"job_id": "M1", "code": "SEARCH_LIMIT", "explanation": "자리 없음", "proof_level": "not_proven", "evidence_refs": []})
    cursor = available
    for index, (departure, service) in enumerate(fixed_rows):
        if departure < cursor + 10:
            issues.append({"job_id": f"F{index}", "code": "FIXED_RESIDUAL_RISK", "explanation": "고정 작업 시간 충돌", "proof_level": "constraint_check", "evidence_refs": []})
        cursor = max(cursor, departure + 50 + service)
    result.update(assignments=assignments, unassigned_job_ids=unassigned, issues=issues,
                  metrics=calculate_metrics(snapshot, assignments, unassigned, issues, 0))
    validate("Snapshot", snapshot)
    validate("MethodResult", result)
    return snapshot, result


@pytest.mark.parametrize("available,fixed_rows,movable", [
    (180, [(60, 20)], 140),  # 고정 복귀 130분이 가용 180분보다 빠름
    (180, [(60, 20)], 190),  # 모순된 고정 기록의 복귀 위치도 신규 배정의 근거로 삼지 않음
    (0, [(10, 20), (20, 0)], 80),  # 두 번째 고정 복귀 70분, 첫 고정은 80분에 복귀
])
def test_conflicting_fixed_record_never_enables_later_movable(snapshot, available, fixed_rows, movable):
    snapshot, result = build_case(snapshot, available=available, fixed_rows=fixed_rows, movable_departure=movable)
    with pytest.raises(ValueError):
        check_result_integrity(snapshot, result)
    with pytest.raises(ValueError):
        verify_schedule(snapshot, result)


@pytest.mark.parametrize("available,fixed_rows", [(180, [(60, 20)]), (0, [(10, 20), (20, 0)])])
def test_fixed_only_risk_is_retained(snapshot, available, fixed_rows):
    snapshot, result = build_case(snapshot, available=available, fixed_rows=fixed_rows)
    check_result_integrity(snapshot, result)
    assert verify_schedule(snapshot, result)


def test_safe_movable_after_normal_fixed_record_is_accepted(snapshot):
    snapshot, result = build_case(snapshot, available=0, fixed_rows=[(60, 20)], movable_departure=140)
    check_result_integrity(snapshot, result)
    assert verify_schedule(snapshot, result)
