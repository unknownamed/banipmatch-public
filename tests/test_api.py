from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import sqlite3
import subprocess
import threading
import time
from unittest.mock import patch
from urllib.parse import urljoin
from uuid import uuid4

from fastapi.testclient import TestClient
from openapi_spec_validator import validate as validate_openapi
import pytest

from backend.api.app import create_app
from backend.api.contracts import DRAFT, digest, validate
from backend.api.fixture import FixtureReplay
from backend.api.engine_replay import EngineReplay
from conftest import make_client


def post(client, path, body, key=None):
    return client.post(path, json=body, headers={"Idempotency-Key": key or uuid4().hex})


def start(client, snapshot):
    registered = post(client, "/v1/scenarios", snapshot)
    assert registered.status_code == 201, registered.text
    response = post(client, "/v1/runs", {
        "scenario_id": snapshot["scenario_id"], "base_plan_version": snapshot["base_plan_version"],
        "methods": ["B0", "B3"], "time_limit_seconds": 10, "seed": 42,
    })
    assert response.status_code == 202, response.text
    return response.json()


def results(client, run, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/v1/runs/{run['run_id']}/results")
        if response.status_code != 202:
            return response
        validate("Run", response.json())
        time.sleep(0.01)
    pytest.fail("설명용 결과 작업이 종료되지 않음")


def approval(run, **updates):
    return {"run_id": run["run_id"], "method": "B3", "expected_version": 1,
            "acknowledged_job_ids": ["J3"], **updates}


def test_registration_round_trip_and_projections(client, snapshot):
    response = post(client, "/v1/scenarios", snapshot)
    assert response.status_code == 201, response.text
    validate("RegisteredScenario", response.json())
    assert response.json()["input_sha256"] == digest(snapshot)
    stored = client.get("/v1/scenarios/S001")
    assert stored.json() == snapshot
    validate("Snapshot", stored.json())
    plan = client.get("/v1/plans/P001").json()
    validate("Plan", plan)
    assert plan["assignments"] == snapshot["baseline_assignments"]
    assert plan["approval_id"] is None
    with client.app.state.store.db.connect() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA recursive_triggers").fetchone()[0] == 1
        for table, count in {"scenarios": 1, "plans": 1, "assignments": 4, "jobs": 4,
                             "locations": 3, "vehicles": 2, "windows": 2, "travel_times": 9,
                             "changes": 1, "baseline_assignments": 4, "baseline_unassigned": 0,
                             "plan_heads": 1, "idempotency_records": 1}.items():
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == count
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("UPDATE scenarios SET snapshot_json=snapshot_json")


def test_fixture_flow_and_approval_blocked(client, snapshot):
    run = start(client, snapshot)
    assert run["status"] == "queued"
    validate("Run", run)
    response = results(client, run)
    assert response.status_code == 200, response.text
    value = response.json()
    validate("Results", value)
    expected = json.loads((DRAFT / "예제 데이터" / "04_results_설명용.json").read_text(encoding="utf-8"))
    assert value["results"] == expected["results"]
    assert value["input_sha256"] == digest(snapshot)
    assert client.get(f"/v1/runs/{run['run_id']}").json()["status"] == "completed"
    denied = post(client, "/v1/plans/P001/approvals", approval(run))
    assert denied.status_code == 422
    assert denied.json()["code"] == "RESULT_NOT_COMPUTED"
    validate("Error", denied.json())
    with client.app.state.store.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM plans").fetchone()[0] == 1


def test_same_post_replays_original_response_and_conflicting_body_rejected(client, snapshot):
    first = post(client, "/v1/scenarios", snapshot, "register-one")
    assert post(client, "/v1/scenarios", snapshot, "register-one").json() == first.json()
    changed = deepcopy(snapshot)
    changed["scenario_id"] = "different"
    assert post(client, "/v1/scenarios", changed, "register-one").status_code == 409
    request = {"scenario_id": "S001", "base_plan_version": 1, "methods": ["B0", "B3"],
               "time_limit_seconds": 10, "seed": 42}
    first_run = post(client, "/v1/runs", request, "run-one")
    assert results(client, first_run.json()).status_code == 200
    repeated = post(client, "/v1/runs", request, "run-one")
    assert repeated.status_code == 202
    assert repeated.json() == first_run.json()  # 최초 queued 응답 보존
    request["seed"] = 43
    assert post(client, "/v1/runs", request, "run-one").status_code == 409
    with client.app.state.store.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1


def test_concurrent_same_key_creates_one_snapshot(client, snapshot):
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(pool.map(lambda _: post(client, "/v1/scenarios", snapshot, "race"), range(6)))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert all(r.json() == responses[0].json() for r in responses)
    with client.app.state.store.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM scenarios").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM idempotency_records").fetchone()[0] == 1


