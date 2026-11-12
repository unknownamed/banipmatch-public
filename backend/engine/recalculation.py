"""Side-effect-free comparison of a dispatcher's condition-recalculation runs.

Uses the existing Snapshot/Results contract. Does not solve, store, approve,
send, or decide that a real operator has confirmed an input. The API owns
current-version/expiry/recipient checks and persistence of the revision reason.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from math import isfinite

from backend.api.contracts import ApiError, digest, validate
from backend.api.input_preflight import check_input
from backend.api.result_integrity import verify_schedule


class RecalculationError(ValueError):
    """A pair cannot be represented as the supported condition-only revision."""


def _index(rows: list[dict], *keys: str) -> dict:
    result = {tuple(row[k] for k in keys): row for row in rows}
    if len(result) != len(rows):
        raise RecalculationError("중복 식별자가 있는 입력은 비교할 수 없습니다.")
    return result


def _unchanged_rows(before, after, *keys):
    if _index(before, *keys) != _index(after, *keys):
        raise RecalculationError("반입시간·원안 등 보호된 자료가 변경됐습니다.")


def validate_condition_revision(before: dict, after: dict, *, reason: str) -> dict:
    """Check R4 edits on the same base plan and return exact changes/evidence.

    An initially incomplete ready/availability value may be repaired. The new
    input must pass full semantic checks; no time, route or capacity is filled
    in here. New locations/routes can only support an added vehicle's start.
    Separate server input/run IDs may change; the base plan must not change.
    as_of may advance for newly received evidence, but it is then a different
    time context, not a controlled estimate of the condition edit's effect.
    """
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1000:
        raise RecalculationError("조건 보완 이유가 필요합니다(1~1000자).")
    validate("Snapshot", before)
    validate("Snapshot", after)
    mutable = {"scenario_id", "as_of", "jobs", "vehicles", "locations", "travel_times", "windows",
               "baseline_assignments", "baseline_unassigned_job_ids"}
    if {k: v for k, v in before.items() if k not in mutable} != {
            k: v for k, v in after.items() if k not in mutable}:
        raise RecalculationError("같은 계획·반입변경·정책에서 조건만 비교해야 합니다.")
    before_time = datetime.fromisoformat(before["as_of"].replace("Z", "+00:00"))
    after_time = datetime.fromisoformat(after["as_of"].replace("Z", "+00:00"))
    if after_time < before_time:
        raise RecalculationError("재계산 기준시각을 이전 입력보다 과거로 돌릴 수 없습니다.")
    _unchanged_rows(before["windows"], after["windows"], "window_id")
    _unchanged_rows(before["baseline_assignments"], after["baseline_assignments"], "job_id")
    if (len(set(after["baseline_unassigned_job_ids"])) != len(after["baseline_unassigned_job_ids"])
            or sorted(before["baseline_unassigned_job_ids"]) != sorted(after["baseline_unassigned_job_ids"])):
        raise RecalculationError("원안 미처리 작업을 변경할 수 없습니다.")

    changes = []
    added_vehicles = []
    for collection, identifier, allowed in (
            ("jobs", "job_id", {"ready_at"}),
            ("vehicles", "vehicle_id", {"available_at", "shift_end_at"})):
        old_rows, new_rows = _index(before[collection], identifier), _index(after[collection], identifier)
        if set(old_rows) - set(new_rows) or (collection == "jobs" and old_rows.keys() != new_rows.keys()):
            raise RecalculationError("기존 작업·차량의 삭제나 작업 추가는 조건 보완이 아닙니다.")
        for key, old in old_rows.items():
            new = new_rows[key]
            edited = {k for k in old if old[k] != new[k]}
            fields = edited - {"evidence"}
            if fields - allowed or (edited and not fields):
                raise RecalculationError("허용된 준비·가용·근무 시각 외 필드가 변경됐습니다.")
            if collection == "jobs" and old["frozen"] and edited:
                raise RecalculationError("고정·출발 작업의 조건을 덮어쓸 수 없습니다.")
            for field in sorted(fields):
                changes.append({"entity": collection, "entity_id": key[0], "field": field,
                                "before": deepcopy(old[field]), "after": deepcopy(new[field]),
                                "before_evidence": deepcopy(old["evidence"]),
                                "after_evidence": deepcopy(new["evidence"])})
        if collection == "vehicles":
            for key in sorted(new_rows.keys() - old_rows.keys()):
                added_vehicles.append(deepcopy(new_rows[key]))

    old_locations = _index(before["locations"], "location_id")
    new_locations = _index(after["locations"], "location_id")
    added_starts = {v["start_location_id"] for v in added_vehicles}
    if any(new_locations.get(key) != row for key, row in old_locations.items()):
        raise RecalculationError("기존 위치 자료를 변경할 수 없습니다.")
    if any(key[0] not in added_starts for key in new_locations.keys() - old_locations.keys()):
        raise RecalculationError("추가 차량의 시작 위치 외 새 위치는 지원하지 않습니다.")
    old_routes = _index(before["travel_times"], "from_location_id", "to_location_id")
    new_routes = _index(after["travel_times"], "from_location_id", "to_location_id")
    if any(new_routes.get(key) != row for key, row in old_routes.items()):
        raise RecalculationError("기존 방향별 이동시간을 바꿔 비교 결과를 개선할 수 없습니다.")
    origins = {j["origin_id"] for j in after["jobs"] if not j["frozen"]}
    additional_routes = new_routes.keys() - old_routes.keys()
    if any(start not in added_starts or end not in origins for start, end in additional_routes):
        raise RecalculationError("새 이동경로는 추가 차량의 상차지 접근 경로만 허용합니다.")
    if not changes and not added_vehicles:
        raise RecalculationError("보완된 작업·차량 조건이 없습니다.")
    # Ensures new vehicles have capacity/equipment/time and every directed leg.
    check_input(after)
    return {"reason": reason.strip(), "changes": sorted(changes, key=lambda r: (r["entity"], r["entity_id"], r["field"])),
            "added_vehicles": added_vehicles,
            "added_locations": [deepcopy(new_locations[k]) for k in sorted(new_locations.keys() - old_locations.keys())],
            "added_travel_times": [deepcopy(new_routes[k]) for k in sorted(additional_routes)],
            "before_input_sha256": digest(before), "after_input_sha256": digest(after),
            "before_as_of": before["as_of"], "after_as_of": after["as_of"],
            "elapsed_reference_minutes": (after_time - before_time).total_seconds() / 60}


def _verified_result(snapshot: dict, envelope: dict, method: str) -> dict:
    validate("Results", envelope)
    if (envelope["input_sha256"] != digest(snapshot)
            or envelope["scenario_id"] != snapshot["scenario_id"]
            or envelope["base_plan_version"] != snapshot["base_plan_version"]):
        raise RecalculationError("계산 결과가 비교할 입력·계획 버전과 일치하지 않습니다.")
    selected = [r for r in envelope["results"] if r["method"] == method]
    if len(selected) != 1:
        raise RecalculationError("비교 방법의 계산 결과가 하나 있어야 합니다.")
    result = selected[0]
    if (result["result_origin"] != "computed" or result["validation_status"] != "passed"
            or not result["approval_eligible"] or not verify_schedule(snapshot, result)):
        raise RecalculationError("독립 일정 검사를 통과한 실계산 결과가 필요합니다.")
    return result


def _summary(result: dict) -> dict:
    return deepcopy({key: result[key] for key in (
        "method", "solution_status", "objective_proven", "objective_stages", "metrics",
        "issues", "unassigned_job_ids", "execution_metadata", "engine_version", "solver_version")})


def _settings(result: dict) -> dict | None:
    settings = deepcopy(result["execution_metadata"])
    declared = settings["solver_settings"]
    budget = declared.get("time_limit_seconds")
    if (not result["engine_version"] or settings["worker_count"] is None
            or type(declared.get("seed")) is not int
            or not isinstance(declared.get("algorithm"), str) or not declared["algorithm"].strip()
            or type(budget) not in (int, float) or not isfinite(budget) or budget <= 0
            or (result["method"] in ("B2", "B3") and not result["solver_version"])):
        return None
    # These describe the outcome, not the configured comparison budget.
    for key in ("time_limit_reached", "warm_start_valid"):
        settings["solver_settings"].pop(key, None)
    return {"engine_version": result["engine_version"], "solver_version": result["solver_version"], **settings}


def _moved(old: dict, new: dict) -> bool:
    """차량이 바뀌었거나 출발이 허용 폭(5분)을 넘게 움직인 작업. 앞에 다른 작업이 끼어 순서 번호만 밀린 것,
    기준 시각이 몇 분 지난 것만으로는 바뀐 작업으로 세지 않는다."""
    if old["vehicle_id"] != new["vehicle_id"]:
        return True
    shift = abs(datetime.fromisoformat(new["pickup_departure_at"].replace("Z", "+00:00"))
                - datetime.fromisoformat(old["pickup_departure_at"].replace("Z", "+00:00")))
    return shift.total_seconds() > 5 * 60


def compare_recalculation(before: dict, before_results: dict | None, after: dict,
                          after_results: dict, *, method: str, reason: str) -> dict:
    """Return R4 before/after changes without a live approval or send decision.

    Both Results envelopes bind their input hashes and run IDs. A missing old
    result is accepted only when old input preflight actually fails; that case
    has no invented zero baseline, delta or 'efficiency improvement'.
    """
    if method not in ("B1", "B2", "B3"):
        raise RecalculationError("같은 조정 방법 B1/B2/B3의 전후 결과가 필요합니다.")
    revision = validate_condition_revision(before, after, reason=reason)
    current = _verified_result(after, after_results, method)
    before_error = None
    try:
        check_input(before)
    except ApiError as error:
        before_error = {"code": error.code, "message": error.message, "details": deepcopy(error.details)}
    if before_error is not None:
        if before_results is not None:
            raise RecalculationError("입력 검사에서 차단된 원안에 성공 결과를 연결할 수 없습니다.")
        return {"comparison_version": "condition-comparison-0.1", "revision": revision,
                "plan_id": before["plan_id"], "base_plan_version": before["base_plan_version"],
                "data_mode": after["data_mode"], "before": {"status": "input_blocked", "error": before_error},
                "after": {"status": "computed", "run_id": after_results["run_id"], **_summary(current)},
                "job_transitions": None, "metric_deltas": None, "efficiency_delta": None,
                "comparison_limits": ["이전 입력이 부족해 계산되지 않았습니다. 미처리 0건이나 개선율로 비교하지 않습니다."],
                "delivery_authorized": False, "external_actions_performed": False}
    if before_results is None:
        raise RecalculationError("계산 가능한 이전 입력의 결과가 필요합니다.")
    previous = _verified_result(before, before_results, method)
    if before_results["run_id"] == after_results["run_id"]:
        raise RecalculationError("서로 다른 입력에 같은 실행 ID를 사용할 수 없습니다.")
    old = {r["job_id"]: r for r in previous["assignments"]}
    new = {r["job_id"]: r for r in current["assignments"]}
    old_unassigned, new_unassigned = set(previous["unassigned_job_ids"]), set(current["unassigned_job_ids"])
    frozen = {j["job_id"] for j in before["jobs"] if j["frozen"]}
    old_risks = {i["job_id"] for i in previous["issues"]} & frozen
    new_risks = {i["job_id"] for i in current["issues"]} & frozen
    old_metrics, new_metrics = previous["metrics"], current["metrics"]
    deltas = {key: new_metrics[key] - old_metrics[key] for key in (
        "unassigned_count", "feasible_movable_count", "movable_violation_count", "fixed_risk_count",
        "movable_travel_minutes")}
    deltas["changed_job_count"] = len(new_metrics["changed_job_ids"]) - len(old_metrics["changed_job_ids"])
    old_settings, new_settings = _settings(previous), _settings(current)
    same_work, same_risks = old.keys() == new.keys(), old_risks == new_risks
    same_settings = old_settings is not None and old_settings == new_settings
    same_time = revision["elapsed_reference_minutes"] == 0
    limits = []
    if not same_work:
        limits.append("처리한 작업 집합이 달라 이동·변경 감소를 같은 작업의 효율 개선으로 해석할 수 없습니다.")
    if not same_risks:
        limits.append("고정 작업의 잔여 위험이 달라 이동·변경 수치만으로 우열을 정할 수 없습니다.")
    if not same_settings:
        limits.append("계산 버전·설정·예산이 다르거나 미확인이라 조건 보완만의 효과로 해석할 수 없습니다.")
    if not same_time:
        limits.append("기준시각도 바뀌었습니다. 시간 경과와 조건 보완의 영향을 분리해 증명한 결과가 아닙니다.")
    limits.append("이 결과는 입력에 적힌 조건의 모의/계산 비교입니다. 실제 조건 확인·운송 수행·새 계획 승인이나 전달을 뜻하지 않습니다.")
    return {"comparison_version": "condition-comparison-0.1", "revision": revision,
            "plan_id": before["plan_id"], "base_plan_version": before["base_plan_version"], "data_mode": after["data_mode"],
            "before": {"status": "computed", "run_id": before_results["run_id"], **_summary(previous)},
            "after": {"status": "computed", "run_id": after_results["run_id"], **_summary(current)},
            "job_transitions": {"became_assigned": sorted(old_unassigned - new_unassigned),
                                "became_unassigned": sorted(new_unassigned - old_unassigned),
                                "remained_unassigned": sorted(old_unassigned & new_unassigned),
                                "changed_assignments": sorted(j for j in old.keys() & new.keys() if _moved(old[j], new[j])),
                                "fixed_risks_added": sorted(new_risks - old_risks),
                                "fixed_risks_removed": sorted(old_risks - new_risks),
                                "fixed_risks_remaining": sorted(old_risks & new_risks)},
            "same_assigned_jobs": same_work, "same_fixed_risks": same_risks, "same_solver_settings": same_settings,
            "same_reference_time": same_time,
            "metric_deltas": deltas,
            "efficiency_delta": {key: deltas[key] for key in ("movable_travel_minutes", "changed_job_count")} if same_work and same_risks and same_settings and same_time else None,
            "comparison_limits": limits, "delivery_authorized": False, "external_actions_performed": False}
