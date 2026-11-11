"""Isolated mock dispatches and injected transport only; never send to a phone."""
import base64
from copy import deepcopy
from dataclasses import dataclass, replace
import json
import time
from uuid import uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
import pytest

from backend.api.app import create_app
from backend.api.contracts import ApiError
from backend.workflow.routes import MANAGER_COOKIE, RECIPIENT_COOKIE
from backend.workflow.contracts import SessionState, RecipientState, DispatchState, NotificationState

ORIGIN = "http://127.0.0.1"


class Transport:
    configured = True
    application_server_key = "test-only-public-key"

    def __init__(self):
        self.calls = []
        self.outcomes = []

    def send(self, subscription, payload):
        self.calls.append((deepcopy(subscription), deepcopy(payload)))
        value = self.outcomes.pop(0) if self.outcomes else {"status": "accepted", "error_code": None}
        if isinstance(value, Exception):
            raise value
        return value


@dataclass
class Actor:
    client: TestClient
    cookie: str
    csrf: str
    info: dict

    def request(self, method, path, body=None, *, key=None):
        headers = {"Origin": ORIGIN, "Cookie": self.cookie, "X-CSRF-Token": self.csrf,
                   "Idempotency-Key": key or uuid4().hex}
        return self.client.request(method, path, json=body, headers=headers)

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, body, **kwargs):
        return self.request("POST", path, body, **kwargs)


def new_manager(client):
    response = client.post("/v2/session", headers={"Origin": ORIGIN, "Cookie": ""})
    assert response.status_code == 201, response.text
    data = response.json()
    token = client.cookies.get(MANAGER_COOKIE)
    return Actor(client, MANAGER_COOKIE + "=" + token, data["csrf_token"], data)


def allow(manager):
    hub = manager.client.app.state.workflow
    with hub.registry.transaction() as conn:
        conn.execute("UPDATE sessions SET push_authorized=1,consent_note='synthetic-consent-test' WHERE session_id=?",
                     (manager.info["session_id"],))


def seed(manager):
    response = manager.get("/v2/examples/default")
    assert response.status_code == 200, response.text
    snapshot = response.json()
    saved = manager.post("/v2/scenarios", snapshot)
    assert saved.status_code == 201, saved.text
    return snapshot


def calculate(manager, snapshot):
    response = manager.post("/v2/runs", {"scenario_id": snapshot["scenario_id"], "base_plan_version": snapshot["base_plan_version"],
        "methods": ["B1"], "time_limit_seconds": 1, "seed": 42})
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = manager.get(f"/v2/runs/{run_id}/results")
        if response.status_code != 202:
            assert response.status_code == 200, response.text
            return response.json()
        time.sleep(.1)
    pytest.fail("real B1 calculation did not finish")


def approve(manager, snapshot, results):
    result = results["results"][0]
    risks = {i["job_id"] for i in result["issues"] if i["code"] == "FIXED_RESIDUAL_RISK" and i["job_id"]}
    return manager.post(f"/v2/plans/{snapshot['plan_id']}/approvals", {
        "run_id": results["run_id"], "method": "B1", "expected_version": snapshot["base_plan_version"],
        "acknowledged_job_ids": sorted(set(result["unassigned_job_ids"]) | risks)})


def subscription(suffix="1"):
    raw = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return {"endpoint": "https://fcm.googleapis.com/fcm/send/SYNTHETIC-" + suffix,
            "keys": {"p256dh": encode(raw), "auth": encode(b"synthetic-auth16")}, "expirationTime": None}


def connect_recipient(manager, snapshot, vehicles):
    invitation = manager.post("/v2/invitations", {"plan_id": snapshot["plan_id"], "vehicle_ids": vehicles,
                                                "consent_acknowledged": True})
    assert invitation.status_code == 201, invitation.text
    data = invitation.json()
    response = manager.client.post("/v2/recipient/session", json={"invitation_token": data["invitation_token"],
        "accept_test_invitation": True}, headers={"Origin": ORIGIN, "Cookie": "", "Idempotency-Key": uuid4().hex})
    assert response.status_code == 201, response.text
    info = response.json()
    token = manager.client.cookies.get(RECIPIENT_COOKIE)
    return Actor(manager.client, RECIPIENT_COOKIE + "=" + token, info["csrf_token"], info), data


def subscribe(actor, value=None):
    result = actor.post("/v2/recipient/subscription", {"subscription": value or subscription(),
                        "notification_permission": "granted", "consent": True})
    assert result.status_code == 201, result.text
    return result