def test_new_input_preserves_history_and_invalidates_old_run(client, snapshot):
    run = start(client, snapshot)
    assert results(client, run).status_code == 200
    changed = deepcopy(snapshot)
    changed["scenario_id"] = "S002"
    changed["windows"][0]["closes_at"] = "2026-11-07T01:20:00Z"
    assert post(client, "/v1/scenarios", changed).status_code == 201
    assert client.get("/v1/scenarios/S001").json() == snapshot
    assert results(client, run).status_code == 200
    denied = post(client, "/v1/plans/P001/approvals", approval(run))
    assert denied.status_code == 409
    assert denied.json()["code"] == "PLAN_VERSION_CONFLICT"
    stale_run = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                       "methods": ["B0"], "time_limit_seconds": 10, "seed": 42})
    assert stale_run.status_code == 409
    with client.app.state.store.db.connect() as conn:
        assert conn.execute("SELECT active_scenario_id FROM plan_heads").fetchone()[0] == "S002"
        assert conn.execute("SELECT current_version FROM plan_heads").fetchone()[0] == 1


@pytest.mark.parametrize("field", ["baseline", "version"])
def test_new_input_must_match_current_plan(client, snapshot, field):
    assert post(client, "/v1/scenarios", snapshot).status_code == 201
    snapshot["scenario_id"] = "S002"
    if field == "version":
        snapshot["base_plan_version"] = 2
    else:
        snapshot["baseline_assignments"][1]["pickup_departure_at"] = "2026-11-07T01:11:00Z"
    assert post(client, "/v1/scenarios", snapshot).status_code == 409
    assert client.get("/v1/scenarios/S002").status_code == 404


