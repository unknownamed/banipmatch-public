"""B0 baseline diagnostics and B1 deterministic deadline-ordered insertion."""
from __future__ import annotations

import copy
from time import monotonic

from .context import Context, EngineInputError, issue, minute, stamp
from .metrics import MissingTravelTimeError, calculate_metrics

ENGINE_VERSION = "0.2.4-b0-b3"


def _job_issues(c: Context, a: dict) -> list[dict]:
    jid = a["job_id"]
    j, v, w = c.jobs[jid], c.vehicles[a["vehicle_id"]], c.window(jid)
    found = c.missing_job(jid)

    def add(code, detail, proof="constraint_check"):
        if j["frozen"] and code != "INPUT_MISSING":
            detail, code = f"{code}: {detail}", "FIXED_RESIDUAL_RISK"
        found.append(issue(jid, code, detail, proof, c.refs(jid)))

    departure = minute(a["pickup_departure_at"])
    if j["ready_at"] is not None and departure < minute(j["ready_at"]):
        add("READY_TOO_LATE", f"출발 {a['pickup_departure_at']} < 준비 {j['ready_at']}")
    if j["equipment_type"] not in v["equipment_types"]:
        add("INCOMPATIBLE_EQUIPMENT", f"{v['vehicle_id']} 장비 {v['equipment_types']}에 {j['equipment_type']} 없음")
    if j["gross_weight_kg"] is not None and j["gross_weight_kg"] > v["capacity_kg"]:
        add("CAPACITY_EXCEEDED", f"중량 {j['gross_weight_kg']}kg > 허용 {v['capacity_kg']}kg")
    loaded = c.travel.get((j["origin_id"], j["terminal_id"]))
    returning = c.travel.get((j["terminal_id"], j["return_location_id"]))
    for start, end, value in ((j["origin_id"], j["terminal_id"], loaded),
                              (j["terminal_id"], j["return_location_id"], returning)):
        if value is None:
            add("INPUT_MISSING", f"이동시간 미확정: {start} → {end}", "input_validation")
    if a["gate_arrival_at"] is None:
        add("INPUT_MISSING", "원안 gate_arrival_at 미확정", "input_validation")
    else:
        arrival = minute(a["gate_arrival_at"])
        if loaded is not None and arrival != departure + loaded:
            add("MODEL_INVALID", f"기록 도착 {a['gate_arrival_at']} != 출발+적재이동 {stamp(departure + loaded)}")
        if arrival < minute(w["opens_at"]):
            add("EARLY_ARRIVAL", f"도착 {a['gate_arrival_at']} < 반입 시작 {w['opens_at']}")
        if arrival + c.buffer > minute(w["closes_at"]):
            add("CUTOFF_EXCEEDED", f"도착+여유 {stamp(arrival + c.buffer)} > 마감 {w['closes_at']}")
        if returning is not None and j["service_minutes"] is not None and a["return_at"] is not None:
            expected = arrival + c.buffer + j["service_minutes"] + returning
            if minute(a["return_at"]) != expected:
                add("MODEL_INVALID", f"기록 복귀 {a['return_at']} != 도착+여유+처리+복귀이동 {stamp(expected)}")
    if a["return_at"] is None:
        add("INPUT_MISSING", "원안 return_at 미확정", "input_validation")
    elif minute(a["return_at"]) > minute(v["shift_end_at"]):
        add("SHIFT_EXCEEDED", f"복귀 {a['return_at']} > 근무 종료 {v['shift_end_at']}")
    return found