def wait_delivery(manager, dispatch_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        response = manager.get("/v2/dispatches/" + dispatch_id)
        assert response.status_code == 200, response.text
        if not any(n["delivery_status"] in {"pending", "sending"} for n in response.json()["notifications"]):
            return response.json()
        time.sleep(.02)
    pytest.fail("injected delivery did not finish")


@pytest.fixture
def workflow(settings, tmp_path):
    config = replace(settings, workflow_enabled=True, workflow_dir=tmp_path / "workflow")
    transport = Transport()
    app = create_app(config, push_sender=transport)
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as client:
        yield client, transport, config


def test_calculation_approval_invite_push_open_and_explicit_response_round_trip(workflow):
    client, transport, _ = workflow
    manager = new_manager(client)
    SessionState.model_validate(manager.info)
    snapshot = seed(manager)
    results = calculate(manager, snapshot)
    approval = approve(manager, snapshot, results)
    assert approval.status_code == 201, approval.text
    assert approval.json()["external_actions_performed"] is False
    preview = manager.get(f"/v2/plans/{snapshot['plan_id']}/dispatch-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["delivery_authorized"] is False
    allow(manager)
    vehicles = [v["vehicle_id"] for v in preview.json()["vehicle_changes"]]
    receiver, invitation = connect_recipient(manager, snapshot, vehicles)
    RecipientState.model_validate(receiver.info)
    subscribe(receiver)
    request = {"approval_id": approval.json()["approval_id"], "expected_version": 2, "confirm_test_send": True}
    dispatch = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches", request)
    assert dispatch.status_code == 202, dispatch.text
    sent = wait_delivery(manager, dispatch.json()["dispatch_id"])
    DispatchState.model_validate(sent)
    assert len(transport.calls) == 1
    notification = sent["notifications"][0]
    assert notification["delivery_status"] == "accepted" and notification["response"] == "none"
    assert notification["opened_at"] is None
    assert set(transport.calls[0][1]) == {"title", "body", "notification_id", "url"}
    nid = notification["notification_id"]
    opened = receiver.post(f"/v2/recipient/notifications/{nid}/opened", {})
    assert opened.status_code == 200, opened.text
    assert opened.json()["opened_at"] is not None and opened.json()["response"] == "none"
    can = receiver.post(f"/v2/recipient/notifications/{nid}/responses", {"response": "can_perform"})
    assert can.status_code == 200, can.text
    NotificationState.model_validate(can.json())
    final = manager.get("/v2/dispatches/" + dispatch.json()["dispatch_id"]).json()
    assert final["notifications"][0]["response"] == "can_perform"
    assert final["notifications"][0]["needs_followup"] is False
    assert final["external_transport_completed"] is False


def approved_flow(workflow, *, receiver=True):
    client, transport, config = workflow
    manager = new_manager(client)
    snapshot = seed(manager)
    result = calculate(manager, snapshot)
    approval = approve(manager, snapshot, result)
    assert approval.status_code == 201, approval.text
    allow(manager)
    targets = manager.get(f"/v2/plans/{snapshot['plan_id']}/dispatch-preview").json()["vehicle_changes"]
    recipient = None
    if receiver:
        recipient, _ = connect_recipient(manager, snapshot, [v["vehicle_id"] for v in targets])
        subscribe(recipient)
    body = {"approval_id": approval.json()["approval_id"], "expected_version": 2, "confirm_test_send": True}
    return manager, snapshot, recipient, body


def test_two_sessions_and_roles_cannot_cross_read_or_write_even_with_same_ids(workflow):
    client, _, _ = workflow
    a, b = new_manager(client), new_manager(client)
    snapshot = seed(a)
    assert b.get("/v2/scenarios/" + snapshot["scenario_id"]).status_code == 404
    assert b.get("/v2/plans/" + snapshot["plan_id"]).status_code == 404
    other = deepcopy(snapshot)
    other["jobs"][0]["evidence"]["source_ref"] = "fixture:other-session"
    assert b.post("/v2/scenarios", other).status_code == 201
    assert a.get("/v2/scenarios/" + snapshot["scenario_id"]).json() == snapshot
    assert b.get("/v2/scenarios/" + snapshot["scenario_id"]).json() == other
    allow(a)
    actor, _ = connect_recipient(a, snapshot, [snapshot["vehicles"][0]["vehicle_id"]])
    assert actor.get("/v2/session").status_code == 401
    assert actor.get("/v2/recipients").status_code == 401
    assert a.get("/v2/recipient/session").status_code == 401
    assert b.post("/v2/recipients/" + actor.info["recipient_id"] + "/revoke", {}).status_code == 404


def test_common_idempotency_keys_do_not_cross_sessions_and_conflicts_do_not_mutate(workflow):
    client, _, _ = workflow
    a, b = new_manager(client), new_manager(client)
    snapshot = a.get("/v2/examples/default").json()
    first = a.post("/v2/scenarios", snapshot, key="same-key")
    assert first.status_code == 201
    assert b.post("/v2/scenarios", snapshot, key="same-key").status_code == 201
    assert a.post("/v2/scenarios", snapshot, key="same-key").json() == first.json()
    changed = deepcopy(snapshot)
    changed["jobs"][0]["evidence"]["source_ref"] = "fixture:conflict"
    assert a.post("/v2/scenarios", changed, key="same-key").status_code == 409
    assert a.get("/v2/scenarios/" + snapshot["scenario_id"]).json() == snapshot


def test_origin_csrf_and_role_checks_do_not_leak_body_or_accept_manager_csrf_as_recipient(workflow):
    client, _, _ = workflow
    assert client.post("/v2/session", headers={"Origin": "https://evil.example", "Cookie": ""}).status_code == 403
    manager = new_manager(client)
    snapshot = manager.get("/v2/examples/default").json()
    bad = client.post("/v2/scenarios", json=snapshot, headers={"Origin": ORIGIN, "Cookie": manager.cookie,
                      "X-CSRF-Token": "wrong", "Idempotency-Key": "x"})
    assert bad.status_code == 403 and bad.json()["code"] == "CSRF_FAILED"
    assert client.post("/v2/session", headers={"Cookie": ""}).status_code == 403
    assert manager.post("/v2/scenarios", snapshot).status_code == 201
    allow(manager)
    receiver, _ = connect_recipient(manager, snapshot, [snapshot["vehicles"][0]["vehicle_id"]])
    bad = client.post("/v2/recipient/subscription", json={"subscription": subscription(), "consent": True,
        "notification_permission": "granted"}, headers={"Origin": ORIGIN, "Cookie": receiver.cookie,
        "X-CSRF-Token": manager.csrf, "Idempotency-Key": "not-recipient"})
    assert bad.status_code == 403


def test_public_visitors_cannot_invite_or_send_before_operator_authorization(workflow):
    client, _, _ = workflow
    manager = new_manager(client)
    snapshot = seed(manager)
    invitation = manager.post("/v2/invitations", {"plan_id": snapshot["plan_id"],
        "vehicle_ids": [snapshot["vehicles"][0]["vehicle_id"]], "consent_acknowledged": True})
    assert invitation.status_code == 403 and invitation.json()["code"] == "PUSH_TEST_NOT_AUTHORIZED"
    dispatch = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches", {
        "approval_id": "not-approved", "expected_version": 1, "confirm_test_send": True})
    assert dispatch.status_code == 403