@pytest.mark.parametrize("mutation", ["reference", "duplicate", "coverage", "frozen", "precision", "real", "field"])
def test_invalid_input_rolls_back_all_writes(client, snapshot, mutation):
    if mutation == "reference":
        snapshot["jobs"][1]["origin_id"] = "unknown"
    elif mutation == "duplicate":
        snapshot["jobs"].append(deepcopy(snapshot["jobs"][0]))
    elif mutation == "coverage":
        snapshot["baseline_assignments"].pop()
    elif mutation == "frozen":
        snapshot["baseline_assignments"].pop(0)
        snapshot["baseline_unassigned_job_ids"].append("J0")
    elif mutation == "precision":
        snapshot["jobs"][1]["ready_at"] = "2026-11-07T00:00:01Z"
    elif mutation == "real":
        snapshot["data_mode"] = "observed"
    else:
        snapshot["made_up_field"] = 1
    response = post(client, "/v1/scenarios", snapshot)
    assert response.status_code == 422, response.text
    validate("Error", response.json())
    with client.app.state.store.db.connect() as conn:
        for table in ("scenarios", "plans", "plan_heads", "jobs", "idempotency_records"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("file, status, code", [
    ("07_snapshot_입력누락.json", 422, "INPUT_INCOMPLETE"),
    ("08_snapshot_미확인변경.json", 503, "WINDOW_UNCONFIRMED"),
])
def test_schema_valid_but_unusable_inputs_do_not_receive_fixture(client, file, status, code):
    snapshot = json.loads((DRAFT / "예제 데이터" / file).read_text(encoding="utf-8"))
    assert post(client, "/v1/scenarios", snapshot).status_code == 201
    response = post(client, "/v1/runs", {"scenario_id": snapshot["scenario_id"], "base_plan_version": 1,
                     "methods": ["B0", "B3"], "time_limit_seconds": 10, "seed": 42})
    assert response.status_code == status
    assert response.json()["code"] == code
    with client.app.state.store.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0


def test_fixture_not_reused_for_modified_input_or_unavailable_method(client, snapshot):
    snapshot["jobs"][1]["ready_at"] = "2026-11-07T00:01:00Z"
    assert post(client, "/v1/scenarios", snapshot).status_code == 201
    request = {"scenario_id": "S001", "base_plan_version": 1, "methods": ["B0"],
               "time_limit_seconds": 10, "seed": 42}
    denied = post(client, "/v1/runs", request)
    assert denied.json()["code"] == "DEMO_INPUT_MISMATCH"
    snapshot["scenario_id"], snapshot["plan_id"] = "S003", "P003"
    snapshot["jobs"][1]["ready_at"] = "2026-11-07T00:00:00Z"
    assert post(client, "/v1/scenarios", snapshot).status_code == 201
    request.update(scenario_id="S003", methods=["B1"])
    assert post(client, "/v1/runs", request).json()["code"] == "DEMO_METHOD_UNAVAILABLE"


class BlockingReplay(FixtureReplay):
    def __init__(self):
        super().__init__()
        self.entered, self.release = threading.Event(), threading.Event()

    def replay(self, snapshot, methods, config):
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("test worker wait exceeded")
        return super().replay(snapshot, methods, config)


def test_running_job_does_not_block_reads(settings, snapshot):
    adapter = BlockingReplay()
    with make_client(settings, replay=adapter) as client:
        try:
            run = start(client, snapshot)
            assert adapter.entered.wait(timeout=2)
            response = client.get(f"/v1/runs/{run['run_id']}/results")
            assert response.status_code == 202
            assert response.json()["status"] == "running"
            assert response.headers["retry-after"] == "1"
            assert client.get("/v1/scenarios/S001").status_code == 200
            assert client.get("/v1/plans/P001").status_code == 200
            assert post(client, "/v1/plans/P001/approvals", approval(run)).status_code == 422
        finally:
            adapter.release.set()
        assert results(client, run).status_code == 200


class BrokenReplay(FixtureReplay):
    def replay(self, snapshot, methods, config):
        raise RuntimeError("sensitive-value-must-not-be-returned")


class InvalidReplay(FixtureReplay):
    def replay(self, snapshot, methods, config):
        result = super().replay(snapshot, methods, config)
        result[-1]["approval_eligible"] = True
        return result


@pytest.mark.parametrize("adapter", [BrokenReplay, InvalidReplay])
def test_failed_or_mislabelled_worker_never_publishes_partial_results(settings, snapshot, adapter):
    with make_client(settings, replay=adapter()) as client:
        run = start(client, snapshot)
        assert results(client, run).status_code == 503
        state = client.get(f"/v1/runs/{run['run_id']}")
        validate("Run", state.json())
        assert state.json()["status"] == "failed"
        assert "sensitive-value" not in state.text
        with client.app.state.store.db.connect() as conn:
            assert conn.execute("SELECT count(*) FROM method_results").fetchone()[0] == 0


@pytest.mark.parametrize("status", ["queued", "running"])
def test_restart_recovers_interrupted_runs_and_preserves_saved_input(settings, snapshot, status):
    with make_client(settings) as client:
        assert post(client, "/v1/scenarios", snapshot).status_code == 201
        store = client.app.state.store
        _, run = store.create_run({"scenario_id": "S001", "base_plan_version": 1, "methods": ["B0"],
                                   "time_limit_seconds": 10, "seed": 42}, "interrupted", FixtureReplay().check)
        with store.db.transaction() as conn:
            conn.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run["run_id"]))
    with make_client(settings) as client:
        assert client.get("/v1/scenarios/S001").json() == snapshot
        recovered = client.get(f"/v1/runs/{run['run_id']}").json()
        assert recovered["status"] == "failed"
        assert recovered["error"]["code"] == "RUN_INTERRUPTED"
        assert results(client, run).status_code == 503


def test_second_server_cannot_recover_another_owners_jobs(settings):
    with make_client(settings):
        with pytest.raises(RuntimeError, match="같은 DB"):
            with make_client(settings):
                pass
    with make_client(settings) as client:
        assert client.get("/v1/scenarios/missing").status_code == 404


def test_auth_and_request_errors_use_common_error(client, snapshot):
    denied = client.get("/v1/scenarios/S001", headers={"Authorization": "Bearer forged"})
    assert denied.status_code == 401
    validate("Error", denied.json())
    assert denied.headers["www-authenticate"] == "Bearer"
    missing_key = client.post("/v1/scenarios", json=snapshot)
    assert missing_key.status_code == 422
    validate("Error", missing_key.json())
    malformed = client.post("/v1/scenarios", content="{", headers={"Content-Type": "application/json"})
    assert malformed.status_code == 422
    validate("Error", malformed.json())
    assert client.get("/v1/scenarios/missing").status_code == 404
    assert client.get("/v1/runs/missing").status_code == 404
    assert client.get("/v1/plans/missing").status_code == 404
    invalid_host = client.get("/v1/scenarios/S001", headers={"Host": "evil.example"})
    assert invalid_host.status_code == 400
    validate("Error", invalid_host.json())
    unknown_path = client.get("/not-an-api")
    validate("Error", unknown_path.json())


def test_nonfinite_json_is_rejected(client, snapshot):
    snapshot["locations"][0]["latitude"] = float("nan")
    response = client.post("/v1/scenarios", content=json.dumps(snapshot),
                           headers={"Content-Type": "application/json", "Idempotency-Key": "nan"})
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_JSON_NUMBER"


