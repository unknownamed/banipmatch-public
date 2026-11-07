from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
import sqlite3
import threading
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from openapi_spec_validator import validate as validate_openapi
import pytest

from backend.api.app import create_app
from backend.api.contracts import DRAFT, digest, validate
from backend.api.fixture import FixtureReplay
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


def results(client, run):
    deadline = time.monotonic() + 5
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
            assert post(client, "/v1/plans/P001/approvals", approval(run)).status_code == 503
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
    assert spec["paths"]["/v1/plans/{plan_id}/approvals"]["post"]["x-implementation-status"] == "blocked"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]


@pytest.mark.parametrize("origin", ["http://127.0.0.1:8000", "http://localhost:8000"])
def test_swagger_same_origin_post_is_allowed(client, snapshot, origin):
    response = client.post(f"{origin}/v1/scenarios", json=snapshot,
                           headers={"Origin": origin, "Idempotency-Key": "swagger-post"})
    assert response.status_code == 201, response.text