def _vehicle_state(c: Context, vid: str) -> tuple[int | None, str, list[str]]:
    v = c.vehicles[vid]
    reasons = []
    if v["available_at"] is None:
        reasons.append("차량 available_at 미확정")
        available = None
    else:
        available = max(c.now, minute(v["available_at"]))
    baseline_route = sorted((a for a in c.base.values() if a["vehicle_id"] == vid), key=lambda a: a["sequence"])
    future_seen = False
    previous_departed = None
    for a in baseline_route:
        j = c.jobs[a["job_id"]]
        # Check the complete baseline: filtering to frozen jobs first would hide
        # a planned movable job incorrectly placed before a departed job.
        if j["state"] != "departed":
            future_seen = True
        if not j["frozen"]:
            continue
        if a["return_at"] is None or a["gate_arrival_at"] is None:
            reasons.append(f"고정 작업 {j['job_id']}의 도착/복귀 미확정")
        elif minute(a["return_at"]) < minute(a["gate_arrival_at"]) or minute(a["gate_arrival_at"]) < minute(a["pickup_departure_at"]):
            reasons.append(f"고정 작업 {j['job_id']}의 시간 순서 모순")
        if any(x["code"] == "INPUT_MISSING" or "MODEL_INVALID:" in x["explanation"] for x in _job_issues(c, a)):
            reasons.append(f"고정 작업 {j['job_id']}의 시간·입력 일관성 미확인")
        if j["state"] == "departed":
            if future_seen or minute(a["pickup_departure_at"]) > c.now:
                reasons.append(f"출발 작업 {j['job_id']}의 시각/순서 모순")
            if previous_departed is not None:
                previous_job = c.jobs[previous_departed["job_id"]]
                approach = c.travel.get((previous_job["return_location_id"], j["origin_id"]))
                if previous_departed["return_at"] is None or approach is None:
                    reasons.append(f"출발 작업 {previous_job['job_id']} → {j['job_id']}의 복귀/접근 시간 미확정")
                elif minute(previous_departed["return_at"]) + approach > minute(a["pickup_departure_at"]):
                    reasons.append(f"출발 작업 {previous_job['job_id']} → {j['job_id']}의 작업 시간 충돌")
            previous_departed = a
            if a["return_at"] is not None and available is not None:
                if minute(v["available_at"]) < minute(a["return_at"]):
                    reasons.append(f"차량 가용 {v['available_at']} < 출발 작업 {j['job_id']} 복귀 {a['return_at']}")
        else:
            future_seen = True
            if minute(a["pickup_departure_at"]) < c.now:
                reasons.append(f"미출발 고정 작업 {j['job_id']}의 출발시각이 과거")
    # The declared start state follows the entire departed prefix. A different
    # location after a past return needs enough recorded time to reach it; a
    # later as_of must not silently repair an impossible available_at.
    if previous_departed is not None and previous_departed["return_at"] is not None and available is not None:
        last_job = c.jobs[previous_departed["job_id"]]
        returned = minute(previous_departed["return_at"])
        origin, destination = last_job["return_location_id"], v["start_location_id"]
        if origin != destination:
            if returned > c.now:
                reasons.append(f"진행 작업 {last_job['job_id']} 복귀 위치와 가용 시작 위치 불일치")
            else:
                reposition = c.travel.get((origin, destination))
                if reposition is None:
                    reasons.append(f"마지막 출발 작업 복귀 후 가용 위치까지 이동시간 미확정: {origin} → {destination}")
                elif minute(v["available_at"]) < returned + reposition:
                    reasons.append(f"차량 가용 {v['available_at']} < 마지막 복귀+시작 위치 이동 {stamp(returned + reposition)} ({origin} → {destination})")
    return (None if reasons else available), v["start_location_id"], reasons