def test_loopback_and_explicit_demo_required(settings):
    with TestClient(create_app(settings), base_url="http://127.0.0.1",
                    client=("192.0.2.1", 50000)) as remote:
        assert remote.get("/openapi.json").status_code == 403
    for invalid in (replace(settings, demo_enabled=False), replace(settings, demo_token="short")):
        with pytest.raises(RuntimeError, match="BANIPMATCH_DEMO"):
            with make_client(invalid):
                pass


def test_cors_and_runtime_openapi(client):
    response = client.options("/v1/runs", headers={"Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "Authorization,Content-Type,Idempotency-Key"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert client.get("/v1/plans/P001", headers={"Origin": "https://evil.example"}).status_code == 403
    response = client.get("/openapi.json")
    spec = response.json()
    validate_openapi(spec)
    assert spec["components"]["schemas"] == json.loads(
        (DRAFT / "공통 규격" / "openapi.json").read_text(encoding="utf-8")
    )["components"]["schemas"]
    assert spec["paths"]["/v1/plans/{plan_id}/approvals"]["post"]["x-implementation-status"] == "local-demo"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8000", "http://localhost:8000"])
def test_swagger_same_origin_post_is_allowed(client, snapshot, origin):
    response = client.post(f"{origin}/v1/scenarios", json=snapshot,
                           headers={"Origin": origin, "Idempotency-Key": "swagger-post"})
    assert response.status_code == 201, response.text


def test_execution_preflight_blocks_missing_route_without_losing_registered_input(client, snapshot):
    snapshot["travel_times"] = [row for row in snapshot["travel_times"]
                                if (row["from_location_id"], row["to_location_id"]) != ("D", "O")]
    assert post(client, "/v1/scenarios", snapshot).status_code == 201
    request = {"scenario_id": "S001", "base_plan_version": 1, "methods": ["B0"],
               "time_limit_seconds": 10, "seed": 42}
    response = post(client, "/v1/runs", request, "missing-route")
    assert response.status_code == 422
    assert response.json()["code"] == "INPUT_INCOMPLETE"
    assert any("TRAVEL_TIME_MISSING" in d["reason"] for d in response.json()["details"])
    assert client.get("/v1/scenarios/S001").json() == snapshot
    with client.app.state.store.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM idempotency_records WHERE route='POST /v1/runs'").fetchone()[0] == 0


def test_execution_preflight_checks_evidence_precision(client, snapshot):
    snapshot["jobs"][1]["evidence"]["received_at"] = "2026-11-07T00:00:01Z"
    assert post(client, "/v1/scenarios", snapshot).status_code == 201
    response = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                    "methods": ["B0"], "time_limit_seconds": 10, "seed": 42})
    assert response.status_code == 422
    assert response.json()["code"] == "INPUT_INVALID"
    assert any(d["path"] == "/jobs/1/evidence/received_at" for d in response.json()["details"])


def test_real_engine_run_is_computed_and_expired_input_cannot_be_approved(settings, snapshot):
    with make_client(replace(settings, run_mode="engine")) as client:
        assert "B0~B3 실계산 모드" in client.get("/openapi.json").json()["info"]["description"]
        assert post(client, "/v1/scenarios", snapshot).status_code == 201
        request = {"scenario_id": "S001", "base_plan_version": 1, "methods": ["B0", "B1"],
                   "time_limit_seconds": 10, "seed": 42}
        response = post(client, "/v1/runs", request)
        assert response.status_code == 202
        run = response.json()
        result = results(client, run)
        assert result.status_code == 200, result.text
        validate("Results", result.json())
        methods = result.json()["results"]
        assert [r["method"] for r in methods] == ["B0", "B1"]
        assert all(r["result_origin"] == "computed" for r in methods)
        assert methods[0]["validation_status"] == "not_run" and not methods[0]["approval_eligible"]
        assert methods[1]["validation_status"] == "passed" and methods[1]["approval_eligible"]
        assert next(a for a in methods[1]["assignments"] if a["job_id"] == "J0") == snapshot["baseline_assignments"][0]
        assert "J3" in methods[1]["unassigned_job_ids"]
        denied = post(client, "/v1/plans/P001/approvals", approval(run, method="B1"))
        assert denied.status_code == 503
        assert denied.json()["code"] == "INPUT_EXPIRED"


def test_engine_mode_runs_and_independently_checks_optimized_methods(settings, snapshot):
    with make_client(settings, replay=EngineReplay()) as client:
        assert post(client, "/v1/scenarios", snapshot).status_code == 201
        response = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                        "methods": ["B2", "B3"], "time_limit_seconds": 10, "seed": 42})
        assert response.status_code == 202
        returned = results(client, response.json(), timeout=40)
        assert returned.status_code == 200, returned.text
        result_list = returned.json()["results"]
        assert [r["method"] for r in result_list] == ["B2", "B3"]
        for result in result_list:
            assert result["result_origin"] == "computed"
            assert result["validation_status"] == "passed"
            assert result["approval_eligible"] is True
            assert next(a for a in result["assignments"] if a["job_id"] == "J0") == snapshot["baseline_assignments"][0]
            if result["objective_proven"]:
                assert result["solution_status"] == "OPTIMAL"


