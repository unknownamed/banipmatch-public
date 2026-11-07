"""Execute the storage draft in memory; write only the requested QA report/field TSV.

No network, real dispatch action or optimization is performed. A generated approval
round-trip uses a TEST-ONLY computed-shaped record to exercise FKs/atomic writes;
it is not evidence that a solver ran or a real plan was approved.
"""
from __future__ import annotations
import copy
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
COMMON = BASE / "공통 규격"
EXAMPLES = BASE / "예제 데이터"
QA = BASE / "검수"
SCHEMA = (COMMON / "schema.sql").read_text(encoding="utf-8")
TESTS = []

def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def fixture(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8-sig"))

def connect():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
    return conn

def insert(conn, table, row):
    columns = list(row)
    sql = f'INSERT INTO "{table}" (' + ",".join(f'"{c}"' for c in columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")"
    conn.execute(sql, [row[c] for c in columns])

def partition_guard(s):
    jobs = {j["job_id"]: j for j in s["jobs"]}
    assigned = [a["job_id"] for a in s["baseline_assignments"]]
    unassigned = s["baseline_unassigned_job_ids"]
    if len(jobs) != len(s["jobs"]):
        raise ValueError("duplicate job IDs")
    if len(set(assigned)) != len(assigned) or len(set(unassigned)) != len(unassigned):
        raise ValueError("duplicate baseline membership")
    if set(assigned) & set(unassigned) or set(assigned) | set(unassigned) != set(jobs):
        raise ValueError("baseline assigned/unassigned must partition all jobs")
    if any(jobs[j]["frozen"] for j in unassigned):
        raise ValueError("frozen baseline job cannot be unassigned")

def same_assignments(left, right):
    return sorted(left, key=lambda x: x["job_id"]) == sorted(right, key=lambda x: x["job_id"])

def add_snapshot(conn, s, *, activate=True, include_plan_assignments=True):
    """Minimal importer for tests, not the complete production semantic validator."""
    partition_guard(s)
    head = conn.execute("SELECT * FROM plan_heads WHERE plan_id=?", (s["plan_id"],)).fetchone()
    if head:
        if head["current_version"] != s["base_plan_version"]:
            raise ValueError("snapshot base version is not the current head")
        current = json.loads(conn.execute("SELECT plan_json FROM plans WHERE plan_id=? AND version=?",
                                         (s["plan_id"], head["current_version"])).fetchone()[0])
        if (not same_assignments(s["baseline_assignments"], current["assignments"])
            or sorted(s["baseline_unassigned_job_ids"]) != sorted(current["unassigned_job_ids"])):
            raise ValueError("new snapshot baseline differs from current plan")
    raw = dump(s)
    conn.execute("BEGIN")
    try:
        insert(conn, "scenarios", dict(scenario_id=s["scenario_id"], plan_id=s["plan_id"],
            base_plan_version=s["base_plan_version"], schema_version=s["schema_version"],
            data_mode=s["data_mode"], as_of=s["as_of"], input_sha256=sha(raw),
            snapshot_json=raw, created_at=s["as_of"]))
        for table, source in [("locations","locations"),("vehicles","vehicles"),("windows","windows"),
                              ("jobs","jobs"),("travel_times","travel_times")]:
            for record in s[source]:
                row = copy.deepcopy(record)
                row["scenario_id"] = s["scenario_id"]
                row["evidence_json"] = dump(row.pop("evidence"))
                if table == "vehicles":
                    row["equipment_types_json"] = dump(row.pop("equipment_types"))
                insert(conn, table, row)
        change = copy.deepcopy(s["change"])
        change["scenario_id"] = s["scenario_id"]
        change["evidence_json"] = dump(change.pop("evidence"))
        insert(conn, "changes", change)
        for a in s["baseline_assignments"]:
            insert(conn, "baseline_assignments", {"scenario_id": s["scenario_id"], **a})
        for job_id in s["baseline_unassigned_job_ids"]:
            insert(conn, "baseline_unassigned", {"scenario_id": s["scenario_id"], "job_id": job_id})
        existing = conn.execute("SELECT 1 FROM plans WHERE plan_id=? AND version=?",
                                (s["plan_id"], s["base_plan_version"])).fetchone()
        if not existing:
            plan = dict(plan_id=s["plan_id"], version=s["base_plan_version"], scenario_id=s["scenario_id"],
                        assignments=s["baseline_assignments"], unassigned_job_ids=s["baseline_unassigned_job_ids"],
                        approval_id=None)
            insert(conn, "plans", dict(plan_id=s["plan_id"], version=s["base_plan_version"],
                scenario_id=s["scenario_id"], approval_id=None, plan_json=dump(plan), created_at=s["as_of"]))
            if include_plan_assignments:
                for a in plan["assignments"]:
                    insert(conn, "assignments", dict(plan_id=s["plan_id"], version=s["base_plan_version"],
                                                      scenario_id=s["scenario_id"], **a))
        if activate:
            conn.execute("""INSERT INTO plan_heads(plan_id,current_version,active_scenario_id,updated_at)
                            VALUES (?,?,?,?) ON CONFLICT(plan_id) DO UPDATE SET
                            active_scenario_id=excluded.active_scenario_id,updated_at=excluded.updated_at""",
                         (s["plan_id"], s["base_plan_version"], s["scenario_id"], s["as_of"]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

def add_run_and_results(conn, s):
    status = fixture("03_run_status.json")
    request = fixture("02_run_request.json")
    raw_results = fixture("04_results_설명용.json")
    record = dict(status)
    record["input_sha256"] = sha(dump(s))
    record["methods_json"] = dump(record.pop("methods"))
    config = record.pop("config")
    assert config == {"time_limit_seconds":request["time_limit_seconds"], "seed":request["seed"]}
    record["time_limit_seconds"] = config["time_limit_seconds"]
    record["seed"] = config["seed"]
    error = record.pop("error")
    record["error_json"] = None if error is None else dump(error)
    insert(conn, "runs", record)
    for r in raw_results["results"]:
        add_result(conn, status["run_id"], s, r)
    conn.commit()
    return raw_results

def add_result(conn, run_id, s, result):
    insert(conn, "method_results", dict(run_id=run_id, method=result["method"],
        scenario_id=s["scenario_id"], plan_id=s["plan_id"], base_plan_version=s["base_plan_version"],
        result_origin=result["result_origin"], solution_status=result["solution_status"],
        objective_proven=result["objective_proven"], approval_eligible=result["approval_eligible"],
        result_json=dump(result)))

def fresh(*, plan_assignments=True):
    conn = connect()
    add_snapshot(conn, fixture("01_snapshot.json"), include_plan_assignments=plan_assignments)
    return conn

def test(name, fn):
    try:
        detail = fn()
        TESTS.append({"name": name, "passed": True, "detail": detail or "통과"})
    except Exception as exc:
        TESTS.append({"name": name, "passed": False, "detail": f"{type(exc).__name__}: {exc}"})

def reject(conn, fn, expected=""):
    conn.execute("SAVEPOINT bad_write")
    try:
        fn()
    except sqlite3.DatabaseError as exc:
        message = str(exc)
        conn.execute("ROLLBACK TO bad_write")
        conn.execute("RELEASE bad_write")
        if expected:
            assert expected.lower() in message.lower(), message
        return message
    else:
        conn.execute("ROLLBACK TO bad_write")
        conn.execute("RELEASE bad_write")
        raise AssertionError("invalid write unexpectedly accepted")

def reject_import(mutator, expected):
    conn = fresh()
    sample = copy.deepcopy(fixture("01_snapshot.json"))
    sample["scenario_id"] = "BAD_INPUT"
    mutator(sample)
    try:
        add_snapshot(conn, sample)
    except (ValueError, sqlite3.DatabaseError) as exc:
        assert expected.lower() in str(exc).lower(), str(exc)
        return str(exc)
    raise AssertionError("invalid snapshot unexpectedly accepted")

def main():
    s = fixture("01_snapshot.json")
    conn = fresh()
    test("schema_and_fixture_import", lambda: (
        "SQLite " + sqlite3.sqlite_version + "; initial deferred FK cycle committed"
        if conn.execute("PRAGMA foreign_key_check").fetchall() == [] else 1/0))
    report_results = add_run_and_results(conn, s)
    test("fixture_input_hash_matches_results", lambda:
         "설명용 결과의 input_sha256와 정규 JSON 해시 일치"
         if report_results["input_sha256"] == sha(dump(s)) else
         (_ for _ in ()).throw(AssertionError("fixture input hash mismatch")))
    test("snapshot_json_roundtrip", lambda:
         "권위 JSON 입력을 손실 없이 복원"
         if json.loads(conn.execute("SELECT snapshot_json FROM scenarios WHERE scenario_id='S001'").fetchone()[0]) == s
         else (_ for _ in ()).throw(AssertionError("roundtrip mismatch")))

    def import_variants():
        add_snapshot(conn, fixture("07_snapshot_입력누락.json"))
        add_snapshot(conn, fixture("08_snapshot_미확인변경.json"))
        missing = fixture("07_snapshot_입력누락.json")
        for j in missing["jobs"]:
            row = conn.execute("SELECT ready_at,gross_weight_kg,service_minutes FROM jobs WHERE scenario_id=? AND job_id=?",
                               (missing["scenario_id"],j["job_id"])).fetchone()
            assert tuple(row) == (j["ready_at"],j["gross_weight_kg"],j["service_minutes"])
        assert conn.execute("SELECT verification FROM changes WHERE scenario_id='S003'").fetchone()[0] == "unconfirmed"
        head = conn.execute("SELECT current_version,active_scenario_id FROM plan_heads WHERE plan_id='P001'").fetchone()
        assert tuple(head) == (1,"S003")
        return "같은 P001/version 1에 S001·S002·S003 공존; NULL/미확인 보존, 활성 입력 S003"
    test("input_revisions_and_incomplete_values", import_variants)

    test("unknown_job_fk_rejected", lambda: reject(conn, lambda: insert(conn, "baseline_assignments",
         dict(scenario_id="S001", **{**s["baseline_assignments"][0], "job_id":"NOT_A_JOB","sequence":9})), "FOREIGN KEY"))
    test("negative_duration_rejected", lambda: reject(conn, lambda:
         conn.execute("INSERT INTO travel_times VALUES ('S001','D','O',-1,'{}')"), "CHECK"))
    test("negative_capacity_rejected", lambda: reject(conn, lambda:
         conn.execute("INSERT INTO vehicles VALUES ('S001','BAD','D',NULL,'2026-11-07T09:00:00Z',-1,'[\"DRY40\"]','{}')"), "CHECK"))
    test("duplicate_job_assignment_rejected", lambda: reject(conn, lambda:
         insert(conn, "baseline_assignments", {"scenario_id":"S001", **s["baseline_assignments"][0]}), "UNIQUE"))
    test("zero_sequence_rejected", lambda: reject(conn, lambda:
         insert(conn, "baseline_assignments", {"scenario_id":"S001", **s["baseline_assignments"][0], "sequence":0}), "CHECK"))

    def crossed_assignment():
        db = fresh(plan_assignments=False)
        add_snapshot(db, fixture("07_snapshot_입력누락.json"))
        return reject(db, lambda: insert(db,"assignments",dict(
            plan_id="P001",version=1,scenario_id="S002",**s["baseline_assignments"][0])), "FOREIGN KEY")
    test("cross_scenario_plan_assignment_rejected", crossed_assignment)

    def bad_run():
        row = dict(conn.execute("SELECT * FROM runs WHERE run_id='R001'").fetchone())
        row.update(run_id="R_BAD", scenario_id="S002")
        return reject(conn, lambda: insert(conn,"runs",row), "FOREIGN KEY")
    test("run_snapshot_hash_mismatch_rejected", bad_run)

    def wrong_version():
        row = dict(conn.execute("SELECT * FROM runs WHERE run_id='R001'").fetchone())
        row.update(run_id="R_BAD_VERSION", base_plan_version=2)
        return reject(conn, lambda: insert(conn,"runs",row), "FOREIGN KEY")
    test("run_plan_version_mismatch_rejected", wrong_version)

    def crossed_result():
        row = dict(conn.execute("SELECT * FROM method_results WHERE method='B3'").fetchone())
        row["scenario_id"]="S002"
        row["method"]="B2"
        obj=json.loads(row["result_json"])
        obj["method"]="B2"
        row["result_json"]=dump(obj)
        return reject(conn, lambda: insert(conn,"method_results",row),"FOREIGN KEY")
    test("result_run_scenario_mismatch_rejected", crossed_result)

    test("snapshot_update_blocked", lambda: reject(conn, lambda:
         conn.execute("UPDATE scenarios SET data_mode='mixed' WHERE scenario_id='S001'"), "immutable"))
    test("normalized_input_update_blocked", lambda: reject(conn, lambda:
         conn.execute("UPDATE jobs SET ready_at=NULL WHERE scenario_id='S001' AND job_id='J1'"), "immutable"))
    test("plan_version_update_blocked", lambda: reject(conn, lambda:
         conn.execute("UPDATE plans SET created_at='2026-11-07T00:01:00Z' WHERE plan_id='P001'"), "immutable"))
    test("assignment_delete_blocked", lambda: reject(conn, lambda:
         conn.execute("DELETE FROM assignments WHERE plan_id='P001'"), "immutable"))
    test("replace_cannot_overwrite_snapshot", lambda: reject(conn, lambda:
         conn.execute("INSERT OR REPLACE INTO scenarios SELECT * FROM scenarios WHERE scenario_id='S001'"), "immutable"))
    test("run_input_identity_update_blocked", lambda: reject(conn, lambda:
         conn.execute("UPDATE runs SET seed=seed+1 WHERE run_id='R001'"), "immutable"))

    def run_status_update():
        conn.execute("UPDATE runs SET status='completed' WHERE run_id='R001'")
        conn.commit()
        return "상태 갱신 가능, 입력 identity 갱신 차단은 별도 검증"
    test("run_status_is_mutable", run_status_update)

    def illustrative_approval():
        row = dict(approval_id="A_BAD",plan_id="P001",version=2,scenario_id="S001",run_id="R001",method="B3",
                   expected_version=1,approved_by="test-only",approved_at=s["as_of"],
                   acknowledged_job_ids_json='["J3"]',external_actions_performed=0)
        return reject(conn, lambda: insert(conn,"approvals",row), "eligible computed")
    test("illustrative_result_cannot_be_approved", illustrative_approval)

    def stale_input_cas():
        changed = conn.execute("""UPDATE plan_heads SET updated_at=?
            WHERE plan_id='P001' AND current_version=1 AND active_scenario_id='S001'""",(s["as_of"],)).rowcount
        conn.commit()
        assert changed == 0
        return "버전이 1로 같아도 활성 입력 S003 != 실행 입력 S001이면 CAS 0행; API는 409"
    test("stale_input_same_version_cas_rejected", stale_input_cas)

    test("baseline_partition_gap_rejected_by_api_guard", lambda:
         reject_import(lambda x:x["baseline_assignments"].pop(), "partition"))
    test("baseline_partition_overlap_rejected_by_api_guard", lambda:
         reject_import(lambda x:x["baseline_unassigned_job_ids"].append("J3"), "partition"))

    def frozen_unassigned(snap):
        snap["baseline_assignments"]=[a for a in snap["baseline_assignments"] if a["job_id"]!="J0"]
        snap["baseline_unassigned_job_ids"]=["J0"]
    test("frozen_baseline_unassigned_rejected_by_api_guard", lambda: reject_import(frozen_unassigned,"frozen"))
    test("baseline_unassigned_overlap_db_rejected", lambda: reject(conn, lambda:
         insert(conn,"baseline_unassigned",{"scenario_id":"S001","job_id":"J3"}),"not assigned"))

    def wrong_changed_voyage(snap):
        snap["change"]["new_window_id"]="W2"
    test("change_voyage_window_fk_rejected", lambda: reject_import(wrong_changed_voyage,"FOREIGN KEY"))
    test("new_snapshot_must_match_current_plan_api_guard", lambda:
         reject_import(lambda x:x["baseline_assignments"][1].update(pickup_departure_at="2026-11-07T01:15:00Z"),"differs"))

    def duplicate_sequence():
        db=connect()
        clone=copy.deepcopy(s)
        clone["baseline_assignments"][1]["sequence"]=1
        try:
            add_snapshot(db,clone)
        except sqlite3.IntegrityError as exc:
            assert "UNIQUE" in str(exc)
            return str(exc)
        raise AssertionError("duplicate vehicle sequence accepted")
    test("duplicate_vehicle_sequence_rejected", duplicate_sequence)

    def deferred_orphan():
        db=connect()
        raw=dump(s)
        insert(db,"scenarios",dict(scenario_id=s["scenario_id"],plan_id=s["plan_id"],
            base_plan_version=1,schema_version=s["schema_version"],data_mode=s["data_mode"],as_of=s["as_of"],
            input_sha256=sha(raw),snapshot_json=raw,created_at=s["as_of"]))
        try:
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            return str(exc)
        raise AssertionError("missing initial base plan committed")
    test("deferred_initial_fk_checked_at_commit", deferred_orphan)

    def approval_storage_roundtrip():
        db=fresh()
        add_run_and_results(db,s)
        run=dict(db.execute("SELECT * FROM runs WHERE run_id='R001'").fetchone())
        run.update(run_id="R_TEST_STORAGE",methods_json='["B3"]')
        result=copy.deepcopy(report_results["results"][1])
        # This is ONLY a storage-path unit fixture, not actual optimization output.
        result["result_origin"]="computed"
        result["approval_eligible"]=True
        insert(db,"runs",run)
        add_result(db,run["run_id"],s,result)
        db.commit()
        db.execute("BEGIN IMMEDIATE")
        plan=dict(plan_id="P001",version=2,scenario_id="S001",assignments=result["assignments"],
                  unassigned_job_ids=result["unassigned_job_ids"],approval_id="A_TEST_STORAGE")
        insert(db,"plans",dict(plan_id="P001",version=2,scenario_id="S001",approval_id="A_TEST_STORAGE",
                              plan_json=dump(plan),created_at=s["as_of"]))
        for a in plan["assignments"]:
            insert(db,"assignments",dict(plan_id="P001",version=2,scenario_id="S001",**a))
        insert(db,"approvals",dict(approval_id="A_TEST_STORAGE",plan_id="P001",version=2,scenario_id="S001",
            run_id=run["run_id"],method="B3",expected_version=1,approved_by="storage-unit-test-only",
            approved_at=s["as_of"],acknowledged_job_ids_json='["J3"]',external_actions_performed=0))
        count=db.execute("""UPDATE plan_heads SET current_version=2,updated_at=?
            WHERE plan_id='P001' AND current_version=1 AND active_scenario_id='S001'""",(s["as_of"],)).rowcount
        assert count==1
        insert(db,"idempotency_records",dict(actor_id="storage-unit-test-only",
            route="POST /v1/plans/P001/approvals",idempotency_key="storage-unit-test-key",
            request_sha256=sha(dump(fixture("05_approval_request.json"))),response_status=201,
            response_json=dump({"approval_id":"A_TEST_STORAGE","version":2}),created_at=s["as_of"]))
        db.commit()
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
        repeat=reject(db,lambda: db.execute(
            "INSERT INTO idempotency_records SELECT * FROM idempotency_records"),"UNIQUE")
        next_input=copy.deepcopy(s)
        next_input.update(scenario_id="S_NEXT",base_plan_version=2,
                          baseline_assignments=plan["assignments"],
                          baseline_unassigned_job_ids=plan["unassigned_job_ids"])
        add_snapshot(db,next_input)
        assert db.execute("SELECT count(*) FROM baseline_unassigned WHERE scenario_id='S_NEXT'").fetchone()[0]==1
        assert tuple(db.execute("SELECT current_version,active_scenario_id FROM plan_heads").fetchone())==(2,"S_NEXT")
        return {"note":"테스트용 computed 형태만 사용; 실제 알고리즘 계산·승인 아님",
                "approval_version":2,"new_input_carries_unassigned":["J3"],"duplicate_idempotency_rejection":repeat}
    test("atomic_approval_storage_and_unassigned_carryover", approval_storage_roundtrip)

    def final_integrity():
        assert conn.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
        assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        return "integrity_check=ok; foreign_key_check=0"
    test("final_sqlite_integrity", final_integrity)

    fields=write_dictionary(conn)
    QA.mkdir(parents=True,exist_ok=True)
    report={
        "checked_at_utc":datetime.now(timezone.utc).isoformat(),
        "sqlite_version":sqlite3.sqlite_version,
        "schema_sha256":sha(SCHEMA),
        "contract_sha256":hashlib.sha256((COMMON/"contracts.schema.json").read_bytes()).hexdigest(),
        "fixture_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in EXAMPLES.glob("*.json")},
        "storage":"in-memory only; no production DB created",
        "passed":all(t["passed"] for t in TESTS),
        "test_count":len(TESTS),"passed_count":sum(t["passed"] for t in TESTS),
        "table_count":len(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()),
        "dictionary_field_count":fields,
        "fixture_counts":{t:conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                          for t in ["scenarios","locations","vehicles","jobs","windows","travel_times",
                                    "baseline_assignments","baseline_unassigned","plans","assignments",
                                    "runs","method_results","approvals"]},
        "tests":TESTS,
        "not_validated_by_db":[
            "전체 JSON Schema/정규화 원본 일치·완전성, 해시 계산과 RFC3339 형식 전체",
            "일정 실행 가능성·차량 공차 이동·차량 적합성·변경 최소성·실제 최적화 성과",
            "사용자 인증·운송사 범위·신선도·근거 확인·실제 외부 처리 권한",
            "plan_heads CAS SQL 선택과 rowcount 검사 및 트랜잭션 경계는 API 책임",
            "중첩 result_json/plan_json의 모든 작업 참조·집계 일치·미처리 분할합집합은 API 검증",
            "검색 projection INSERT 완전성은 API 등록/승인 트랜잭션에서 검사; JSON이 권위 원본"
        ]}
    path=QA/"DB검증.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"passed":report["passed"],"tests":len(TESTS),"passed_count":report["passed_count"],
                      "tables":report["table_count"],"fields":fields,
                      "failed":[t for t in TESTS if not t["passed"]]},ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)

DESCRIPTIONS={
"scenario_id":"불변 입력 revision ID; 같은 plan에 여러 입력을 보존",
"plan_id":"운송사 내부 배차 계획 ID; 승인 revision을 묶는 키",
"base_plan_version":"이 입력/실행이 기준으로 삼은 승인 계획 버전",
"schema_version":"JSON 계약 버전",
"data_mode":"모의·관측·혼합 구분",
"as_of":"시나리오 판단 기준 시각(UTC)",
"input_sha256":"정규 JSON 입력 SHA-256; API가 계산",
"snapshot_json":"권위 입력 JSON 전체; 변경 불가",
"created_at":"생성 시각(UTC)",
"location_id":"입력 안에서의 장소 ID",
"name":"장소 표시명",
"kind":"장소 종류",
"latitude":"위도; 미확보 NULL",
"longitude":"경도; 미확보 NULL",
"evidence_json":"출처·관측/수신 시각·모의 여부",
"vehicle_id":"입력 안에서의 차량 ID",
"start_location_id":"차량 시작 장소",
"available_at":"차량 다음 사용 가능 시각; 불명 NULL",
"shift_end_at":"근무 종료 시각",
"capacity_kg":"차량 허용 중량 kg",
"equipment_types_json":"차량 지원 컨테이너 종류 배열",
"window_id":"반입시간창 ID",
"voyage_id":"내부 항차 ID; 외부 선명/ETB와 별개",
"terminal_id":"반입 터미널 장소 ID",
"opens_at":"반입 시작 시각",
"closes_at":"반입 마감 시각; ETB와 별개",
"verification":"확인·미확인·충돌 상태",
"confirmed_by":"확인자 식별자; 미확인시 NULL 가능",
"confirmed_at":"확인 시각; 미확인시 NULL 가능",
"job_id":"입력 안에서의 작업 ID",
"origin_id":"상차지 장소 ID",
"return_location_id":"작업 후 복귀 장소 ID",
"ready_at":"화물 준비 시각; 미확보 NULL",
"gross_weight_kg":"총중량 kg; 미확보 NULL",
"equipment_type":"DRY20/DRY40",
"service_minutes":"터미널 처리 분; 미확보 NULL",
"state":"계획 또는 이미 출발 상태",
"frozen":"고정 작업 여부 0/1",
"freeze_reason":"고정 이유",
"from_location_id":"이동 출발 장소",
"to_location_id":"이동 도착 장소",
"minutes":"이동 소요 분; 음수 불가",
"change_id":"반입시간 변경 이벤트 ID",
"previous_opens_at":"변경 전 반입 시작",
"previous_closes_at":"변경 전 반입 마감",
"new_window_id":"변경 후 반입시간창",
"sequence":"차량 내 실행 순서; 1부터 시작",
"pickup_departure_at":"상차지 출발 시각",
"gate_arrival_at":"게이트 도착 시각; 불명 NULL",
"return_at":"복귀 완료 시각; 불명 NULL",
"version":"이 승인 계획의 revision",
"approval_id":"승인 감사 기록 ID; 최초 원안은 NULL",
"plan_json":"권위 계획 버전 JSON; 배정/미처리 포함",
"current_version":"현재 승인 계획 버전; CAS 대상",
"active_scenario_id":"현재 활성 입력 revision; 버전과 함께 CAS",
"updated_at":"head 최종 갱신 시각",
"run_id":"비교 계산 실행 ID",
"status":"실행 대기·진행·완료·실패·취소",
"started_at":"실행 시작 시각; 미시작 NULL",
"finished_at":"실행 종료 시각; 미종료 NULL",
"methods_json":"요청한 B0~B3 배열",
"time_limit_seconds":"계산 시간 제한; 1~120초",
"seed":"재현용 난수 seed",
"error_json":"실행 실패 상세 Error JSON; 오류 없으면 NULL",
"method":"B0/B1/B2/B3 방식",
"result_origin":"설명용 예제 또는 계산 결과",
"solution_status":"계산/검사 상태; 최적성 의미는 별도 확인",
"objective_proven":"목적함수 최적성 입증 여부 0/1",
"approval_eligible":"현재 결과의 승인 후보 자격 0/1; 승인 그 자체 아님",
"result_json":"해당 방식의 결과 전체; 입력/계획과 연결",
"expected_version":"승인 요청이 기대한 현재 계획 버전",
"approved_by":"서버 인증에서 얻은 승인자 ID",
"approved_at":"내부 승인 시각",
"acknowledged_job_ids_json":"요청자가 확인한 미처리/위험 작업 ID 배열",
"external_actions_performed":"v0.1은 항상 0; 외부 연락·예약 미수행",
"actor_id":"인증된 요청자 ID; 요청 body로 신뢰 금지",
"route":"HTTP 메서드+구체 경로; 멱등키 범위",
"idempotency_key":"동일 요청 재시도 식별자",
"request_sha256":"요청 body 해시; 다른 body 재사용은 API 409",
"response_status":"저장된 응답 HTTP 상태",
"response_json":"재시도에 반환할 완료 응답 JSON",
}

def write_dictionary(conn):
    path=COMMON/"DB_필드사전.tsv"
    count=0
    tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    with path.open("w",encoding="utf-8-sig",newline="") as fp:
        writer=csv.writer(fp,delimiter="\t")
        writer.writerow(["테이블","필드","SQLite형","NULL허용","기본키순서","기본값","외래키","설명"])
        for table in tables:
            refs={}
            for fk in conn.execute(f'PRAGMA foreign_key_list("{table}")'):
                refs.setdefault(fk["from"],[]).append(f'{fk["table"]}.{fk["to"]} (FK#{fk["id"]}:{fk["seq"]})')
            for col in conn.execute(f'PRAGMA table_xinfo("{table}")'):
                nullable="아니오" if col["notnull"] or col["pk"] else "예"
                writer.writerow([table,col["name"],col["type"],nullable,col["pk"],
                    "" if col["dflt_value"] is None else col["dflt_value"],
                    " | ".join(refs.get(col["name"],[])),DESCRIPTIONS.get(col["name"],"")])
                count+=1
    return count

if __name__=="__main__":
    main()
