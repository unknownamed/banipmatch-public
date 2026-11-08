"""엔진 결과의 방어적 일관성 검사. 전체 독립 검증·승인 판정은 아님."""

from datetime import datetime, timedelta
from itertools import combinations


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_result_integrity(snapshot: dict, result: dict) -> None:
    jobs = {job["job_id"]: job for job in snapshot["jobs"]}
    vehicles = {vehicle["vehicle_id"] for vehicle in snapshot["vehicles"]}
    assignments = result["assignments"]
    assigned = [row["job_id"] for row in assignments]
    unassigned = result["unassigned_job_ids"]
    if (len(assigned) != len(set(assigned)) or len(unassigned) != len(set(unassigned))
            or set(assigned) & set(unassigned) or set(assigned) | set(unassigned) != set(jobs)):
        raise ValueError("결과 배정과 미처리가 전체 작업을 분할하지 않음")
    slots = [(row["vehicle_id"], row["sequence"]) for row in assignments]
    if len(slots) != len(set(slots)) or any(vehicle not in vehicles for vehicle, _ in slots):
        raise ValueError("결과 차량 참조 또는 순서 오류")
    baseline = {row["job_id"]: row for row in snapshot["baseline_assignments"]}
    current = {row["job_id"]: row for row in assignments}
    if any(current.get(jid) != baseline.get(jid) for jid, job in jobs.items() if job["frozen"]):
        raise ValueError("고정 배정이 원안과 다름")
    if result["method"] == "B0":
        if current != baseline or set(unassigned) != set(snapshot["baseline_unassigned_job_ids"]):
            raise ValueError("B0 원안이 변경됨")
        return

    vehicle_data = {v["vehicle_id"]: v for v in snapshot["vehicles"]}
    travel = {(t["from_location_id"], t["to_location_id"]): t["minutes"] for t in snapshot["travel_times"]}
    windows = {(w["voyage_id"], w["terminal_id"]): w for w in snapshot["windows"]}
    buffer = timedelta(minutes=snapshot["policy"]["buffer_minutes"])
    for vid in vehicles:
        vehicle = vehicle_data[vid]
        cursor = max(_time(snapshot["as_of"]), _time(vehicle["available_at"])) if vehicle["available_at"] else None
        location = vehicle["start_location_id"]
        previous_movable = False
        for row in sorted((a for a in assignments if a["vehicle_id"] == vid), key=lambda a: a["sequence"]):
            job = jobs[row["job_id"]]
            if job["frozen"]:
                if job["state"] != "departed":
                    leg = (location, job["origin_id"])
                    if previous_movable and (cursor is None or leg not in travel
                            or cursor + timedelta(minutes=travel[leg]) > _time(row["pickup_departure_at"])):
                        raise ValueError("조정 작업과 후속 고정 작업 충돌")
                    cursor = _time(row["return_at"]) if row["return_at"] else None
                    location = job["return_location_id"]
                elif previous_movable:
                    raise ValueError("출발 고정 작업 앞에 조정 작업이 배치됨")
                previous_movable = False
                continue
            legs = [(location, job["origin_id"]), (job["origin_id"], job["terminal_id"]),
                    (job["terminal_id"], job["return_location_id"])]
            if (cursor is None or any(leg not in travel for leg in legs)
                    or any(job[k] is None for k in ("ready_at", "gross_weight_kg", "service_minutes"))
                    or row["gate_arrival_at"] is None or row["return_at"] is None):
                raise ValueError("조정 작업의 시간·이동 입력 누락")
            departure, arrival, returned = map(_time, (row["pickup_departure_at"], row["gate_arrival_at"], row["return_at"]))
            window = windows[(job["voyage_id"], job["terminal_id"])]
            if (job["equipment_type"] not in vehicle["equipment_types"]
                    or job["gross_weight_kg"] > vehicle["capacity_kg"]
                    or departure < max(cursor + timedelta(minutes=travel[legs[0]]), _time(job["ready_at"]))
                    or arrival != departure + timedelta(minutes=travel[legs[1]])
                    or arrival < _time(window["opens_at"]) or arrival + buffer > _time(window["closes_at"])
                    or returned != arrival + buffer + timedelta(minutes=job["service_minutes"] + travel[legs[2]])
                    or returned > _time(vehicle["shift_end_at"])):
                raise ValueError("조정 작업의 일정 제약 위반")
            cursor, location = returned, job["return_location_id"]
            previous_movable = True