def test_proven_optimization_is_stored_and_independently_checked(settings, snapshot):
    from backend.engine import solve
    result = solve(snapshot, "B1", {"time_limit_seconds": 10, "seed": 42})
    unassigned = result["metrics"]["unassigned_count"]
    travel = result["metrics"]["movable_travel_minutes"]
    result.update(method="B2", solution_status="OPTIMAL", objective_proven=True,
                  objective_stages=[{"objective": "unassigned", "status": "OPTIMAL", "value": unassigned, "best_bound": unassigned},
                                    {"objective": "travel", "status": "OPTIMAL", "value": travel, "best_bound": travel}])
    success = subprocess.CompletedProcess([], 0, stdout=json.dumps(result), stderr="")
    with patch("backend.api.engine_replay.subprocess.run", return_value=success):
        with make_client(settings, replay=EngineReplay()) as client:
            assert post(client, "/v1/scenarios", snapshot).status_code == 201
            response = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                            "methods": ["B2"], "time_limit_seconds": 10, "seed": 42})
            stored = results(client, response.json()).json()["results"][0]
            assert stored["objective_proven"] is True
            assert stored["validation_status"] == "passed"
            assert stored["approval_eligible"] is True


def test_local_approval_is_atomic_idempotent_and_versioned(settings, snapshot):
    with make_client(settings, replay=EngineReplay()) as client:
        assert post(client, "/v1/scenarios", snapshot).status_code == 201
        response = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                        "methods": ["B1"], "time_limit_seconds": 10, "seed": 42})
        run = response.json()
        assert results(client, run, timeout=20).status_code == 200
        request = approval(run, method="B1")
        with patch("backend.db.store.utc_now", return_value="2026-11-07T00:30:00Z"):
            missing = post(client, "/v1/plans/P001/approvals", {**request, "acknowledged_job_ids": []}, "missing")
            assert missing.status_code == 422
            assert missing.json()["code"] == "ACKNOWLEDGEMENT_REQUIRED"
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses = list(pool.map(lambda _: post(client, "/v1/plans/P001/approvals", request, "same-approval"), range(4)))
            assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
            assert all(r.json() == responses[0].json() for r in responses)
            approved = responses[0].json()
            validate("Approval", approved)
            assert approved["version"] == 2 and approved["external_actions_performed"] is False
            plan = client.get("/v1/plans/P001").json()
            validate("Plan", plan)
            assert plan["approval_id"] == approved["approval_id"] and plan["version"] == 2
            assert post(client, "/v1/plans/P001/approvals", request, "different-key").status_code == 409
            assert post(client, "/v1/plans/P001/approvals", {**request, "acknowledged_job_ids": []}, "same-approval").json()["code"] == "IDEMPOTENCY_CONFLICT"
        assert post(client, "/v1/plans/P001/approvals", request, "same-approval").json() == approved
        with client.app.state.store.db.connect() as conn:
            assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM plans").fetchone()[0] == 2
            assert conn.execute("SELECT current_version FROM plan_heads").fetchone()[0] == 2
        next_snapshot = deepcopy(snapshot)
        next_snapshot.update(scenario_id="S002", base_plan_version=2,
                             baseline_assignments=plan["assignments"], baseline_unassigned_job_ids=plan["unassigned_job_ids"])
        assert post(client, "/v1/scenarios", next_snapshot).status_code == 201
        assert post(client, "/v1/plans/P001/approvals", request, "old-result").status_code == 409


def test_expired_or_future_input_cannot_be_approved(settings, snapshot):
    with make_client(settings, replay=EngineReplay()) as client:
        assert post(client, "/v1/scenarios", snapshot).status_code == 201
        run = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                   "methods": ["B1"], "time_limit_seconds": 10, "seed": 42}).json()
        assert results(client, run, timeout=20).status_code == 200
        for clock, code in (("2026-11-06T23:59:00Z", "INPUT_STALE"), ("2026-11-07T03:00:01Z", "INPUT_EXPIRED")):
            with patch("backend.db.store.utc_now", return_value=clock):
                denied = post(client, "/v1/plans/P001/approvals", approval(run, method="B1"))
                assert denied.status_code == 503 and denied.json()["code"] == code
        with client.app.state.store.db.connect() as conn:
            assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0


