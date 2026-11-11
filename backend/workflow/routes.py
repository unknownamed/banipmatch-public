"""v0.2 HTTP surface; dispatcher and recipient cookies are separate capabilities."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import secrets
from typing import Literal
from uuid import uuid4

from fastapi import Body, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.api.contracts import ApiError, DRAFT, validate
from .hub import Hub, moment
from .security import csrf, hashed
from .contracts import (SessionState, RecipientState, InvitationState, RevisionState,
                        RevisionRecord, ComparisonState, DispatchReceipt, RetryReceipt,
                        DispatchState, NotificationState, NotificationInbox, RecipientsState,
                        PushConfig, SubscriptionState)

MANAGER_COOKIE = "banipmatch_session"
RECIPIENT_COOKIE = "banipmatch_recipient"


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if isinstance(value, dict):
            for name in ("consent", "consent_acknowledged", "accept_test_invitation", "confirm_test_send"):
                if name in value and value[name] is not True:
                    raise ValueError("explicit boolean consent required")
        return value


class Revision(Input):
    snapshot: dict
    reason: str = Field(min_length=1, max_length=1000)
    confirmation: Literal["confirmed_simulation", "assumed"]


class Invitation(Input):
    plan_id: str = Field(min_length=1, max_length=64)
    vehicle_ids: list[str] = Field(min_length=1, max_length=10)
    consent_acknowledged: Literal[True]


class Claim(Input):
    invitation_token: str = Field(min_length=100, max_length=200)
    accept_test_invitation: Literal[True]


class Subscription(Input):
    subscription: dict
    notification_permission: Literal["granted"]
    consent: Literal[True]


class Dispatch(Input):
    approval_id: str = Field(min_length=1, max_length=64)
    expected_version: int = Field(ge=1, le=2**31)
    confirm_test_send: Literal[True]


class Retry(Input):
    confirm_test_send: Literal[True]
    recipient_id: str | None = Field(default=None, max_length=32)


class RecipientResponse(Input):
    response: Literal["acknowledged", "can_perform", "cannot_perform"]
    note: str = Field(default="", max_length=300)


class Empty(Input):
    pass


def key(request):
    value = request.headers.get("idempotency-key", "")
    if not 1 <= len(value) <= 128 or not value.isascii() or not value.strip():
        raise ApiError(422, "IDEMPOTENCY_KEY_REQUIRED", "1~128자 ASCII Idempotency-Key가 필요함")
    return value


def check_csrf(request, token):
    value = request.headers.get("x-csrf-token", "")
    if not value.isascii() or not secrets.compare_digest(csrf(token), value):
        raise ApiError(403, "CSRF_FAILED", "현재 역할 세션의 쓰기 확인 값이 필요함")


def install(app, settings, *, replay=None, sender=None, clock=None):
    hub = Hub(settings, replay=replay, sender=sender, clock=clock)
    app.state.workflow = hub

    def manager(request: Request, *, write=False):
        cookie = request.cookies.get(MANAGER_COOKIE, "")
        row = hub.authenticate(cookie)
        hub.rate("manager:" + row["session_id"], limit=180)
        if write:
            check_csrf(request, cookie)
            key(request)
            hub.rate("manager-write:" + row["session_id"], limit=40)
        return hub.domain(row["session_id"]), row

    def recipient(request: Request, *, write=False):
        cookie = request.cookies.get(RECIPIENT_COOKIE, "")
        sid, identifier = hub.secrets.verify(cookie, "recipient")
        hub.session(sid)
        domain = hub.domain(sid)
        with domain.db.connect() as conn:
            info = domain.recipient(conn, identifier)
        hub.rate("recipient:" + sid + ":" + identifier, limit=120)
        if write:
            check_csrf(request, cookie)
            key(request)
            hub.rate("recipient-write:" + sid + ":" + identifier, limit=20)
        return domain, info, cookie

    def cookie_response(data, cookie_name, token, path, expires, status=200):
        response = JSONResponse(data, status_code=status)
        response.set_cookie(cookie_name, token, httponly=True, secure=settings.public_enabled,
                            samesite="strict", path=path,
                            max_age=max(0, int((moment(expires) - hub.clock()).total_seconds())))
        return response

    @app.post("/v2/session", response_model=SessionState, status_code=201)
    def create_session(request: Request):
        address = request.client.host if request.client else "unknown"
        token, response = hub.create_session(request.cookies.get(MANAGER_COOKIE), hashed(address))
        return cookie_response(response, MANAGER_COOKIE, token, "/v2", response["expires_at"], 201)

    @app.get("/v2/session", response_model=SessionState)
    def get_session(request: Request):
        _, row = manager(request)
        return hub.session_response(request.cookies[MANAGER_COOKIE], row)

    @app.delete("/v2/session")
    def delete_session(request: Request):
        _, row = manager(request, write=True)
        hub.expire(row["session_id"])
        response = JSONResponse({"expired": True})
        response.delete_cookie(MANAGER_COOKIE, path="/v2", secure=settings.public_enabled, httponly=True, samesite="strict")
        return response

    @app.get("/v2/examples/default")
    def example(request: Request):
        manager(request)
        import json
        from tools.demo_engine_api import prepare_snapshot
        source = json.loads((DRAFT / "예제 데이터" / "01_snapshot.json").read_text(encoding="utf-8"))
        return prepare_snapshot(source, hub.clock().replace(second=0, microsecond=0), uuid4().hex[:12])

    @app.post("/v2/scenarios")
    def register(request: Request, body: dict = Body(...)):
        domain, _ = manager(request, write=True)
        with hub.lock:
            status, result = domain.register(body, key(request))
        return JSONResponse(result, status_code=status)

    @app.get("/v2/scenarios/{scenario_id}")
    def snapshot(scenario_id: str, request: Request):
        domain, _ = manager(request)
        return domain.store.get_snapshot(scenario_id)

    @app.post("/v2/scenarios/{scenario_id}/revisions", response_model=RevisionState, status_code=201)
    def revise(scenario_id: str, request: Request, body: Revision):
        domain, _ = manager(request, write=True)
        status, result = domain.revise(scenario_id, body.model_dump(), key(request))
        return JSONResponse(result, status_code=status)

    @app.post("/v2/runs")
    def run(request: Request, body: dict = Body(...)):
        domain, _ = manager(request, write=True)
        validate("RunRequest", body)
        if body["time_limit_seconds"] > 10 or not 0 <= body["seed"] <= 2**31 - 1:
            raise ApiError(422, "RUN_LIMIT_EXCEEDED", "방법별 예산은10초, seed는0~2^31-1 범위만 허용")
        status, response = hub.enqueue_run(domain, body, key(request))
        return JSONResponse(response, status_code=status)

    @app.get("/v2/runs/{run_id}")
    def get_run(run_id: str, request: Request):
        domain, _ = manager(request)
        return domain.store.get_run(run_id)

    @app.get("/v2/runs/{run_id}/results")
    def results(run_id: str, request: Request):
        domain, _ = manager(request)
        status, value = domain.store.get_results(run_id)
        return JSONResponse(value, status_code=status, headers={"Retry-After": "2"} if status == 202 else None)

    @app.get("/v2/revisions/{revision_id}/comparison", response_model=ComparisonState)
    def compare(revision_id: str, request: Request, after_run_id: str,
                method: Literal["B1", "B2", "B3"] = "B1", before_run_id: str | None = None):
        domain, _ = manager(request)
        return domain.comparison(revision_id, before_run_id, after_run_id, method)

    @app.get("/v2/revisions/{revision_id}", response_model=RevisionRecord)
    def get_revision(revision_id: str, request: Request):
        import json
        domain, _ = manager(request)
        with domain.db.connect() as conn:
            row = conn.execute("SELECT * FROM condition_revisions WHERE revision_id=?", (revision_id,)).fetchone()
        if not row:
            raise ApiError(404, "NOT_FOUND", "조건 수정 기록을 찾을 수 없음")
        return {key: row[key] for key in ("revision_id", "before_scenario_id", "after_scenario_id", "confirmation", "reason", "created_at")} | {
            "revision": json.loads(row["revision_json"])}

    @app.get("/v2/plans/{plan_id}")
    def plan(plan_id: str, request: Request):
        domain, _ = manager(request)
        return domain.store.get_plan(plan_id)

    @app.get("/v2/plans/{plan_id}/next-input")
    def next_input(plan_id: str, request: Request):
        domain, _ = manager(request)
        return domain.next_input(plan_id)

    @app.post("/v2/plans/{plan_id}/approvals")
    def approve(plan_id: str, request: Request, body: dict = Body(...)):
        domain, _ = manager(request, write=True)
        validate("ApprovalRequest", body)
        with hub.lock:
            status, value = domain.store.approve(plan_id, body, key(request), before_approve=domain.approval_guard)
        return JSONResponse(value, status_code=status)

    @app.get("/v2/plans/{plan_id}/dispatch-preview")
    def preview(plan_id: str, request: Request):
        domain, _ = manager(request)
        return domain.preview(plan_id)

    @app.post("/v2/invitations", response_model=InvitationState, status_code=201)
    def invitation(request: Request, body: Invitation):
        domain, _ = manager(request, write=True)
        status, response = domain.invite(body.model_dump(), key(request))
        return JSONResponse(response, status_code=status)

    @app.get("/v2/recipients", response_model=RecipientsState)
    def recipients(request: Request):
        domain, _ = manager(request)
        return domain.recipients()

    @app.post("/v2/recipients/{recipient_id}/revoke")
    def revoke(recipient_id: str, request: Request, body: Empty):
        domain, _ = manager(request, write=True)
        return domain.revoke(recipient_id)

    @app.post("/v2/plans/{plan_id}/dispatches", response_model=DispatchReceipt, status_code=202)
    def dispatch(plan_id: str, request: Request, body: Dispatch):
        domain, _ = manager(request, write=True)
        status, response = domain.dispatch(plan_id, body.model_dump(), key(request))
        return JSONResponse(response, status_code=status)

    @app.get("/v2/dispatches/{dispatch_id}", response_model=DispatchState)
    def get_dispatch(dispatch_id: str, request: Request):
        domain, _ = manager(request)
        return domain.get_dispatch(dispatch_id)

    @app.post("/v2/notifications/{notification_id}/retry", response_model=RetryReceipt, status_code=202)
    def retry(notification_id: str, request: Request, body: Retry):
        domain, _ = manager(request, write=True)
        status, response = domain.retry(notification_id, body.model_dump(), key(request))
        return JSONResponse(response, status_code=status)

    @app.post("/v2/recipient/session", response_model=RecipientState, status_code=201)
    def claim(request: Request, body: Claim):
        sid, identifier = hub.secrets.verify(body.invitation_token, "invite")
        hub.session(sid)
        domain = hub.domain(sid)
        hub.rate("claim:" + sid, limit=10)
        status, info = domain.claim(identifier, key(request))
        token = hub.secrets.token("recipient", sid, info["recipient_id"])
        return cookie_response(info | {"csrf_token": csrf(token)}, RECIPIENT_COOKIE, token,
                               "/v2/recipient", info["expires_at"], status)

    @app.get("/v2/recipient/session", response_model=RecipientState)
    def recipient_session(request: Request):
        _, info, token = recipient(request)
        return info | {"csrf_token": csrf(token)}

    @app.delete("/v2/recipient/session")
    def recipient_exit(request: Request):
        domain, info, _ = recipient(request, write=True)
        domain.revoke(info["recipient_id"])
        response = JSONResponse({"revoked": True})
        response.delete_cookie(RECIPIENT_COOKIE, path="/v2/recipient", secure=settings.public_enabled, httponly=True, samesite="strict")
        return response

    @app.get("/v2/recipient/push-config", response_model=PushConfig)
    def push_config(request: Request):
        recipient(request)
        return {"configured": hub.sender.configured, "application_server_key": hub.sender.application_server_key}

    @app.post("/v2/recipient/subscription", response_model=SubscriptionState, status_code=201)
    def subscription(request: Request, body: Subscription):
        domain, info, _ = recipient(request, write=True)
        status, value = domain.subscribe(info["recipient_id"], body.subscription, key(request))
        return JSONResponse(value, status_code=status)

    @app.delete("/v2/recipient/subscription")
    def unsubscribe(request: Request):
        domain, info, _ = recipient(request, write=True)
        return domain.unsubscribe(info["recipient_id"])

    @app.get("/v2/recipient/notifications", response_model=NotificationInbox)
    def inbox(request: Request):
        domain, info, _ = recipient(request)
        return domain.recipient_notifications(info["recipient_id"])

    @app.get("/v2/recipient/notifications/{notification_id}", response_model=NotificationState)
    def notification(notification_id: str, request: Request):
        domain, info, _ = recipient(request)
        return domain.recipient_notifications(info["recipient_id"], notification_id)

    @app.post("/v2/recipient/notifications/{notification_id}/opened", response_model=NotificationState)
    def opened(notification_id: str, request: Request, body: Empty):
        domain, info, _ = recipient(request, write=True)
        status, value = domain.respond(info["recipient_id"], notification_id, {}, key(request), opened=True)
        return JSONResponse(value, status_code=status)

    @app.post("/v2/recipient/notifications/{notification_id}/responses", response_model=NotificationState)
    def respond(notification_id: str, request: Request, body: RecipientResponse):
        domain, info, _ = recipient(request, write=True)
        status, value = domain.respond(info["recipient_id"], notification_id, body.model_dump(), key(request))
        return JSONResponse(value, status_code=status)

    return hub
