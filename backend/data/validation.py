"""공통 스키마와 입력 관계 검사. 결과 일정의 독립 검사는 API 담당 범위다."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

CONTRACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs/development/v0.1/공통 규격/contracts.schema.json"
)
MINUTE_FIELDS = frozenset({
    "as_of", "available_at", "shift_end_at", "ready_at", "opens_at",
    "closes_at", "pickup_departure_at", "gate_arrival_at", "return_at",
    "previous_opens_at", "previous_closes_at", "input_valid_until",
    "confirmed_at", "observed_at", "received_at",
})


@dataclass(frozen=True)
class InputIssue:
    code: str
    path: str
    message: str
    source: str | None = None
    row: int | None = None


@dataclass(frozen=True)
class InputReport:
    snapshot: dict[str, Any] | None
    issues: tuple[InputIssue, ...]

    @property
    def valid(self) -> bool:
        return self.snapshot is not None and not self.issues


@lru_cache(maxsize=None)
def contract_validator(name: str) -> Draft202012Validator:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    schema = {
        "$schema": contract["$schema"], "$defs": contract["$defs"],
        "$ref": "#/$defs/" + name,
    }
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _pointer(parts: Any) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_snapshot(value: Any, *, source: str | None = None) -> InputReport:
    """유효한 입력의 독립 사본만 반환한다. 오류 메시지에는 원본 값을 넣지 않는다."""
    issues: list[InputIssue] = []

    def issue(code: str, path: str, message: str) -> None:
        issues.append(InputIssue(code, path, message, source))

    def check_finite(node: Any, path: str = "") -> None:
        if isinstance(node, float) and not math.isfinite(node):
            issue("JSON_NUMBER_INVALID", path, "NaN·Infinity는 JSON 숫자가 아닙니다.")
        elif isinstance(node, dict):
            for key, item in node.items():
                check_finite(item, path + _pointer([key]))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                check_finite(item, path + f"/{index}")

    check_finite(value)
    if issues:
        return InputReport(None, tuple(issues))
    for error in contract_validator("Snapshot").iter_errors(value):
        issue("SCHEMA_INVALID", _pointer(error.absolute_path),
              f"공통 규격의 {error.validator} 조건을 충족하지 않습니다.")
    # 구조가 깨진 입력에서 후속 검사 예외나 잘못된 의미 판정을 만들지 않는다.
    if issues:
        return InputReport(None, tuple(issues))

    snapshot = deepcopy(value)

    def check_minutes(node: Any, path: str = "") -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                child = path + _pointer([key])
                if key in MINUTE_FIELDS and item is not None:
                    parsed = _time(item)
                    fraction = item[20:-1] if len(item) > 20 and item[19] == "." else ""
                    if parsed.second or any(digit != "0" for digit in fraction):
                        issue("TIME_PRECISION", child, "v0.1 입력 시각은 분 경계여야 합니다. 임의 반올림하지 않습니다.")
                check_minutes(item, child)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                check_minutes(item, path + f"/{index}")

    check_minutes(snapshot)
    as_of = _time(snapshot["as_of"])
    if _time(snapshot["policy"]["input_valid_until"]) < as_of:
        issue("INPUT_EXPIRED_AT_SNAPSHOT", "/policy/input_valid_until",
              "입력 기준시각이 입력 유효기간 이후입니다.")
    for group, key in (("locations", "location_id"), ("vehicles", "vehicle_id"),
                       ("jobs", "job_id"), ("windows", "window_id")):
        seen: set[str] = set()
        for index, item in enumerate(snapshot[group]):
            if item[key] in seen:
                issue("DUPLICATE_ID", f"/{group}/{index}/{key}", "ID가 중복됩니다.")
            seen.add(item[key])

    locations = {x["location_id"]: x for x in snapshot["locations"]}
    vehicles = {x["vehicle_id"]: x for x in snapshot["vehicles"]}
    jobs = {x["job_id"]: x for x in snapshot["jobs"]}
    windows = {x["window_id"]: x for x in snapshot["windows"]}

    def location_ref(identifier: str, path: str, *, terminal: bool = False) -> None:
        if identifier not in locations:
            issue("UNKNOWN_LOCATION", path, "같은 입력의 위치 목록에 없는 참조입니다.")
        elif terminal and locations[identifier]["kind"] != "terminal":
            issue("TERMINAL_KIND", path, "터미널 종류의 위치를 참조해야 합니다.")

    for index, vehicle in enumerate(snapshot["vehicles"]):
        path = f"/vehicles/{index}"
        location_ref(vehicle["start_location_id"], path + "/start_location_id")
        if vehicle["available_at"] is None:
            issue("INPUT_MISSING", path + "/available_at", "차량 가용시각이 미확인입니다.")
        elif _time(vehicle["available_at"]) > _time(vehicle["shift_end_at"]):
            issue("AVAILABILITY_ORDER", path + "/available_at", "가용시각이 근무 종료보다 늦습니다.")

    window_pairs: set[tuple[str, str]] = set()

    def confirmation(item: dict, path: str) -> None:
        if item["verification"] != "confirmed":
            issue("WINDOW_UNCONFIRMED", path + "/verification", "반입시간 변경 또는 시간창이 미확인입니다.")
        elif not item["confirmed_by"] or not item["confirmed_by"].strip() or item["confirmed_at"] is None:
            issue("CONFIRMATION_MISSING", path, "확인자와 확인시각이 필요합니다.")
        elif _time(item["confirmed_at"]) > as_of:
            issue("CONFIRMATION_AFTER_SNAPSHOT", path + "/confirmed_at",
                  "입력 기준시각 이후에 확인된 정보를 사용할 수 없습니다.")

    for index, window in enumerate(snapshot["windows"]):
        path = f"/windows/{index}"
        location_ref(window["terminal_id"], path + "/terminal_id", terminal=True)
        pair = (window["voyage_id"], window["terminal_id"])
        if pair in window_pairs:
            issue("DUPLICATE_WINDOW", path, "동일 항차·터미널의 현재 시간창이 중복됩니다.")
        window_pairs.add(pair)
        if _time(window["opens_at"]) > _time(window["closes_at"]):
            issue("WINDOW_ORDER", path, "반입 시작이 마감보다 늦습니다.")
        confirmation(window, path)

    change = snapshot["change"]
    confirmation(change, "/change")
    target = windows.get(change["new_window_id"])
    if target is None or (target["voyage_id"], target["terminal_id"]) != (change["voyage_id"], change["terminal_id"]):
        issue("CHANGE_TARGET", "/change/new_window_id", "변경 대상과 신규 시간창의 항차·터미널이 일치해야 합니다.")
    if _time(change["previous_opens_at"]) > _time(change["previous_closes_at"]):
        issue("WINDOW_ORDER", "/change", "이전 반입 시작이 마감보다 늦습니다.")

    assignments: dict[str, dict] = {}
    sequences: set[tuple[str, int]] = set()
    for index, assignment in enumerate(snapshot["baseline_assignments"]):
        path = f"/baseline_assignments/{index}"
        if assignment["job_id"] not in jobs:
            issue("UNKNOWN_JOB", path + "/job_id", "작업 목록에 없는 참조입니다.")
        if assignment["vehicle_id"] not in vehicles:
            issue("UNKNOWN_VEHICLE", path + "/vehicle_id", "차량 목록에 없는 참조입니다.")
        pair = (assignment["vehicle_id"], assignment["sequence"])
        if pair in sequences:
            issue("DUPLICATE_SEQUENCE", path + "/sequence", "차량 내 원안 순서가 중복됩니다.")
        sequences.add(pair)
        assignments[assignment["job_id"]] = assignment
    coverage = Counter(a["job_id"] for a in snapshot["baseline_assignments"])
    coverage.update(snapshot["baseline_unassigned_job_ids"])
    if set(coverage) != set(jobs) or any(count != 1 for count in coverage.values()):
        issue("BASELINE_COVERAGE", "/baseline_assignments", "원안 배정·미처리 목록은 모든 작업을 중복 없이 나눠야 합니다.")

    routes: set[tuple[str, str]] = set()
    for index, travel in enumerate(snapshot["travel_times"]):
        path = f"/travel_times/{index}"
        for key in ("from_location_id", "to_location_id"):
            location_ref(travel[key], path + "/" + key)
        pair = (travel["from_location_id"], travel["to_location_id"])
        if pair in routes:
            issue("DUPLICATE_ROUTE", path, "같은 방향의 이동시간이 중복됩니다.")
        routes.add(pair)

    # The confirmed vehicle start follows the final departed assignment, not
    # every earlier return location. Keep the original sequence authoritative.
    last_departed: dict[str, dict] = {}
    for job in snapshot["jobs"]:
        baseline = assignments.get(job["job_id"])
        if job["state"] == "departed" and job["frozen"] and baseline is not None:
            previous = last_departed.get(baseline["vehicle_id"])
            if previous is None or baseline["sequence"] > previous["sequence"]:
                last_departed[baseline["vehicle_id"]] = baseline
    travel_minutes = {
        (row["from_location_id"], row["to_location_id"]): row["minutes"]
        for row in snapshot["travel_times"]
    }

    for index, job in enumerate(snapshot["jobs"]):
        path = f"/jobs/{index}"
        for key in ("origin_id", "terminal_id", "return_location_id"):
            location_ref(job[key], path + "/" + key, terminal=key == "terminal_id")
        if (job["voyage_id"], job["terminal_id"]) not in window_pairs:
            issue("UNKNOWN_WINDOW", path + "/voyage_id", "작업의 항차·터미널에 해당하는 시간창이 없습니다.")
        for key in ("ready_at", "gross_weight_kg", "service_minutes"):
            if job[key] is None:
                issue("INPUT_MISSING", path + "/" + key, "계산에 필요한 값이 미확인입니다.")
        if job["state"] == "departed" and not job["frozen"]:
            issue("DEPARTED_MUST_FREEZE", path + "/frozen", "출발 작업은 고정해야 합니다.")
        if job["frozen"]:
            if not job["freeze_reason"] or not job["freeze_reason"].strip():
                issue("FREEZE_REASON_MISSING", path + "/freeze_reason", "고정 이유가 필요합니다.")
            baseline = assignments.get(job["job_id"])
            if baseline is None:
                issue("FROZEN_UNASSIGNED", path, "고정 작업의 원안 배정이 필요합니다.")
            elif baseline["return_at"] is None or baseline["gate_arrival_at"] is None:
                issue("INPUT_MISSING", path, "고정 작업의 도착·복귀 시각이 미확인입니다.")
            elif job["state"] == "departed" and baseline["vehicle_id"] in vehicles:
                vehicle = vehicles[baseline["vehicle_id"]]
                if vehicle["available_at"] is not None:
                    available = _time(vehicle["available_at"])
                    returned = _time(baseline["return_at"])
                    if available < returned:
                        issue("FIXED_AVAILABILITY_CONFLICT", path, "차량 가용시각이 출발 작업의 복귀시각보다 빠릅니다.")
                    elif last_departed[baseline["vehicle_id"]]["job_id"] == job["job_id"]:
                        origin, destination = job["return_location_id"], vehicle["start_location_id"]
                        if origin != destination:
                            if returned > _time(snapshot["as_of"]):
                                issue("FIXED_AVAILABILITY_CONFLICT", path, "진행 작업의 복귀 위치와 차량 가용 시작 위치가 다릅니다.")
                            else:
                                reposition = travel_minutes.get((origin, destination))
                                if reposition is None:
                                    issue("TRAVEL_TIME_MISSING", path, f"마지막 복귀 후 가용 위치까지 이동경로 {origin} → {destination}가 없습니다.")
                                elif (available - returned).total_seconds() / 60 < reposition:
                                    issue("FIXED_AVAILABILITY_CONFLICT", path, "마지막 복귀 후 가용 시작 위치까지 이동할 시간이 부족합니다.")
        required_routes = {(job["origin_id"], job["terminal_id"]),
                           (job["terminal_id"], job["return_location_id"])}
        if not job["frozen"]:
            # 모든 후보 접근 경로를 요구하는 보수적 검사다. 배정 가능성을 계산하지 않는다.
            starts = {v["start_location_id"] for v in vehicles.values()}
            starts.update(j["return_location_id"] for j in jobs.values())
            required_routes.update((start, job["origin_id"]) for start in starts)
        for start, end in sorted(required_routes - routes):
            issue("TRAVEL_TIME_MISSING", path, f"필요 이동경로 {start} → {end}가 없습니다. 0분으로 보완하지 않습니다.")

    return InputReport(snapshot if not issues else None, tuple(issues))