def test_competing_approvals_allow_only_one_version(settings, snapshot):
    with make_client(settings, replay=EngineReplay()) as client:
        assert post(client, "/v1/scenarios", snapshot).status_code == 201
        run = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                   "methods": ["B1"], "time_limit_seconds": 10, "seed": 42}).json()
        assert results(client, run, timeout=20).status_code == 200
        with patch("backend.db.store.utc_now", return_value="2026-11-07T00:30:00Z"):
            with ThreadPoolExecutor(max_workers=4) as pool:
                responses = list(pool.map(lambda n: post(client, "/v1/plans/P001/approvals", approval(run, method="B1"), f"competing-{n}"), range(4)))
        assert sorted(r.status_code for r in responses) == [201, 409, 409, 409]
        with client.app.state.store.db.connect() as conn:
            assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 1
            assert conn.execute("SELECT count(*) FROM plans").fetchone()[0] == 2


def test_approval_storage_failure_rolls_back_everything(settings, snapshot):
    from backend.db import store as store_module
    original_insert = store_module.insert
    def fail_approval(conn, table, row, field_paths=None):
        if table == "approvals":
            raise sqlite3.OperationalError("simulated storage failure")
        return original_insert(conn, table, row, field_paths)
    with make_client(settings, replay=EngineReplay()) as client:
        assert post(client, "/v1/scenarios", snapshot).status_code == 201
        run = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                   "methods": ["B1"], "time_limit_seconds": 10, "seed": 42}).json()
        assert results(client, run, timeout=20).status_code == 200
        with patch("backend.db.store.utc_now", return_value="2026-11-07T00:30:00Z"):
            with patch("backend.db.store.insert", side_effect=fail_approval):
                denied = post(client, "/v1/plans/P001/approvals", approval(run, method="B1"), "retry-after-failure")
                assert denied.status_code == 503 and denied.json()["code"] == "STORAGE_UNAVAILABLE"
            with client.app.state.store.db.connect() as conn:
                assert conn.execute("SELECT count(*) FROM plans").fetchone()[0] == 1
                assert conn.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
                assert conn.execute("SELECT current_version FROM plan_heads").fetchone()[0] == 1
                assert conn.execute("SELECT count(*) FROM idempotency_records WHERE idempotency_key='retry-after-failure'").fetchone()[0] == 0
            assert post(client, "/v1/plans/P001/approvals", approval(run, method="B1"), "retry-after-failure").status_code == 201


def test_metric_mismatch_never_becomes_eligible(settings, snapshot):
    from backend.engine import solve
    result = solve(snapshot, "B1", {"time_limit_seconds": 10, "seed": 42})
    result["metrics"]["movable_travel_minutes"] += 1
    success = subprocess.CompletedProcess([], 0, stdout=json.dumps(result), stderr="")
    with patch("backend.api.engine_replay.subprocess.run", return_value=success):
        with make_client(settings, replay=EngineReplay()) as client:
            assert post(client, "/v1/scenarios", snapshot).status_code == 201
            run = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                       "methods": ["B1"], "time_limit_seconds": 10, "seed": 42}).json()
            result = results(client, run).json()["results"][0]
            assert result["validation_status"] == "failed" and not result["approval_eligible"]
            assert post(client, "/v1/plans/P001/approvals", approval(run, method="B1")).json()["code"] == "RESULT_NOT_ELIGIBLE"


def test_fixed_residual_risk_must_be_verified_and_acknowledged(settings, snapshot):
    from backend.api.result_integrity import verify_schedule
    from backend.engine import solve
    snapshot["jobs"][0]["gross_weight_kg"] = 100000
    result = solve(snapshot, "B1", {"time_limit_seconds": 10, "seed": 42})
    assert verify_schedule(snapshot, result)
    tampered = deepcopy(result)
    tampered["issues"] = [i for i in tampered["issues"] if i["job_id"] != "J0"]
    assert not verify_schedule(snapshot, tampered)
    tampered = deepcopy(result)
    tampered["metrics"]["movable_travel_minutes"] += 1
    assert not verify_schedule(snapshot, tampered)
    with make_client(settings, replay=EngineReplay()) as client:
        assert post(client, "/v1/scenarios", snapshot).status_code == 201
        run = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                   "methods": ["B1"], "time_limit_seconds": 10, "seed": 42}).json()
        computed = results(client, run, timeout=20).json()["results"][0]
        assert computed["validation_status"] == "passed" and computed["approval_eligible"]
        with patch("backend.db.store.utc_now", return_value="2026-11-07T00:30:00Z"):
            missing = post(client, "/v1/plans/P001/approvals", approval(run, method="B1"))
            assert missing.status_code == 422 and missing.json()["code"] == "ACKNOWLEDGEMENT_REQUIRED"
            accepted = post(client, "/v1/plans/P001/approvals", approval(run, method="B1", acknowledged_job_ids=["J0", "J3"]))
            assert accepted.status_code == 201, accepted.text


