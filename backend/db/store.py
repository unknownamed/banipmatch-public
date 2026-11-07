from __future__ import annotations

import json
import math
import sqlite3
from uuid import uuid4

from backend.api.contracts import ApiError, canonical, digest, utc_now
from backend.db.database import Database

# 모의 인증 주체는 서버가 고정. 실제 조직·사용자 권한 모델은 후속 구현 대상.
DEMO_ACTOR = "local-demo:single-carrier:dispatcher"
SQLITE_INTEGER_MIN = -(2**63)
SQLITE_INTEGER_MAX = 2**63 - 1


def integer_binding(value: object, path: str) -> object:
    """SQL INTEGER로 전달할 값만 검사. JSON 원본·배포 스키마는 변경하지 않음."""
    if type(value) is int:
        integer = value
    elif type(value) is float and math.isfinite(value) and value.is_integer():
        # JSON Schema의 integer는 42.0 같은 표현도 허용함. 정확히 표현된 값만 변환.
        integer = int(value)
    else:
        return value  # null·boolean 및 기타 형식 검사는 기존 스키마/DB 경계 유지.
    if not SQLITE_INTEGER_MIN <= integer <= SQLITE_INTEGER_MAX:
        raise ApiError(422, "INTEGER_OUT_OF_RANGE", "정수가 저장 가능한 범위를 넘음", [
            {"path": path, "reason": "SQLite INTEGER는 signed 64-bit 범위만 저장 가능"},
        ])
    return integer


def insert(conn: sqlite3.Connection, table: str, row: dict, field_paths: dict | None = None) -> None:
    # table/column 이름은 이 모듈의 상수·고정 매핑에서만 생성. 값은 전부 바인딩.
    integer_columns = {column[1] for column in conn.execute(f"PRAGMA table_info({table})")
                       if column[2] == "INTEGER"}
    paths = field_paths or {}
    values = tuple(integer_binding(value, paths.get(key, f"/{key}")) if key in integer_columns else value
                   for key, value in row.items())
    columns = ",".join(row)
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({','.join('?' for _ in row)})", values)


def project(row: dict, scenario_id: str) -> dict:
    return {"scenario_id": scenario_id, **{
        (key + "_json" if isinstance(value, (dict, list)) else key):
        canonical(value) if isinstance(value, (dict, list)) else value
        for key, value in row.items()
    }}


def same_baseline(snapshot: dict, plan: dict) -> bool:
    return (sorted(snapshot["baseline_assignments"], key=lambda a: a["job_id"])
            == sorted(plan["assignments"], key=lambda a: a["job_id"])
            and set(snapshot["baseline_unassigned_job_ids"]) == set(plan["unassigned_job_ids"]))


