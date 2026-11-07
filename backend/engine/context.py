"""Defensive engine boundary checks, not the data team's ingestion module."""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


class EngineInputError(ValueError):
    """Reject invalid/incomplete input without inventing a MethodResult metric."""

    def __init__(self, issues: list[dict], category: str = "invalid"):
        self.issues = issues
        self.category = category
        super().__init__("; ".join(i["explanation"] for i in issues))


def minute(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()) // 60


def stamp(value: int) -> str:
    return datetime.fromtimestamp(value * 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def issue(job_id: str | None, code: str, explanation: str,
          proof: str = "input_validation", refs: list[str] | None = None) -> dict:
    return dict(job_id=job_id, code=code, explanation=explanation,
                proof_level=proof, evidence_refs=list(dict.fromkeys(refs or [])))


@lru_cache(maxsize=1)
def schema() -> dict:
    path = Path(__file__).resolve().parents[2] / "docs/development/v0.1/공통 규격/contracts.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_shape(snapshot: dict, config: dict) -> None:
    doc = schema()
    validator = Draft202012Validator(
        {"$schema": doc["$schema"], "$defs": doc["$defs"], "$ref": "#/$defs/Snapshot"},
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(snapshot), key=lambda e: str(list(e.path)))
    if errors:
        raise EngineInputError([issue(None, "MODEL_INVALID", f"{list(e.path)}: {e.message}") for e in errors])
    if (not isinstance(config, dict) or set(config) != {"seed", "time_limit_seconds"}
            or type(config["seed"]) is not int or config["seed"] < 0
            or type(config["time_limit_seconds"]) is not int
            or not 1 <= config["time_limit_seconds"] <= 120):
        raise EngineInputError([issue(None, "MODEL_INVALID", "config에는 seed(0 이상 정수), time_limit_seconds(1~120 정수)가 필요합니다.")])

    def walk(obj, path="snapshot"):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if (key.endswith("_at") or key in ("as_of", "input_valid_until")) and isinstance(value, str):
                    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                    # datetime truncates fractions beyond microseconds; inspect the source too.
                    fraction = value[20:-1] if len(value) > 20 and value[19] == "." else ""
                    if dt.second or any(digit != "0" for digit in fraction):
                        raise EngineInputError([issue(None, "MODEL_INVALID", f"{path}.{key}: v0.1 입력 시각은 UTC 분 경계여야 합니다. 임의 반올림하지 않습니다.")])
                walk(value, f"{path}.{key}")
        elif isinstance(obj, list):
            for idx, value in enumerate(obj):
                walk(value, f"{path}[{idx}]")
    walk(snapshot)


class Context:
    def __init__(self, snapshot: dict, config: dict):
        validate_shape(snapshot, config)
        self.s = snapshot
        self.now = minute(snapshot["as_of"])
        self.buffer = snapshot["policy"]["buffer_minutes"]
        errors = []
        for collection, key in (("locations", "location_id"), ("vehicles", "vehicle_id"),
                                ("jobs", "job_id"), ("windows", "window_id")):
            values = [r[key] for r in snapshot[collection]]
            if len(values) != len(set(values)):
                errors.append(issue(None, "MODEL_INVALID", f"{collection}: 중복 ID"))
        self.jobs = {r["job_id"]: r for r in snapshot["jobs"]}
        self.vehicles = {r["vehicle_id"]: r for r in snapshot["vehicles"]}
        locations = {r["location_id"] for r in snapshot["locations"]}
        self.windows = {(r["voyage_id"], r["terminal_id"]): r for r in snapshot["windows"]}
        self.travel = {(r["from_location_id"], r["to_location_id"]): r["minutes"] for r in snapshot["travel_times"]}
        self.base = {r["job_id"]: r for r in snapshot["baseline_assignments"]}
        if len(self.windows) != len(snapshot["windows"]):
            errors.append(issue(None, "MODEL_INVALID", "항차/터미널별 현재 시간창 중복"))
        if len(self.travel) != len(snapshot["travel_times"]):
            errors.append(issue(None, "MODEL_INVALID", "방향별 이동시간 중복"))
        if len(self.base) != len(snapshot["baseline_assignments"]):
            errors.append(issue(None, "MODEL_INVALID", "원안 작업 중복 배정"))
        assigned = set(self.base)
        unassigned = set(snapshot["baseline_unassigned_job_ids"])
        if assigned & unassigned or assigned | unassigned != set(self.jobs):
            errors.append(issue(None, "MODEL_INVALID", "원안 배정/미처리가 전체 작업을 정확히 분할하지 않습니다."))
        seqs = [(a["vehicle_id"], a["sequence"]) for a in self.base.values()]
        if len(seqs) != len(set(seqs)):
            errors.append(issue(None, "MODEL_INVALID", "원안의 차량별 sequence 중복"))
        for a in self.base.values():
            if a["vehicle_id"] not in self.vehicles:
                errors.append(issue(a["job_id"], "MODEL_INVALID", "원안 차량 참조 없음"))
        for j in self.jobs.values():
            jid = j["job_id"]
            if any(j[k] not in locations for k in ("origin_id", "terminal_id", "return_location_id")):
                errors.append(issue(jid, "MODEL_INVALID", "작업 위치 참조 없음"))
            if (j["voyage_id"], j["terminal_id"]) not in self.windows:
                errors.append(issue(jid, "MODEL_INVALID", "작업의 현재 시간창 참조 없음"))
            if j["state"] == "departed" and not j["frozen"]:
                errors.append(issue(jid, "MODEL_INVALID", "출발한 작업은 frozen=true여야 합니다."))
            if j["frozen"] and (jid not in assigned or not j["freeze_reason"]):
                errors.append(issue(jid, "MODEL_INVALID", "고정 작업은 원안 배정과 고정 이유가 필요합니다."))
        for v in self.vehicles.values():
            if v["start_location_id"] not in locations:
                errors.append(issue(None, "MODEL_INVALID", f"차량 {v['vehicle_id']}: 시작 위치 참조 없음"))
        for (start, end) in self.travel:
            if start not in locations or end not in locations:
                errors.append(issue(None, "MODEL_INVALID", f"이동 경로 {start} → {end}: 위치 참조 없음"))
        for w in self.windows.values():
            if w["terminal_id"] not in locations or minute(w["opens_at"]) > minute(w["closes_at"]):
                errors.append(issue(None, "MODEL_INVALID", f"시간창 {w['window_id']}: 위치 또는 시간 범위 오류"))
        change = snapshot["change"]
        chosen = next((w for w in snapshot["windows"] if w["window_id"] == change["new_window_id"]), None)
        if chosen is None or (chosen["voyage_id"], chosen["terminal_id"]) != (change["voyage_id"], change["terminal_id"]):
            errors.append(issue(None, "MODEL_INVALID", "변경 사건과 새 시간창 참조가 다릅니다."))
        if minute(change["previous_opens_at"]) > minute(change["previous_closes_at"]):
            errors.append(issue(None, "MODEL_INVALID", "이전 시간창 범위 오류"))
        if minute(snapshot["policy"]["input_valid_until"]) < self.now:
            errors.append(issue(None, "MODEL_INVALID", "입력 기준시각이 입력 유효기간 이후입니다."))
        if errors:
            raise EngineInputError(errors)
        unconfirmed = []
        for obj in [change, *snapshot["windows"]]:
            if (obj["verification"] != "confirmed" or not obj["confirmed_by"]
                    or not obj["confirmed_at"] or not obj["evidence"]["source_ref"]):
                unconfirmed.append(issue(None, "WINDOW_UNCONFIRMED", "변경 사건과 적용 시간창에 확인자·시각·출처를 갖춘 confirmed가 필요합니다."))
            elif minute(obj["confirmed_at"]) > self.now:
                unconfirmed.append(issue(None, "WINDOW_UNCONFIRMED", "입력 기준시각 이후에 확인된 변경을 사용하지 않습니다."))
        if unconfirmed:
            raise EngineInputError(unconfirmed, "incomplete")

    def window(self, jid: str) -> dict:
        j = self.jobs[jid]
        return self.windows[(j["voyage_id"], j["terminal_id"])]

    def refs(self, jid: str) -> list[str]:
        return [self.jobs[jid]["evidence"]["source_ref"], self.window(jid)["evidence"]["source_ref"]]

    def missing_job(self, jid: str) -> list[dict]:
        j = self.jobs[jid]
        missing = [k for k in ("ready_at", "gross_weight_kg", "service_minutes") if j[k] is None]
        return [issue(jid, "INPUT_MISSING", f"미확정 작업 필드: {', '.join(missing)}", refs=self.refs(jid))] if missing else []