@pytest.mark.parametrize("mutation", ["drop_fixed", "duplicate_job", "duplicate_slot", "invalid_time"])
def test_engine_rejects_corrupt_assignment_without_partial_results(settings, snapshot, mutation):
    from backend.engine import solve
    result = solve(snapshot, "B1", {"time_limit_seconds": 10, "seed": 42})
    if mutation == "drop_fixed":
        result["assignments"] = [a for a in result["assignments"] if a["job_id"] != "J0"]
        result["unassigned_job_ids"].append("J0")
    elif mutation == "duplicate_job":
        result["assignments"].append(deepcopy(result["assignments"][0]))
    elif mutation == "duplicate_slot":
        result["assignments"][1]["vehicle_id"] = result["assignments"][0]["vehicle_id"]
        result["assignments"][1]["sequence"] = result["assignments"][0]["sequence"]
    else:
        movable = next(a for a in result["assignments"] if a["job_id"] != "J0")
        movable["gate_arrival_at"] = "2026-11-08T00:00:00Z"
    success = subprocess.CompletedProcess([], 0, stdout=json.dumps(result), stderr="")
    with patch("backend.api.engine_replay.subprocess.run", return_value=success):
        with make_client(settings, replay=EngineReplay()) as client:
            assert post(client, "/v1/scenarios", snapshot).status_code == 201
            response = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                            "methods": ["B1"], "time_limit_seconds": 10, "seed": 42})
            assert results(client, response.json()).status_code == 503
            with client.app.state.store.db.connect() as conn:
                assert conn.execute("SELECT count(*) FROM method_results").fetchone()[0] == 0


def test_engine_failure_discards_partial_results_and_records_method(settings, snapshot):
    from backend.engine import solve
    first = solve(snapshot, "B0", {"time_limit_seconds": 10, "seed": 42})
    success = subprocess.CompletedProcess([], 0, stdout=json.dumps(first), stderr="")
    with patch("backend.api.engine_replay.subprocess.run", side_effect=[success, subprocess.TimeoutExpired("engine", 15)]):
        with make_client(settings, replay=EngineReplay()) as client:
            assert post(client, "/v1/scenarios", snapshot).status_code == 201
            response = post(client, "/v1/runs", {"scenario_id": "S001", "base_plan_version": 1,
                            "methods": ["B0", "B1"], "time_limit_seconds": 10, "seed": 42})
            run = response.json()
            assert results(client, run).status_code == 503
            state = client.get(f"/v1/runs/{run['run_id']}").json()
            assert state["status"] == "failed"
            assert "B1" in state["error"]["details"][0]["reason"]
            with client.app.state.store.db.connect() as conn:
                assert conn.execute("SELECT count(*) FROM method_results").fetchone()[0] == 0


@pytest.mark.parametrize("origin", ["http://localhost:8000", "http://localhost:8123", "http://127.0.0.1:8123"])
def test_swagger_resolves_runtime_server_on_current_host_and_port(client, snapshot, origin):
    spec_response = client.get(f"{origin}/openapi.json")
    assert spec_response.status_code == 200
    spec = spec_response.json()
    server = urljoin(f"{origin}/openapi.json", spec["servers"][0]["url"])
    response = client.post(urljoin(server.rstrip("/") + "/", "v1/scenarios"), json=snapshot,
                           headers={"Origin": origin, "Idempotency-Key": "swagger-resolved"})
    assert response.status_code == 201, response.text
    assert spec["servers"][0]["url"] == "/"
    archived = json.loads((DRAFT / "공통 규격" / "openapi.json").read_text(encoding="utf-8"))
    assert archived["servers"][0]["url"] == "http://127.0.0.1:8000"


