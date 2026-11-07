"""저장 경계의 최소 무결성 검사. 데이터 담당의 전체 의미 검증기를 대체하지 않음."""
from datetime import datetime

from backend.api.contracts import ApiError


def storage_checks(snapshot: dict) -> None:
    if snapshot["data_mode"] != "simulated":
        raise ApiError(422, "DEMO_DATA_ONLY", "1차 API는 모의 입력만 저장 가능")
    assigned = [a["job_id"] for a in snapshot["baseline_assignments"]]
    unassigned = snapshot["baseline_unassigned_job_ids"]
    jobs = {j["job_id"] for j in snapshot["jobs"]}
    if (len(set(assigned)) != len(assigned) or set(assigned) & set(unassigned)
            or set(assigned) | set(unassigned) != jobs):
        raise ApiError(422, "BASELINE_COVERAGE", "원안의 배정·미처리가 모든 작업을 중복 없이 포함해야 함")
    if any(j["frozen"] and j["job_id"] not in assigned for j in snapshot["jobs"]):
        raise ApiError(422, "FROZEN_UNASSIGNED", "고정 작업은 원안 배정에 남아야 함")

    times = [("/as_of", snapshot["as_of"]),
             ("/policy/input_valid_until", snapshot["policy"]["input_valid_until"])]
    fields = {
        "vehicles": ("available_at", "shift_end_at"), "jobs": ("ready_at",),
        "windows": ("opens_at", "closes_at"),
        "baseline_assignments": ("pickup_departure_at", "gate_arrival_at", "return_at"),
    }
    for group, keys in fields.items():
        times.extend((f"/{group}/{i}/{key}", row[key])
                     for i, row in enumerate(snapshot[group]) for key in keys)
    times.extend((f"/change/{key}", snapshot["change"][key])
                 for key in ("previous_opens_at", "previous_closes_at"))
    for path, value in times:
        if value is not None:
            parsed = datetime.fromisoformat(value)
            if parsed.second or parsed.microsecond:
                raise ApiError(422, "MINUTE_PRECISION_REQUIRED", "계산 시각은 분 경계여야 함",
                               [{"path": path, "reason": "초·소수 초를 반올림하지 않음"}])