def verify_schedule(snapshot: dict, result: dict) -> bool:
    """입력과 배정에서 제약·고정 위험·지표를 독립적으로 다시 확인."""
    check_result_integrity(snapshot, result)
    if result["method"] == "B0" or result["solution_status"] not in {"HEURISTIC", "FEASIBLE", "OPTIMAL"}:
        return False
    jobs = {j["job_id"]: j for j in snapshot["jobs"]}
    vehicles = {v["vehicle_id"]: v for v in snapshot["vehicles"]}
    windows = {(w["voyage_id"], w["terminal_id"]): w for w in snapshot["windows"]}
    travel = {(t["from_location_id"], t["to_location_id"]): t["minutes"] for t in snapshot["travel_times"]}
    rows = result["assignments"]
    assigned = {a["job_id"]: a for a in rows}
    issues = result["issues"]
    if any(i["code"] in {"INPUT_MISSING", "MODEL_INVALID", "WINDOW_UNCONFIRMED", "OUT_OF_SCOPE"} for i in issues):
        return False
    if any(i["job_id"] in assigned and (not jobs[i["job_id"]]["frozen"] or i["code"] != "FIXED_RESIDUAL_RISK") for i in issues):
        return False
    claimed_risks = {i["job_id"] for i in issues if i["code"] == "FIXED_RESIDUAL_RISK" and i["job_id"] in assigned}
    verified_risks = set()
    if any(not any(i["job_id"] == jid for i in issues) for jid in result["unassigned_job_ids"]):
        return False
    buffer = timedelta(minutes=snapshot["policy"]["buffer_minutes"])
    for vid, vehicle in vehicles.items():
        if vehicle["available_at"] is None:
            return False
        route = sorted((a for a in rows if a["vehicle_id"] == vid), key=lambda a: a["sequence"])
        departed = [a for a in route if jobs[a["job_id"]]["state"] == "departed"]
        if route[:len(departed)] != departed:
            return False
        previous = None
        for row in departed:
            job = jobs[row["job_id"]]
            if not row["return_at"] or not row["gate_arrival_at"] or _time(row["pickup_departure_at"]) > _time(snapshot["as_of"]):
                return False
            if previous is not None:
                old_job, old_row = previous
                leg = (old_job["return_location_id"], job["origin_id"])
                if leg not in travel or _time(old_row["return_at"]) + timedelta(minutes=travel[leg]) > _time(row["pickup_departure_at"]):
                    return False
            previous = (job, row)
        if previous:
            job, row = previous
            returned = _time(row["return_at"])
            if _time(vehicle["available_at"]) < returned:
                return False
            leg = (job["return_location_id"], vehicle["start_location_id"])
            if leg[0] != leg[1]:
                if returned > _time(snapshot["as_of"]) or leg not in travel or _time(vehicle["available_at"]) < returned + timedelta(minutes=travel[leg]):
                    return False
        cursor = max(_time(snapshot["as_of"]), _time(vehicle["available_at"]))
        location = vehicle["start_location_id"]
        for row in route:
            job = jobs[row["job_id"]]
            if not job["frozen"]:
                cursor, location = _time(row["return_at"]), job["return_location_id"]
                continue
            if (job["ready_at"] is None or job["gross_weight_kg"] is None or job["service_minutes"] is None
                    or row["gate_arrival_at"] is None or row["return_at"] is None):
                return False
            legs = ((job["origin_id"], job["terminal_id"]), (job["terminal_id"], job["return_location_id"]))
            if any(leg not in travel for leg in legs):
                return False
            dep, arr, ret = map(_time, (row["pickup_departure_at"], row["gate_arrival_at"], row["return_at"]))
            window = windows[(job["voyage_id"], job["terminal_id"])]
            if (arr != dep + timedelta(minutes=travel[legs[0]])
                    or ret != arr + buffer + timedelta(minutes=job["service_minutes"] + travel[legs[1]])):
                return False
            if (dep < _time(job["ready_at"]) or job["equipment_type"] not in vehicle["equipment_types"]
                    or job["gross_weight_kg"] > vehicle["capacity_kg"] or arr < _time(window["opens_at"])
                    or arr + buffer > _time(window["closes_at"]) or ret > _time(vehicle["shift_end_at"])):
                verified_risks.add(job["job_id"])
            if job["state"] != "departed":
                leg = (location, job["origin_id"])
                if leg not in travel or dep < _time(snapshot["as_of"]):
                    return False
                if dep < cursor + timedelta(minutes=travel[leg]):
                    verified_risks.add(job["job_id"])
                cursor, location = ret, job["return_location_id"]

    if verified_risks != claimed_risks:
        return False

    # 지표는 엔진의 집계 함수를 호출하지 않고 입력·결과에서 재계산.
    base = {a["job_id"]: a for a in snapshot["baseline_assignments"]}
    retained = set(assigned) & set(base)
    vehicle_changed = {j for j in retained if assigned[j]["vehicle_id"] != base[j]["vehicle_id"]}
    tolerance = timedelta(minutes=snapshot["policy"]["time_change_tolerance_minutes"])
    time_changed = {j for j in retained if abs(_time(assigned[j]["pickup_departure_at"]) - _time(base[j]["pickup_departure_at"])) > tolerance}
    order_changed = set()
    for left, right in combinations(sorted(retained - vehicle_changed), 2):
        if assigned[left]["vehicle_id"] == assigned[right]["vehicle_id"] and (base[left]["sequence"] - base[right]["sequence"]) * (assigned[left]["sequence"] - assigned[right]["sequence"]) < 0:
            order_changed.update((left, right))
    new = set(assigned) & set(snapshot["baseline_unassigned_job_ids"])
    total = 0
    for vid, vehicle in vehicles.items():
        location = vehicle["start_location_id"]
        for row in sorted((a for a in rows if a["vehicle_id"] == vid), key=lambda a: a["sequence"]):
            job = jobs[row["job_id"]]
            if job["frozen"]:
                if job["state"] != "departed":
                    location = job["return_location_id"]
                continue
            total += sum(travel[leg] for leg in ((location, job["origin_id"]), (job["origin_id"], job["terminal_id"]), (job["terminal_id"], job["return_location_id"])))
            location = job["return_location_id"]
    expected = {"unassigned_count": len(result["unassigned_job_ids"]),
                "feasible_movable_count": sum(not jobs[j]["frozen"] for j in assigned),
                "movable_violation_count": 0, "fixed_risk_count": len(verified_risks), "movable_travel_minutes": total,
                "vehicle_changed_job_ids": sorted(vehicle_changed), "time_changed_job_ids": sorted(time_changed),
                "order_changed_job_ids": sorted(order_changed), "newly_assigned_job_ids": sorted(new),
                "changed_job_ids": sorted(vehicle_changed | time_changed | order_changed | new)}
    if not all(result["metrics"].get(key) == value for key, value in expected.items()):
        return False
    if result["objective_proven"]:
        order = ["unassigned", "travel"] if result["method"] == "B2" else ["unassigned", "changed", "travel"]
        objectives = {"unassigned": expected["unassigned_count"], "changed": len(expected["changed_job_ids"]),
                      "travel": expected["movable_travel_minutes"]}
        stages = result["objective_stages"]
        if (result["method"] not in ("B2", "B3") or result["solution_status"] != "OPTIMAL"
                or [stage["objective"] for stage in stages] != order):
            return False
        if any(stage["status"] != "OPTIMAL" or stage["value"] != objectives[stage["objective"]]
               or stage["best_bound"] is None or abs(stage["best_bound"] - stage["value"]) > 1e-6 for stage in stages):
            return False
    elif result["solution_status"] == "OPTIMAL":
        return False
    return True