def _diagnose(c: Context, assignments: list[dict]) -> list[dict]:
    found = []
    for a in assignments:
        found.extend(_job_issues(c, a))
    for vid in sorted(c.vehicles):
        cursor, location, reasons = _vehicle_state(c, vid)
        route = sorted((a for a in assignments if a["vehicle_id"] == vid), key=lambda a: a["sequence"])
        for a in route:
            jid, j = a["job_id"], c.jobs[a["job_id"]]
            if j["state"] == "departed":
                continue  # vehicle state already describes availability after this prefix
            code = "FIXED_RESIDUAL_RISK" if j["frozen"] else "VEHICLE_UNAVAILABLE"
            if reasons:
                found.append(issue(jid, "INPUT_MISSING", f"차량 {vid}: {'; '.join(reasons)}", refs=c.refs(jid)))
            approach = c.travel.get((location, j["origin_id"]))
            if approach is None:
                found.append(issue(jid, "INPUT_MISSING", f"접근 이동시간 미확정: {location} → {j['origin_id']}", refs=c.refs(jid)))
            elif cursor is not None and minute(a["pickup_departure_at"]) < cursor + approach:
                found.append(issue(jid, code, f"출발 {a['pickup_departure_at']} < 이전 복귀/가용+접근 {stamp(cursor + approach)}", "constraint_check", c.refs(jid)))
            if a["return_at"] is None:
                cursor = None
                reasons = [f"앞 작업 {jid}의 복귀 미확정"]
            else:
                cursor = max(cursor or minute(a["return_at"]), minute(a["return_at"]))
            location = j["return_location_id"]
    return found


def _sequences(c: Context, route: list[str]) -> dict[str, int] | None:
    """Keep frozen integer sequence values verbatim; no fractional insertion IDs."""
    result, cursor = {}, 0
    for jid in route:
        if c.jobs[jid]["frozen"]:
            value = c.base[jid]["sequence"]
            if value <= cursor:
                return None
            cursor = value
        else:
            cursor += 1
        result[jid] = cursor
    return result


def _schedule(c: Context, vid: str, route: list[str], missing_paths: set[str] | None = None) -> list[dict] | None:
    numbers = _sequences(c, route)
    if numbers is None:
        return None
    v = c.vehicles[vid]
    # Reject statically incompatible movable work before collecting any route
    # gaps. Such paths cannot affect whether this vehicle can serve the job.
    # Frozen assignments are retained and diagnosed, including existing risks.
    for jid in route:
        j = c.jobs[jid]
        if not j["frozen"] and (c.missing_job(jid)
                                or j["equipment_type"] not in v["equipment_types"]
                                or j["gross_weight_kg"] > v["capacity_kg"]):
            return None
    cursor, location, reasons = _vehicle_state(c, vid)
    if reasons or cursor is None:
        return None
    result = []
    movable_seen = False
    for jid in route:
        j = c.jobs[jid]
        if j["frozen"] and j["state"] == "departed":
            if movable_seen:
                return None
            result.append(copy.deepcopy(c.base[jid]))
            continue
        approach = c.travel.get((location, j["origin_id"]))
        if approach is None:
            if missing_paths is not None:
                missing_paths.add(f"{location} → {j['origin_id']}")
            return None
        if j["frozen"]:
            a = c.base[jid]
            if a["return_at"] is None or cursor + approach > minute(a["pickup_departure_at"]):
                return None
            result.append(copy.deepcopy(a))
            cursor = minute(a["return_at"])
        else:
            movable_seen = True
            loaded = c.travel.get((j["origin_id"], j["terminal_id"]))
            returning = c.travel.get((j["terminal_id"], j["return_location_id"]))
            if loaded is None or returning is None:
                return None
            w = c.window(jid)
            departure = max(cursor + approach, minute(j["ready_at"]), minute(w["opens_at"]) - loaded)
            arrival = departure + loaded
            back = arrival + c.buffer + j["service_minutes"] + returning
            if arrival + c.buffer > minute(w["closes_at"]) or back > minute(v["shift_end_at"]):
                return None
            result.append(dict(job_id=jid, vehicle_id=vid, sequence=numbers[jid],
                               pickup_departure_at=stamp(departure), gate_arrival_at=stamp(arrival), return_at=stamp(back)))
            cursor = back
        location = j["return_location_id"]
    return result