def test_invitation_single_use_expiration_and_revocation(workflow):
    client, _, _ = workflow
    manager = new_manager(client)
    snapshot = seed(manager)
    allow(manager)
    invitation = manager.post("/v2/invitations", {"plan_id": snapshot["plan_id"],
        "vehicle_ids": [snapshot["vehicles"][0]["vehicle_id"]], "consent_acknowledged": True}).json()
    body = {"invitation_token": invitation["invitation_token"], "accept_test_invitation": True}
    headers = {"Origin": ORIGIN, "Cookie": "", "Idempotency-Key": "one-claim"}
    first = client.post("/v2/recipient/session", json=body, headers=headers)
    assert first.status_code == 201, first.text
    assert client.post("/v2/recipient/session", json=body, headers=headers).status_code == 200
    assert client.post("/v2/recipient/session", json=body, headers=headers | {"Idempotency-Key": "another-claim"}).status_code == 409
    rid = first.json()["recipient_id"]
    token = client.cookies.get(RECIPIENT_COOKIE)
    actor = Actor(client, RECIPIENT_COOKIE + "=" + token, first.json()["csrf_token"], first.json())
    subscribe(actor)
    assert manager.post("/v2/recipients/" + rid + "/revoke", {}).status_code == 200
    assert actor.get("/v2/recipient/session").status_code == 401
    domain = client.app.state.workflow.domain(manager.info["session_id"])
    with domain.db.connect() as conn:
        assert conn.execute("SELECT encrypted_json FROM push_subscriptions WHERE recipient_id=?", (rid,)).fetchone()[0] is None
        conn.execute("UPDATE invitations SET revoked=0,consumed_by=NULL,expires_at='2000-01-01T00:00:00Z'")
    expired = client.post("/v2/recipient/session", json=body, headers=headers)
    assert expired.status_code == 410 and expired.json()["code"] == "INVITATION_EXPIRED"


def test_revision_is_new_immutable_input_with_reason_and_comparison(workflow):
    client, _, _ = workflow
    manager = new_manager(client)
    before = seed(manager)
    previous = calculate(manager, before)
    after = deepcopy(before)
    after["jobs"][-1]["ready_at"] = before["as_of"]
    after["jobs"][-1]["evidence"]["source_ref"] = "fixture:confirmed-readiness"
    body = {"snapshot": after, "reason": "모의 상차 준비시각 확인", "confirmation": "confirmed_simulation"}
    revised = manager.post(f"/v2/scenarios/{before['scenario_id']}/revisions", body, key="revision")
    assert revised.status_code == 201, revised.text
    assert revised.json()["scenario_id"] != before["scenario_id"]
    assert manager.post(f"/v2/scenarios/{before['scenario_id']}/revisions", body, key="revision").json() == revised.json()
    assert manager.get("/v2/scenarios/" + before["scenario_id"]).json() == before
    assert approve(manager, before, previous).status_code == 409
    current = manager.get("/v2/scenarios/" + revised.json()["scenario_id"]).json()
    following = calculate(manager, current)
    compared = manager.get(f"/v2/revisions/{revised.json()['revision_id']}/comparison?before_run_id={previous['run_id']}&after_run_id={following['run_id']}&method=B1")
    assert compared.status_code == 200, compared.text
    assert compared.json()["comparison"]["delivery_authorized"] is False
    assert approve(manager, current, following).status_code == 201