class Store:
    def __init__(self, database: Database):
        self.db = database

    def idempotent(self, route: str, key: str, body: dict, operation) -> tuple[int, dict]:
        request_hash = digest(body)
        with self.db.transaction() as conn:
            previous = conn.execute(
                "SELECT * FROM idempotency_records WHERE actor_id=? AND route=? AND idempotency_key=?",
                (DEMO_ACTOR, route, key),
            ).fetchone()
            if previous:
                if previous["request_sha256"] != request_hash:
                    raise ApiError(409, "IDEMPOTENCY_CONFLICT", "같은 멱등키를 다른 요청에 사용할 수 없음")
                return previous["response_status"], json.loads(previous["response_json"])
            status, response = operation(conn)
            insert(conn, "idempotency_records", {
                "actor_id": DEMO_ACTOR, "route": route, "idempotency_key": key,
                "request_sha256": request_hash, "response_status": status,
                "response_json": canonical(response), "created_at": utc_now(),
            })
            return status, response

    @staticmethod
    def head(conn, plan_id: str):
        head = conn.execute("SELECT * FROM plan_heads WHERE plan_id=?", (plan_id,)).fetchone()
        if not head:
            raise ApiError(404, "PLAN_NOT_FOUND", "계획을 찾을 수 없음")
        return head

    @staticmethod
    def snapshot(conn, scenario_id: str) -> dict:
        row = conn.execute("SELECT snapshot_json FROM scenarios WHERE scenario_id=?", (scenario_id,)).fetchone()
        if not row:
            raise ApiError(404, "SCENARIO_NOT_FOUND", "입력을 찾을 수 없음")
        return json.loads(row["snapshot_json"])

    def register(self, snapshot: dict, key: str) -> tuple[int, dict]:
        def operation(conn):
            sid, pid, version = (snapshot[k] for k in ("scenario_id", "plan_id", "base_plan_version"))
            version = integer_binding(version, "/base_plan_version")
            if conn.execute("SELECT 1 FROM scenarios WHERE scenario_id=?", (sid,)).fetchone():
                raise ApiError(409, "SCENARIO_EXISTS", "이미 등록된 입력 ID임. 새 입력에는 새 ID 사용")
            head = conn.execute("SELECT * FROM plan_heads WHERE plan_id=?", (pid,)).fetchone()
            if head:
                if head["current_version"] != version:
                    raise ApiError(409, "PLAN_VERSION_CONFLICT", "기준 계획 버전이 현재 버전과 다름")
                plan = json.loads(conn.execute(
                    "SELECT plan_json FROM plans WHERE plan_id=? AND version=?", (pid, version)
                ).fetchone()["plan_json"])
                if not same_baseline(snapshot, plan):
                    raise ApiError(409, "BASELINE_CONFLICT", "입력 원안이 서버의 현재 계획과 다름")
            now, sha = utc_now(), digest(snapshot)
            insert(conn, "scenarios", {
                "scenario_id": sid, "plan_id": pid, "base_plan_version": version,
                "schema_version": snapshot["schema_version"], "data_mode": snapshot["data_mode"],
                "as_of": snapshot["as_of"], "input_sha256": sha,
                "snapshot_json": canonical(snapshot), "created_at": now,
            })
            for group, table in (("locations", "locations"), ("vehicles", "vehicles"),
                                 ("windows", "windows"), ("jobs", "jobs"),
                                 ("travel_times", "travel_times"),
                                 ("baseline_assignments", "baseline_assignments")):
                for index, row in enumerate(snapshot[group]):
                    insert(conn, table, project(row, sid),
                           {key: f"/{group}/{index}/{key}" for key in row})
            insert(conn, "changes", project(snapshot["change"], sid))
            for job_id in snapshot["baseline_unassigned_job_ids"]:
                insert(conn, "baseline_unassigned", {"scenario_id": sid, "job_id": job_id})
            if not head:
                plan = {"plan_id": pid, "version": version, "scenario_id": sid,
                        "assignments": snapshot["baseline_assignments"],
                        "unassigned_job_ids": snapshot["baseline_unassigned_job_ids"], "approval_id": None}
                insert(conn, "plans", {"plan_id": pid, "version": version, "scenario_id": sid,
                                       "approval_id": None, "plan_json": canonical(plan), "created_at": now})
                for row in plan["assignments"]:
                    insert(conn, "assignments", {"plan_id": pid, "version": version, "scenario_id": sid, **row})
                insert(conn, "plan_heads", {"plan_id": pid, "current_version": version,
                                            "active_scenario_id": sid, "updated_at": now})
            else:
                conn.execute("UPDATE plan_heads SET active_scenario_id=?, updated_at=? WHERE plan_id=?",
                             (sid, now, pid))
            return 201, {"scenario_id": sid, "plan_id": pid, "base_plan_version": version, "input_sha256": sha}
        return self.idempotent("POST /v1/scenarios", key, snapshot, operation)

    def get_snapshot(self, scenario_id: str) -> dict:
        with self.db.connect() as conn:
            return self.snapshot(conn, scenario_id)

    def get_plan(self, plan_id: str) -> dict:
        with self.db.connect() as conn:
            head = self.head(conn, plan_id)
            return json.loads(conn.execute("SELECT plan_json FROM plans WHERE plan_id=? AND version=?",
                                           (plan_id, head["current_version"])).fetchone()["plan_json"])

    @staticmethod
    def run(conn, run_id: str) -> dict:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            raise ApiError(404, "RUN_NOT_FOUND", "실행을 찾을 수 없음")
        return {k: row[k] for k in ("run_id", "scenario_id", "plan_id", "base_plan_version", "status",
                                    "created_at", "started_at", "finished_at")} | {
            "methods": json.loads(row["methods_json"]),
            "config": {"seed": row["seed"], "time_limit_seconds": row["time_limit_seconds"]},
            "error": json.loads(row["error_json"]) if row["error_json"] else None,
        }

    def create_run(self, request: dict, key: str, check_fixture) -> tuple[int, dict]:
        def operation(conn):
            for field in ("base_plan_version", "seed", "time_limit_seconds"):
                integer_binding(request[field], f"/{field}")
            snapshot = self.snapshot(conn, request["scenario_id"])
            head = self.head(conn, snapshot["plan_id"])
            if (head["current_version"] != request["base_plan_version"]
                    or snapshot["base_plan_version"] != request["base_plan_version"]
                    or head["active_scenario_id"] != request["scenario_id"]):
                raise ApiError(409, "PLAN_VERSION_CONFLICT", "최신 입력과 기준 계획으로 다시 실행해야 함")
            check_fixture(snapshot, request["methods"])
            run_id = "R-" + uuid4().hex
            insert(conn, "runs", {
                "run_id": run_id, "scenario_id": snapshot["scenario_id"], "plan_id": snapshot["plan_id"],
                "base_plan_version": request["base_plan_version"], "input_sha256": digest(snapshot),
                "status": "queued", "created_at": utc_now(), "started_at": None, "finished_at": None,
                "methods_json": canonical(request["methods"]), "seed": request["seed"],
                "time_limit_seconds": request["time_limit_seconds"], "error_json": None,
            })
            return 202, self.run(conn, run_id)
        return self.idempotent("POST /v1/runs", key, request, operation)

    def get_run(self, run_id: str) -> dict:
        with self.db.connect() as conn:
            return self.run(conn, run_id)

    def get_results(self, run_id: str) -> tuple[int, dict]:
        with self.db.connect() as conn:
            run = self.run(conn, run_id)
            if run["status"] in ("queued", "running"):
                return 202, run
            if run["status"] != "completed":
                raise ApiError(503, "RUN_EXECUTION_FAILED", "실행이 완료되지 않았음. 실행 상태·오류 확인 필요")
            rows = conn.execute("SELECT method, result_json FROM method_results WHERE run_id=?", (run_id,))
            indexed = {row["method"]: json.loads(row["result_json"]) for row in rows}
            sha = conn.execute("SELECT input_sha256 FROM runs WHERE run_id=?", (run_id,)).fetchone()[0]
            return 200, {"run_id": run_id, "scenario_id": run["scenario_id"],
                         "base_plan_version": run["base_plan_version"], "input_sha256": sha,
                         "results": [indexed[m] for m in run["methods"]]}

    def reject_approval(self, plan_id: str, request: dict) -> None:
        with self.db.transaction() as conn:
            head, run = self.head(conn, plan_id), self.run(conn, request["run_id"])
            if (run["plan_id"] != plan_id or request["expected_version"] != head["current_version"]
                    or run["base_plan_version"] != head["current_version"]
                    or run["scenario_id"] != head["active_scenario_id"]):
                raise ApiError(409, "PLAN_VERSION_CONFLICT", "계획 또는 입력이 변경되어 이전 결과 승인 불가")
            row = conn.execute("SELECT result_json FROM method_results WHERE run_id=? AND method=?",
                               (run["run_id"], request["method"])).fetchone()
            if row and json.loads(row[0])["result_origin"] == "illustrative_fixture":
                raise ApiError(422, "RESULT_NOT_COMPUTED", "설명용 결과는 승인할 수 없음")
            raise ApiError(503, "APPROVAL_NOT_IMPLEMENTED", "실계산·독립 검증·운영 인증·승인 기능은 미구현")