def _unassigned_issue(c: Context, jid: str, timed_out: bool, missing_paths: set[str]) -> list[dict]:
    j, w = c.jobs[jid], c.window(jid)
    missing = c.missing_job(jid)
    if missing:
        return missing
    loaded = c.travel.get((j["origin_id"], j["terminal_id"]))
    returning = c.travel.get((j["terminal_id"], j["return_location_id"]))
    if loaded is None or returning is None:
        return [issue(jid, "INPUT_MISSING", f"적재/복귀 이동시간 미확정: {j['origin_id']} → {j['terminal_id']} → {j['return_location_id']}", refs=c.refs(jid))]
    # A vehicle-independent lower bound; does not diagnose the cause from a heuristic miss.
    earliest = minute(j["ready_at"]) + loaded + c.buffer
    if earliest > minute(w["closes_at"]):
        return [issue(jid, "READY_TOO_LATE", f"준비 {j['ready_at']} + 터미널까지 운송 {loaded}분 + 여유 {c.buffer}분 = {stamp(earliest)} > 마감 {w['closes_at']}. 다른 작업을 모두 빼도 마감 안에 들어갈 수 없습니다.", "constraint_check", c.refs(jid))]
    compatible = [v for v in c.vehicles.values() if j["equipment_type"] in v["equipment_types"]]
    if not compatible:
        return [issue(jid, "INCOMPATIBLE_EQUIPMENT", f"{j['equipment_type']} 호환 차량이 없습니다.", "constraint_check", c.refs(jid))]
    capable = [v for v in compatible if v["capacity_kg"] >= j["gross_weight_kg"]]
    if not capable:
        return [issue(jid, "CAPACITY_EXCEEDED", f"작업 {j['gross_weight_kg']}kg을 만족하는 호환 차량이 없습니다.", "constraint_check", c.refs(jid))]
    usable = [v for v in capable if _vehicle_state(c, v["vehicle_id"])[0] is not None]
    if not usable:
        return [issue(jid, "INPUT_MISSING", "모든 호환·중량 충족 차량의 복귀/가용 상태가 미확정 또는 모순입니다. 신규 배정을 차단했습니다.", refs=c.refs(jid))]
    if missing_paths:
        return [issue(jid, "INPUT_MISSING", f"실제 삽입 후보 평가에 필요한 접근 이동시간 미확정: {', '.join(sorted(missing_paths))}", refs=c.refs(jid))]
    return [issue(jid, "SEARCH_LIMIT", "시간 예산 내 삽입 탐색이 끝나지 않았습니다." if timed_out else "현재 삽입 순서에서 실행 가능한 자리를 찾지 못했습니다. 차량 경쟁·고정 예약·시간/근무 조건·정수 순서 슬롯을 확인해야 하며, 전체 불가능을 증명한 것은 아닙니다.", "not_proven", c.refs(jid))]


def _insert(c: Context, deadline: float):
    """Shared B1 construction, also used as an in-budget optimization seed."""
    timed_out = False
    routes = {vid: [a["job_id"] for a in sorted(c.base.values(), key=lambda a: a["sequence"])
                    if a["vehicle_id"] == vid and c.jobs[a["job_id"]]["frozen"]]
              for vid in sorted(c.vehicles)}
    schedules = {vid: [copy.deepcopy(c.base[jid]) for jid in ids] for vid, ids in routes.items()}
    ordered = sorted((jid for jid, j in c.jobs.items() if not j["frozen"]),
                     key=lambda jid: (minute(c.window(jid)["closes_at"]), jid))
    unassigned = []
    missing_paths_by_job = {jid: set() for jid in ordered}
    for idx, jid in enumerate(ordered):
        best = None
        for vid, route in routes.items():
            for pos in range(len(route) + 1):
                if monotonic() >= deadline:
                    timed_out = True
                    break
                candidate_ids = route[:pos] + [jid] + route[pos:]
                candidate = _schedule(c, vid, candidate_ids, missing_paths_by_job[jid])
                if candidate is None:
                    continue
                # Fixed lexical tie-break; no future data or random advantage.
                added = next(a for a in candidate if a["job_id"] == jid)
                key = (minute(added["gate_arrival_at"]), vid, pos)
                if best is None or key < best[0]:
                    best = (key, vid, candidate_ids, candidate)
            if timed_out:
                break
        if best is not None:
            _, vid, routes[vid], schedules[vid] = best
        else:
            unassigned.append(jid)
        if timed_out:
            unassigned.extend(ordered[idx + 1:])
            break
    assignments = [a for vid in sorted(schedules) for a in schedules[vid]]
    issues = _diagnose(c, assignments)
    for jid in unassigned:
        issues.extend(_unassigned_issue(c, jid, timed_out, missing_paths_by_job[jid]))
    return assignments, unassigned, issues, timed_out