@pytest.mark.parametrize("confirmation", ["assumed", "confirmed_simulation"])
def test_hypothetical_condition_or_assumed_readiness_cannot_be_approved(workflow, confirmation):
    client, _, _ = workflow
    manager = new_manager(client)
    before = seed(manager)
    after = deepcopy(before)
    after["jobs"][-1]["ready_at"] = before["as_of"]
    after["jobs"][-1]["evidence"].update(kind="assumed", source_ref="fixture:what-if")
    revised = manager.post(f"/v2/scenarios/{before['scenario_id']}/revisions", {
        "snapshot": after, "reason": "가정 시험", "confirmation": confirmation})
    assert revised.status_code == 201, revised.text
    stored = manager.get("/v2/scenarios/" + revised.json()["scenario_id"]).json()
    response = approve(manager, stored, calculate(manager, stored))
    assert response.status_code == 422 and response.json()["code"] == "ASSUMPTION_NOT_APPROVABLE"


def test_frozen_edits_and_incomplete_extra_vehicle_are_rejected(workflow):
    client, _, _ = workflow
    manager = new_manager(client)
    before = seed(manager)
    after = deepcopy(before)
    frozen = next(j for j in after["jobs"] if j["frozen"])
    frozen["ready_at"] = before["as_of"]
    frozen["evidence"]["source_ref"] = "fixture:changed-frozen"
    result = manager.post(f"/v2/scenarios/{before['scenario_id']}/revisions", {
        "snapshot": after, "reason": "금지 조건 변경 시험", "confirmation": "confirmed_simulation"})
    assert result.status_code == 422
    after = deepcopy(before)
    extra = deepcopy(after["vehicles"][-1])
    extra.update(vehicle_id="SYNTHETIC-EXTRA", available_at=None)
    after["vehicles"].append(extra)
    missing = manager.post(f"/v2/scenarios/{before['scenario_id']}/revisions", {
        "snapshot": after, "reason": "가용 미확인 차량", "confirmation": "confirmed_simulation"})
    assert missing.status_code == 422
    assert manager.get("/v2/scenarios/" + before["scenario_id"]).json() == before


def test_unknown_send_is_not_retried_or_confused_with_human_response(workflow):
    manager, snapshot, receiver, body = approved_flow(workflow)
    transport = workflow[1]
    transport.outcomes = [TimeoutError("SECRET-ENDPOINT-AND-KEY")]
    path = f"/v2/plans/{snapshot['plan_id']}/dispatches"
    first = manager.post(path, body, key="send-once")
    sent = wait_delivery(manager, first.json()["dispatch_id"])
    message = sent["notifications"][0]
    assert message["delivery_status"] == "unknown" and message["response"] == "none"
    assert "SECRET" not in json.dumps(sent)
    assert manager.post(path, body, key="send-once").json() == first.json()
    assert manager.post(path, body).status_code == 200
    assert len(transport.calls) == 1
    retry = manager.post(f"/v2/notifications/{message['notification_id']}/retry", {"confirm_test_send": True})
    assert retry.status_code == 409 and retry.json()["code"] == "DELIVERY_UNCERTAIN"
    response = receiver.post(f"/v2/recipient/notifications/{message['notification_id']}/responses", {
        "response": "cannot_perform", "note": "모의 수행 곤란"})
    assert response.status_code == 200 and response.json()["needs_followup"] is True
    domain = manager.client.app.state.workflow.domain(manager.info["session_id"])
    with domain.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM runs").fetchone()[0] == 1


def test_new_input_supersedes_old_notice_and_even_an_idempotent_response_retry(workflow):
    manager, snapshot, receiver, body = approved_flow(workflow)
    sent = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches", body)
    state = wait_delivery(manager, sent.json()["dispatch_id"])
    nid = state["notifications"][0]["notification_id"]
    assert receiver.post(f"/v2/recipient/notifications/{nid}/responses", {"response": "acknowledged"}, key="ack").status_code == 200
    next_input = deepcopy(snapshot)
    plan = manager.get("/v2/plans/" + snapshot["plan_id"]).json()
    next_input.update(scenario_id="S-NEW-AFTER-APPROVAL", base_plan_version=2,
                      baseline_assignments=plan["assignments"], baseline_unassigned_job_ids=plan["unassigned_job_ids"])
    assert manager.post("/v2/scenarios", next_input).status_code == 201
    stale = receiver.get(f"/v2/recipient/notifications/{nid}")
    assert stale.status_code == 200 and stale.json()["is_current"] is False and stale.json()["payload"] is None
    assert receiver.post(f"/v2/recipient/notifications/{nid}/responses", {"response": "acknowledged"}, key="ack").status_code == 409
    assert receiver.post(f"/v2/recipient/notifications/{nid}/opened", {}).status_code == 409


