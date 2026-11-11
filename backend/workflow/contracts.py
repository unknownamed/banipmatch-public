"""Additional v0.2 response contracts. v0.1 domain objects are reused unchanged."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SessionPlan(Output):
    plan_id: str
    version: int
    scenario_id: str
    latest_run_id: str | None
    latest_revision_id: str | None


class SessionState(Output):
    session_id: str
    expires_at: str
    csrf_token: str
    push_test_authorized: bool
    data_mode: Literal["simulated"]
    plans: list[SessionPlan]
    limits: dict[str, int]


class RecipientState(Output):
    recipient_id: str
    vehicle_ids: list[str]
    expires_at: str
    csrf_token: str
    subscription_status: Literal["active", "revoked", "expired", "missing"]
    data_mode: Literal["simulated"]


class InvitationState(Output):
    invitation_id: str
    invitation_token: str = Field(description="일회 초대 비밀. URL query/로그/storage로 전달하지 않음")
    expires_at: str


class RevisionState(Output):
    scenario_id: str
    plan_id: str
    base_plan_version: int
    input_sha256: str
    revision_id: str
    confirmation: Literal["confirmed_simulation", "assumed"]


class RevisionRecord(Output):
    revision_id: str
    before_scenario_id: str
    after_scenario_id: str
    confirmation: Literal["confirmed_simulation", "assumed"]
    reason: str
    created_at: str
    revision: dict


class ComparisonState(Output):
    revision_id: str
    confirmation: Literal["confirmed_simulation", "assumed"]
    comparison: dict


class DispatchReceipt(Output):
    dispatch_id: str


class RetryReceipt(DispatchReceipt):
    notification_id: str


class ResponseEvent(Output):
    response: Literal["acknowledged", "can_perform", "cannot_perform"]
    note: str
    created_at: str


class RecipientPayload(Output):
    data_mode: Literal["simulated"]
    stage: Literal["approved_simulation_change"]
    plan_id: str
    plan_version: int
    approval_id: str
    scenario_id: str
    run_id: str
    vehicle_changes: list[dict]
    transport_completion: Literal["not_claimed"]
    external_booking_changed: Literal[False]


class NotificationState(Output):
    notification_id: str
    dispatch_id: str
    recipient_id: str | None
    delivery_status: Literal["pending", "sending", "accepted", "failed", "unknown", "expired", "unsubscribed", "unlinked", "superseded"]
    error_code: str | None
    attempts: int
    created_at: str
    accepted_at: str | None
    opened_at: str | None
    retry_not_before: str | None
    response: Literal["none", "acknowledged", "can_perform", "cannot_perform"]
    responded_at: str | None
    is_current: bool
    vehicle_ids: list[str]
    payload: RecipientPayload | None
    response_history: list[ResponseEvent]
    needs_followup: bool


class NotificationInbox(Output):
    notifications: list[NotificationState]


class DispatchState(Output):
    dispatch_id: str
    approval_id: str
    plan_id: str
    plan_version: int
    scenario_id: str
    is_current: bool
    notifications: list[NotificationState]
    followups: list[dict]
    external_transport_completed: Literal[False]


class RecipientSummary(Output):
    recipient_id: str
    plan_id: str
    expires_at: str
    revoked: bool
    vehicle_ids: list[str]
    subscription_status: Literal["active", "revoked", "expired", "missing"]


class RecipientsState(Output):
    recipients: list[RecipientSummary]


class SubscriptionState(Output):
    subscription_status: Literal["active"]
    expires_at: str


class PushConfig(Output):
    configured: bool
    application_server_key: str | None