def solve(snapshot: dict, method: str = "B0", config: dict | None = None) -> dict:
    """Return one v0.1 MethodResult. External validation/approval remains separate."""
    if method not in ("B0", "B1", "B2", "B3"):
        raise ValueError(f"Unknown method: {method}")
    if method in ("B2", "B3"):
        from .optimization import solve_optimized
        # Dependency loading is setup, not one method's optimization budget.
        config = dict(seed=0, time_limit_seconds=10) if config is None else config
        return solve_optimized(snapshot, method, config, monotonic(), ENGINE_VERSION)
    started = monotonic()
    config = dict(seed=0, time_limit_seconds=10) if config is None else config
    c = Context(snapshot, config)
    timed_out = False
    if method == "B0":
        assignments = copy.deepcopy(snapshot["baseline_assignments"])
        unassigned = list(snapshot["baseline_unassigned_job_ids"])
        issues = _diagnose(c, assignments)
        for jid in unassigned:
            issues.extend(c.missing_job(jid))
        status = "BASELINE"
    else:
        assignments, unassigned, issues, timed_out = _insert(c, started + config["time_limit_seconds"])
        status = "HEURISTIC"
    if any(i["code"] in ("INPUT_MISSING", "WINDOW_UNCONFIRMED") for i in issues):
        status = "INPUT_INCOMPLETE"
    # Missing/contradictory vehicle inputs remain visible even if another vehicle
    # serves every job. A feasible partial-data plan is not a complete-input plan.
    for vid in sorted(c.vehicles):
        _, _, reasons = _vehicle_state(c, vid)
        if reasons:
            issues.append(issue(None, "INPUT_MISSING", f"차량 {vid}: {'; '.join(reasons)}"))
            for a in c.base.values():
                if a["vehicle_id"] == vid and c.jobs[a["job_id"]]["frozen"]:
                    issues.append(issue(a["job_id"], "INPUT_MISSING", f"고정 작업을 보존했으나 차량 {vid}의 가용/복귀 입력 확인이 필요합니다.", refs=c.refs(a["job_id"])))
            status = "INPUT_INCOMPLETE"
    try:
        metrics = calculate_metrics(snapshot, assignments, unassigned, issues, int((monotonic() - started) * 1000))
    except MissingTravelTimeError as exc:
        raise EngineInputError([issue(exc.job_id, "INPUT_MISSING", f"이동합계 계산에 필요한 경로 미확정: {exc.origin_id} → {exc.destination_id}. v0.1 metrics에는 null을 넣을 수 없어 수치를 만들지 않고 입력을 보류합니다.", refs=c.refs(exc.job_id))], "incomplete") from exc
    return dict(method=method, result_origin="computed", solution_status=status,
                assignments=assignments, unassigned_job_ids=sorted(unassigned), issues=issues,
                metrics=metrics, objective_proven=False, approval_eligible=False,
                engine_version=ENGINE_VERSION, solver_version=None, objective_stages=[],
                validation_status="not_run", execution_metadata=dict(
                    solver_settings=dict(seed=config["seed"], seed_used=False,
                                         time_limit_seconds=config["time_limit_seconds"],
                                         algorithm="baseline-diagnosis" if method == "B0" else "deadline-insertion",
                                         tie_break="arrival, vehicle_id, insertion_position", time_limit_reached=timed_out),
                    initial_solution_ref="snapshot.baseline_assignments", worker_count=1))