def test_expired_subscription_is_removed_and_only_explicit_retry_can_send_again(workflow):
    manager, snapshot, receiver, body = approved_flow(workflow)
    transport = workflow[1]
    transport.outcomes = [{"status": "expired", "error_code": "PUSH_SUBSCRIPTION_EXPIRED"}]
    sent = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches", body)
    state = wait_delivery(manager, sent.json()["dispatch_id"])
    nid = state["notifications"][0]["notification_id"]
    assert state["notifications"][0]["delivery_status"] == "expired"
    assert manager.post(f"/v2/notifications/{nid}/retry", {"confirm_test_send": True}).status_code == 422
    subscribe(receiver, subscription("replacement"))
    assert len(transport.calls) == 1
    retry = manager.post(f"/v2/notifications/{nid}/retry", {"confirm_test_send": True})
    assert retry.status_code == 202, retry.text
    final = wait_delivery(manager, sent.json()["dispatch_id"])
    assert final["notifications"][0]["delivery_status"] == "accepted"
    assert final["notifications"][0]["attempts"] == 2 and len(transport.calls) == 2


def test_unlinked_target_is_visible_and_requires_explicit_new_recipient_confirmation(workflow):
    manager, snapshot, _, body = approved_flow(workflow, receiver=False)
    sent = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches", body)
    state = wait_delivery(manager, sent.json()["dispatch_id"])
    assert state["notifications"] and all(n["delivery_status"] == "unlinked" for n in state["notifications"])
    message = state["notifications"][0]
    receiver, _ = connect_recipient(manager, snapshot, message["vehicle_ids"])
    subscribe(receiver)
    nid = message["notification_id"]
    assert manager.post(f"/v2/notifications/{nid}/retry", {"confirm_test_send": True}).status_code == 409
    retry = manager.post(f"/v2/notifications/{nid}/retry", {"confirm_test_send": True,
                                                             "recipient_id": receiver.info["recipient_id"]})
    assert retry.status_code == 202, retry.text
    final = wait_delivery(manager, sent.json()["dispatch_id"])
    assert any(n["delivery_status"] == "accepted" for n in final["notifications"])


def test_recipient_cannot_see_another_vehicle_or_response_to_another_recipient(workflow):
    manager, snapshot, _, body = approved_flow(workflow, receiver=False)
    preview = manager.get(f"/v2/plans/{snapshot['plan_id']}/dispatch-preview").json()
    vehicles = [v["vehicle_id"] for v in preview["vehicle_changes"]]
    a, _ = connect_recipient(manager, snapshot, vehicles[:1])
    b, _ = connect_recipient(manager, snapshot, vehicles[1:])
    subscribe(a, subscription("a"))
    subscribe(b, subscription("b"))
    sent = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches", body)
    wait_delivery(manager, sent.json()["dispatch_id"])
    am = a.get("/v2/recipient/notifications").json()["notifications"][0]
    bm = b.get("/v2/recipient/notifications").json()["notifications"][0]
    assert a.get("/v2/recipient/notifications/" + bm["notification_id"]).status_code == 404
    assert a.post(f"/v2/recipient/notifications/{bm['notification_id']}/responses", {"response": "can_perform"}).status_code == 404
    for vehicle in am["payload"]["vehicle_changes"]:
        assert vehicle["vehicle_id"] in a.info["vehicle_ids"]
        for change in vehicle["changes"]:
            for side in ("before", "after"):
                if change[side]:
                    assert change[side]["vehicle_id"] in a.info["vehicle_ids"]


def test_subscription_and_invitation_secrets_are_absent_from_raw_db_and_manager_json(workflow):
    client, _, _ = workflow
    manager = new_manager(client)
    snapshot = seed(manager)
    allow(manager)
    receiver, invitation = connect_recipient(manager, snapshot, [snapshot["vehicles"][0]["vehicle_id"]])
    value = subscription("ENCRYPTED-ONLY")
    subscribe(receiver, value)
    assert "ENCRYPTED-ONLY" not in manager.get("/v2/recipients").text
    domain = client.app.state.workflow.domain(manager.info["session_id"])
    with domain.db.connect() as conn:
        dump = "\n".join(conn.iterdump())
    for secret in (value["endpoint"], value["keys"]["auth"], value["keys"]["p256dh"], invitation["invitation_token"], receiver.cookie.split("=",1)[1]):
        assert secret not in dump


@pytest.mark.parametrize("data", [b'{"secret":"DO-NOT-ECHO","secret":1}', b'{"value":NaN}', b'{"value":Infinity}', b'{"value":1e9999}'])
def test_invalid_json_constants_and_duplicate_fields_are_rejected_without_echo(workflow, data):
    client, _, _ = workflow
    response = client.post("/v2/session", content=data, headers={"Origin": ORIGIN, "Content-Type": "application/json", "Cookie": ""})
    assert response.status_code == 422 and "DO-NOT-ECHO" not in response.text