@pytest.mark.parametrize("value", [2**63, float(2**63)])
def test_run_integer_overflow_has_field_error_and_no_partial_records(client, snapshot, value):
    assert post(client, "/v1/scenarios", snapshot).status_code == 201
    request = {"scenario_id": "S001", "base_plan_version": 1, "methods": ["B0"],
               "time_limit_seconds": 10, "seed": value}
    response = post(client, "/v1/runs", request, "seed-boundary")
    assert response.status_code == 422, response.text
    validate("Error", response.json())
    assert response.json()["code"] == "INTEGER_OUT_OF_RANGE"
    assert response.json()["details"][0]["path"] == "/seed"
    with client.app.state.store.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM method_results").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM idempotency_records").fetchone()[0] == 1
        assert conn.execute("SELECT current_version FROM plan_heads").fetchone()[0] == 1
    # 거절한 요청의 멱등 기록을 남기지 않아 같은 키로 수정 요청을 보낼 수 있어야 함.
    request["seed"] = 2**63 - 1
    accepted = post(client, "/v1/runs", request, "seed-boundary")
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["config"]["seed"] == 2**63 - 1
    assert results(client, accepted.json()).status_code == 200
    with client.app.state.store.db.connect() as conn:
        stored = conn.execute("SELECT seed, typeof(seed) FROM runs").fetchone()
        assert tuple(stored) == (2**63 - 1, "integer")


@pytest.mark.parametrize("value", [2**63, float(2**63)])
def test_snapshot_integer_overflow_rolls_back_projections_and_idempotency(client, snapshot, value):
    # 두 번째 차량에서 실패시켜 앞서 삽입한 원본·장소·첫 차량도 롤백되는지 확인.
    snapshot["vehicles"][1]["capacity_kg"] = value
    response = post(client, "/v1/scenarios", snapshot, "capacity-boundary")
    assert response.status_code == 422, response.text
    validate("Error", response.json())
    assert response.json()["code"] == "INTEGER_OUT_OF_RANGE"
    assert response.json()["details"][0]["path"] == "/vehicles/1/capacity_kg"
    with client.app.state.store.db.connect() as conn:
        for table in ("scenarios", "locations", "vehicles", "jobs", "windows", "plans", "assignments",
                      "baseline_assignments", "baseline_unassigned", "plan_heads", "idempotency_records"):
            assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    snapshot["vehicles"][1]["capacity_kg"] = 2**63 - 1
    accepted = post(client, "/v1/scenarios", snapshot, "capacity-boundary")
    assert accepted.status_code == 201, accepted.text
    assert client.get("/v1/scenarios/S001").json() == snapshot
    with client.app.state.store.db.connect() as conn:
        stored = conn.execute("SELECT capacity_kg, typeof(capacity_kg) FROM vehicles WHERE vehicle_id='T2'").fetchone()
        assert tuple(stored) == (2**63 - 1, "integer")


@pytest.mark.parametrize("value", [42.0, float(2**63 - 1024)])
def test_integral_json_float_is_stored_as_integer_without_mutating_input(client, snapshot, value):
    snapshot["vehicles"][0]["capacity_kg"] = value
    original = deepcopy(snapshot)
    assert post(client, "/v1/scenarios", snapshot).status_code == 201
    assert snapshot == original
    assert client.get("/v1/scenarios/S001").json() == original
    with client.app.state.store.db.connect() as conn:
        stored = conn.execute("SELECT capacity_kg, typeof(capacity_kg) FROM vehicles WHERE vehicle_id='T1'").fetchone()
        assert tuple(stored) == (int(value), "integer")


@pytest.mark.parametrize("seed", [42.0, float(2**63 - 1024)])
def test_integral_json_float_run_config_is_stored_and_replayed(client, snapshot, seed):
    assert post(client, "/v1/scenarios", snapshot).status_code == 201
    request = {"scenario_id": "S001", "base_plan_version": 1.0, "methods": ["B0"],
               "time_limit_seconds": 10.0, "seed": seed}
    original = deepcopy(request)
    response = post(client, "/v1/runs", request, "float-config")
    assert response.status_code == 202, response.text
    validate("Run", response.json())
    assert request == original
    assert type(response.json()["config"]["seed"]) is int
    assert response.json()["config"] == {"seed": int(seed), "time_limit_seconds": 10}
    assert results(client, response.json()).status_code == 200
    assert post(client, "/v1/runs", original, "float-config").json() == response.json()


@pytest.mark.parametrize("collection,index,field,path", [
    (None, None, "base_plan_version", "/base_plan_version"),
    ("jobs", 1, "gross_weight_kg", "/jobs/1/gross_weight_kg"),
    ("jobs", 1, "service_minutes", "/jobs/1/service_minutes"),
    ("travel_times", 0, "minutes", "/travel_times/0/minutes"),
    ("baseline_assignments", 1, "sequence", "/baseline_assignments/1/sequence"),
])
def test_other_sqlite_integer_fields_have_precise_storage_errors(client, snapshot, collection, index, field, path):
    target = snapshot if collection is None else snapshot[collection][index]
    target[field] = 2**63
    response = post(client, "/v1/scenarios", snapshot)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "INTEGER_OUT_OF_RANGE"
    assert response.json()["details"][0]["path"] == path
    with client.app.state.store.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM scenarios").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM idempotency_records").fetchone()[0] == 0