def test_body_size_and_solver_budget_are_bounded(workflow):
    client, _, _ = workflow
    response = client.post("/v2/session", content=b"x" * (256 * 1024 + 1), headers={"Origin": ORIGIN})
    assert response.status_code == 413
    manager = new_manager(client)
    snapshot = seed(manager)
    request = {"scenario_id": snapshot["scenario_id"], "base_plan_version": 1, "methods": ["B1"],
               "time_limit_seconds": 11, "seed": 42}
    assert manager.post("/v2/runs", request).status_code == 422
    assert manager.post("/v2/runs", request | {"time_limit_seconds": 1, "seed": 2**64}).status_code == 422


def test_public_mode_requires_https_allowed_host_and_never_opens_legacy_shared_token(settings, tmp_path):
    config = replace(settings, workflow_enabled=True, public_enabled=True, run_mode="engine",
                     workflow_dir=tmp_path / "public", public_hosts=("demo.example",),
                     cors_origins=("https://demo.example",))
    with TestClient(create_app(config), base_url="https://demo.example", client=("203.0.113.20",40000)) as client:
        denied = client.get("/v1/plans/anything", headers={"Authorization":"Bearer " + settings.demo_token})
        assert denied.status_code == 404
        session = client.post("/v2/session", headers={"Origin":"https://demo.example"})
        assert session.status_code == 201, session.text
        cookie = session.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
        assert settings.demo_token not in session.text
        assert client.get("https://evil.example/health").status_code == 400
        assert client.get("http://demo.example/health").status_code == 400
        assert client.post("/v2/session", headers={"Origin":"https://evil.example"}).status_code == 403


def test_missing_push_settings_are_reported_without_queued_or_fake_success(workflow):
    manager, snapshot, _, body = approved_flow(workflow, receiver=False)
    workflow[1].configured = False
    failed = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches", body)
    assert failed.status_code == 503 and failed.json()["code"] == "PUSH_NOT_CONFIGURED"
    domain = manager.client.app.state.workflow.domain(manager.info["session_id"])
    with domain.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM dispatches").fetchone()[0] == 0


@pytest.mark.parametrize("consent", [False, 1, "true"])
def test_invitation_requires_explicit_boolean_consent(workflow, consent):
    client, _, _ = workflow
    manager = new_manager(client)
    snapshot = seed(manager)
    allow(manager)
    response = manager.post("/v2/invitations", {"plan_id":snapshot["plan_id"],
        "vehicle_ids":[snapshot["vehicles"][0]["vehicle_id"]], "consent_acknowledged":consent})
    assert response.status_code == 422


def test_restart_keeps_cookie_input_and_response_but_uncertain_send_is_not_replayed(settings, tmp_path):
    config = replace(settings, workflow_enabled=True, workflow_dir=tmp_path/"restart")
    first_sender = Transport()
    with TestClient(create_app(config,push_sender=first_sender),base_url=ORIGIN,client=("127.0.0.1",50000)) as client:
        manager,snapshot,receiver,body = approved_flow((client,first_sender,config))
        sent = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches",body)
        state = wait_delivery(manager,sent.json()["dispatch_id"])
        nid = state["notifications"][0]["notification_id"]
        receiver.post(f"/v2/recipient/notifications/{nid}/responses",{"response":"acknowledged"})
        domain = client.app.state.workflow.domain(manager.info["session_id"])
        with domain.db.transaction() as conn:
            conn.execute("UPDATE notifications SET delivery_status='sending' WHERE notification_id=?",(nid,))
            conn.execute("UPDATE notification_attempts SET finished_at=NULL,status='sending' WHERE notification_id=?",(nid,))
    second_sender = Transport()
    with TestClient(create_app(config,push_sender=second_sender),base_url=ORIGIN,client=("127.0.0.1",50000)) as client:
        manager.client = receiver.client = client
        restored = manager.get("/v2/session")
        assert restored.status_code == 200 and restored.json()["plans"][0]["plan_id"] == snapshot["plan_id"]
        state = manager.get("/v2/dispatches/"+sent.json()["dispatch_id"]).json()
        assert state["notifications"][0]["delivery_status"] == "unknown"
        assert state["notifications"][0]["response"] == "acknowledged"
        assert state["notifications"][0]["response_history"][0]["response"] == "acknowledged"
        assert second_sender.calls == []
        assert receiver.get("/v2/recipient/session").status_code == 200


def test_expiry_blocks_roles_wipes_push_secrets_and_retention_removes_only_own_database(workflow):
    client, _, config = workflow
    manager = new_manager(client)
    snapshot = seed(manager)
    allow(manager)
    receiver,_ = connect_recipient(manager,snapshot,[snapshot["vehicles"][0]["vehicle_id"]])
    subscribe(receiver)
    hub = client.app.state.workflow
    domain = hub.domain(manager.info["session_id"])
    with hub.registry.transaction() as conn:
        conn.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00Z' WHERE session_id=?",(manager.info["session_id"],))
    assert manager.get("/v2/session").status_code == 410
    assert receiver.get("/v2/recipient/session").status_code == 410
    sentinel = config.workflow_dir/"sessions"/"preserve-user-file.txt"
    sentinel.write_text("preserve",encoding="utf-8")
    hub.cleanup()
    assert not domain.db.path.exists()
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    with hub.registry.connect() as conn:
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM endpoint_owners").fetchone()[0] == 0


def test_queue_and_active_session_limits_are_global_and_do_not_admit_extra_work(settings,tmp_path):
    import threading
    from backend.engine import solve
    class Blocking:
        result_origin = "computed"
        def __init__(self):
            self.release = threading.Event()
        def check(self,snapshot,methods):
            pass
        def replay(self,snapshot,methods,config):
            assert self.release.wait(5)
            return [solve(snapshot,method,config) for method in methods]
    replay = Blocking()
    config = replace(settings,workflow_enabled=True,workflow_dir=tmp_path/"queue")
    with TestClient(create_app(config,workflow_replay=replay),base_url=ORIGIN,client=("127.0.0.1",50000)) as client:
        try:
            actors = [new_manager(client) for _ in range(5)]
            snapshots = [seed(actor) for actor in actors]
            body = lambda snap:{"scenario_id":snap["scenario_id"],"base_plan_version":1,"methods":["B1"],"time_limit_seconds":1,"seed":42}
            assert actors[0].post("/v2/runs",body(snapshots[0])).status_code == 202
            assert actors[0].post("/v2/runs",body(snapshots[0])).status_code == 429
            for actor,snap in zip(actors[1:4],snapshots[1:4]):
                assert actor.post("/v2/runs",body(snap)).status_code == 202
            assert actors[4].post("/v2/runs",body(snapshots[4])).status_code == 429
            assert len(client.app.state.workflow.pending) == 4
        finally:
            replay.release.set()


def test_server_owner_cli_authorizes_only_an_active_named_session(workflow):
    from tools.workflow_admin import authorize
    client, _, config = workflow
    manager = new_manager(client)
    assert manager.get("/v2/session").json()["push_test_authorized"] is False
    authorize(config.workflow_dir,manager.info["session_id"],consent_note="팀원 역할 시험 동의 확인")
    assert manager.get("/v2/session").json()["push_test_authorized"] is True
    authorize(config.workflow_dir,manager.info["session_id"],consent_note="시험 종료",revoke=True)
    assert manager.get("/v2/session").json()["push_test_authorized"] is False


def test_generic_registration_cannot_bypass_condition_audit_or_unfreeze_a_saved_job(workflow):
    client, _, _ = workflow
    manager = new_manager(client)
    snapshot = seed(manager)
    altered = deepcopy(snapshot)
    altered["scenario_id"] = "S-UNTRACKED-EDIT"
    job = next(j for j in altered["jobs"] if j["frozen"])
    job.update(frozen=False,state="planned",freeze_reason=None)
    response = manager.post("/v2/scenarios",altered)
    assert response.status_code in (409,422)
    assert manager.get("/v2/scenarios/"+snapshot["scenario_id"]).json() == snapshot


def test_next_input_reuses_approved_baseline_without_extending_policy_or_losing_origin(workflow):
    manager,snapshot,_,_ = approved_flow(workflow,receiver=False)
    proposal = manager.get(f"/v2/plans/{snapshot['plan_id']}/next-input")
    assert proposal.status_code == 200,proposal.text
    rebased = proposal.json()
    plan = manager.get("/v2/plans/"+snapshot["plan_id"]).json()
    assert rebased["baseline_assignments"] == plan["assignments"]
    assert rebased["base_plan_version"] == 2 and rebased["policy"] == snapshot["policy"]
    assert rebased["jobs"] == snapshot["jobs"]
    assert manager.post("/v2/scenarios",rebased).status_code == 201
    changed = deepcopy(rebased)
    changed["scenario_id"] = "S-UNTRACKED-POLICY"
    changed["policy"]["input_valid_until"] = "2099-01-01T00:00:00Z"
    assert manager.post("/v2/scenarios",changed).status_code == 422
    domain = manager.client.app.state.workflow.domain(manager.info["session_id"])
    with domain.db.connect() as conn:
        origin = conn.execute("SELECT * FROM input_rebases WHERE scenario_id=?",(rebased["scenario_id"],)).fetchone()
        assert origin["source_scenario_id"] == snapshot["scenario_id"]


def test_multiple_vehicle_notices_of_same_current_dispatch_remain_respondable(workflow):
    manager,snapshot,_,body = approved_flow(workflow,receiver=False)
    sent = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches",body)
    state = wait_delivery(manager,sent.json()["dispatch_id"])
    vehicles = [v for n in state["notifications"] for v in n["vehicle_ids"]]
    receiver,_ = connect_recipient(manager,snapshot,vehicles)
    subscribe(receiver)
    for message in state["notifications"]:
        response = manager.post(f"/v2/notifications/{message['notification_id']}/retry",{
            "confirm_test_send":True,"recipient_id":receiver.info["recipient_id"]})
        assert response.status_code == 202,response.text
        wait_delivery(manager,sent.json()["dispatch_id"])
    messages = receiver.get("/v2/recipient/notifications").json()["notifications"]
    assert len(messages) >= 2 and all(m["is_current"] for m in messages)
    for message in messages:
        response = receiver.post(f"/v2/recipient/notifications/{message['notification_id']}/responses",{"response":"can_perform"})
        assert response.status_code == 200,response.text


def test_provider_rate_limit_is_preserved_and_manual_retry_waits_for_retry_after(workflow):
    manager,snapshot,_,body = approved_flow(workflow)
    transport = workflow[1]
    transport.outcomes = [{"status":"failed","error_code":"PUSH_RATE_LIMITED","retry_after_seconds":120}]
    sent = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches",body)
    message = wait_delivery(manager,sent.json()["dispatch_id"])["notifications"][0]
    assert message["retry_not_before"] is not None
    failed = manager.post(f"/v2/notifications/{message['notification_id']}/retry",{"confirm_test_send":True})
    assert failed.status_code == 429 and 1 <= int(failed.headers["Retry-After"]) <= 120
    assert len(transport.calls) == 1


def test_concurrent_same_revision_is_registered_once_and_replays_same_input_id(workflow):
    from concurrent.futures import ThreadPoolExecutor
    client, _, _ = workflow
    manager = new_manager(client)
    before = seed(manager)
    after = deepcopy(before)
    after["jobs"][-1]["ready_at"] = before["as_of"]
    body = {"snapshot":after,"reason":"모의 준비 확인","confirmation":"confirmed_simulation"}
    def submit():
        return manager.post(f"/v2/scenarios/{before['scenario_id']}/revisions",body,key="concurrent-revision")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:submit(),range(2)))
    assert [r.status_code for r in results] == [201,201]
    assert results[0].json() == results[1].json()
    domain = client.app.state.workflow.domain(manager.info["session_id"])
    with domain.db.connect() as conn:
        assert conn.execute("SELECT count(*) FROM condition_revisions").fetchone()[0] == 1


def test_late_expiration_of_old_subscription_cannot_revoke_a_replacement(workflow):
    import threading
    manager,snapshot,receiver,body = approved_flow(workflow)
    transport = workflow[1]
    entered,release = threading.Event(),threading.Event()
    def send(subscription,payload):
        entered.set()
        assert release.wait(5)
        return {"status":"expired","error_code":"PUSH_SUBSCRIPTION_EXPIRED"}
    transport.send = send
    sent = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches",body)
    try:
        assert entered.wait(2)
        subscribe(receiver,subscription("replacement-during-send"))
    finally:
        release.set()
    wait_delivery(manager,sent.json()["dispatch_id"])
    assert receiver.get("/v2/recipient/session").json()["subscription_status"] == "active"
    hub = manager.client.app.state.workflow
    with hub.registry.connect() as conn:
        assert conn.execute("SELECT count(*) FROM endpoint_owners WHERE recipient_id=?",(receiver.info["recipient_id"],)).fetchone()[0] == 1


def test_partial_session_provisioning_is_not_authenticated_and_is_cleaned_after_restart(settings,tmp_path):
    config = replace(settings,workflow_enabled=True,workflow_dir=tmp_path/"provision")
    orphan = "f"*32
    with TestClient(create_app(config),base_url=ORIGIN,client=("127.0.0.1",50000)) as client:
        manager = new_manager(client)
        snapshot = seed(manager)
        hub = client.app.state.workflow
        with hub.registry.transaction() as conn:
            conn.execute("INSERT INTO sessions(session_id,token_hash,created_at,expires_at,ready) VALUES(?,?,?,?,0)",
                         (orphan,"0"*64,hub.now(),manager.info["expires_at"]))
        partial = config.workflow_dir/"sessions"/(orphan+".sqlite3")
        partial.write_bytes(b"interrupted-provisioning-not-a-database")
        with pytest.raises(ApiError) as error:
            hub.session(orphan)
        assert error.value.code == "SESSION_REQUIRED"
    with TestClient(create_app(config),base_url=ORIGIN,client=("127.0.0.1",50000)) as client:
        manager.client = client
        assert manager.get("/v2/scenarios/"+snapshot["scenario_id"]).status_code == 200
        assert not partial.exists()
        with client.app.state.workflow.registry.connect() as conn:
            assert not conn.execute("SELECT 1 FROM sessions WHERE session_id=?",(orphan,)).fetchone()


def test_dispatch_checks_stored_run_hash_rather_than_inventing_a_matching_hash(workflow):
    manager,snapshot,_,body = approved_flow(workflow,receiver=False)
    domain = manager.client.app.state.workflow.domain(manager.info["session_id"])
    # Simulate a damaged offline backup, not a mutation allowed by the API/DB.
    # Normal connections keep the FK and immutable-identity trigger enabled.
    with domain.db.connect() as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DROP TRIGGER runs_keep_input_identity")
        conn.execute("UPDATE runs SET input_sha256=?",("f"*64,))
    preview = manager.get(f"/v2/plans/{snapshot['plan_id']}/dispatch-preview")
    assert preview.status_code == 422 and preview.json()["code"] == "APPROVAL_INTEGRITY_FAILED"
    sent = manager.post(f"/v2/plans/{snapshot['plan_id']}/dispatches",body)
    assert sent.status_code == 422 and workflow[1].calls == []
