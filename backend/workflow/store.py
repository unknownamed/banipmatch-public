"""Version-bound revisions, invitations, notifications and explicit human responses."""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import json
import math

from backend.api.contracts import ApiError, canonical, digest, validate
from backend.engine.recalculation import RecalculationError, compare_recalculation, validate_condition_revision
from tools.dispatch_response import bind_archived_approval
from .hub import moment, stamp
from .security import hashed, new_id, validate_snapshot_bounds, validate_subscription


class WorkflowStore:
    def __init__(self, hub, sid, store, jobs):
        self.hub, self.sid, self.store, self.jobs = hub, sid, store, jobs
        self.db = store.db

    def recover(self):
        with self.db.transaction() as conn:
            conn.execute("UPDATE notifications SET delivery_status='unknown',error_code='SERVER_RESTART_DURING_SEND' "
                         "WHERE delivery_status='sending'")
            conn.execute("UPDATE notifications SET delivery_status='failed',error_code='SERVER_RESTART_BEFORE_SEND' "
                         "WHERE delivery_status='pending'")
            conn.execute("UPDATE notification_attempts SET status='unknown',error_code='SERVER_RESTART_DURING_SEND',"
                         "finished_at=? WHERE finished_at IS NULL", (self.hub.now(),))

    def revoke_all(self):
        with self.db.transaction() as conn:
            conn.execute("UPDATE invitations SET revoked=1")
            conn.execute("UPDATE recipients SET revoked=1")
            conn.execute("DELETE FROM recipient_vehicles")
            conn.execute("DELETE FROM recipient_locations")
            conn.execute("UPDATE push_subscriptions SET encrypted_json=NULL,endpoint_fingerprint=NULL,status='revoked'")
            conn.execute("UPDATE notifications SET delivery_status='superseded',error_code='SESSION_EXPIRED' "
                         "WHERE delivery_status='pending'")

    def cached_operation(self, route, key, body):
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM idempotency_records WHERE actor_id=? AND route=? AND idempotency_key=?",
                               (self.store.actor_id, route, key)).fetchone()
        if row:
            if row["request_sha256"] != digest(body):
                raise ApiError(409, "IDEMPOTENCY_CONFLICT", "같은 멱등키에 다른 요청을 사용할 수 없음")
            return row["response_status"], json.loads(row["response_json"])
        return None

    def register(self, snapshot, key):
        validate_snapshot_bounds(snapshot)
        previous = self.cached_operation("POST /v2/scenarios", key, snapshot)
        if previous:
            return previous
        rebase = None
        with self.db.connect() as conn:
            head = conn.execute("SELECT * FROM plan_heads WHERE plan_id=?", (snapshot["plan_id"],)).fetchone()
            if head:
                expected = self.next_input_in(conn, snapshot["plan_id"], snapshot["scenario_id"])
                if snapshot != expected:
                    raise ApiError(422, "CONDITION_REVISION_REQUIRED", "기존 계획은 승인 원안 재기준화 또는 이유를 기록한 조건 수정 경로를 사용해야 함")
                plan = self.store.get_plan(snapshot["plan_id"])
                rebase = (plan["scenario_id"], head["active_scenario_id"], head["current_version"])
        def cap(conn):
            # 세션당 입력 보관 상한. 리허설·시연을 반복해도 막히지 않게 넉넉히 두고(디스크 여유 충분), 계산 동시성·요청 속도는 별도 제한한다.
            if conn.execute("SELECT count(*) FROM scenarios").fetchone()[0] > 100:
                raise ApiError(429, "SCENARIO_LIMIT", "세션 입력 보관 상한에 도달함")
            if rebase:
                conn.execute("INSERT INTO input_rebases VALUES(?,?,?,?,?)",
                             (snapshot["scenario_id"], *rebase, self.hub.now()))
            return {}
        return self.store.register(snapshot, key, on_registered=cap, route="POST /v2/scenarios")

    def next_input_in(self, conn, plan_id, scenario_id=None):
        head = self.store.head(conn, plan_id)
        plan = json.loads(conn.execute("SELECT plan_json FROM plans WHERE plan_id=? AND version=?",
                                      (plan_id, head["current_version"])).fetchone()[0])
        if not plan["approval_id"]:
            raise ApiError(409, "CONDITION_REVISION_REQUIRED", "아직 확정 전인 입력은 조건 수정 경로로 보완해야 함")
        snapshot = self.store.snapshot(conn, plan["scenario_id"])
        snapshot.update(scenario_id=scenario_id or new_id("S-"), base_plan_version=plan["version"],
                        baseline_assignments=plan["assignments"], baseline_unassigned_job_ids=plan["unassigned_job_ids"])
        return snapshot

    def next_input(self, plan_id):
        with self.db.connect() as conn:
            return self.next_input_in(conn, plan_id)

    def revise(self, scenario_id, body, key):
        route = f"POST /v2/scenarios/{scenario_id}/revisions"
        previous = self.cached_operation(route, key, body)
        if previous:
            return previous
        before = self.store.get_snapshot(scenario_id)
        after = deepcopy(body["snapshot"])
        after["scenario_id"] = new_id("S-")
        validate_snapshot_bounds(after)
        try:
            revision = validate_condition_revision(before, after, reason=body["reason"])
        except RecalculationError as error:
            raise ApiError(422, "CONDITION_REVISION_INVALID", str(error)) from None
        revision_id = new_id("V-")
        def record(conn):
            # 세션당 입력 보관 상한. 리허설·시연을 반복해도 막히지 않게 넉넉히 두고(디스크 여유 충분), 계산 동시성·요청 속도는 별도 제한한다.
            if conn.execute("SELECT count(*) FROM scenarios").fetchone()[0] > 100:
                raise ApiError(429, "SCENARIO_LIMIT", "세션 입력 보관 상한에 도달함")
            head = self.store.head(conn, before["plan_id"])
            # register() has already atomically advanced the active input to after.
            if head["current_version"] != before["base_plan_version"]:
                raise ApiError(409, "PLAN_VERSION_CONFLICT", "기준 계획이 변경됨")
            conn.execute("INSERT INTO condition_revisions VALUES(?,?,?,?,?,?,?)", (
                revision_id, scenario_id, after["scenario_id"], body["confirmation"],
                body["reason"], canonical(revision), self.hub.now()))
            return {"revision_id": revision_id, "confirmation": body["confirmation"]}
        # Current source check and registration execute under the Hub's write lock;
        # immutable data+revision audit are committed in one domain DB transaction.
        with self.hub.lock:
            previous = self.cached_operation(route, key, body)
            if previous:
                return previous
            with self.db.connect() as conn:
                head = self.store.head(conn, before["plan_id"])
                if head["active_scenario_id"] != scenario_id or head["current_version"] != before["base_plan_version"]:
                    raise ApiError(409, "PLAN_VERSION_CONFLICT", "현재 입력과 계획으로 조건을 다시 확인해야 함")
            return self.store.register(after, key, on_registered=record, route=route, idempotency_body=body)

    def comparison(self, revision_id, before_run_id, after_run_id, method):
        with self.db.connect() as conn:
            revision = conn.execute("SELECT * FROM condition_revisions WHERE revision_id=?", (revision_id,)).fetchone()
            if not revision:
                raise ApiError(404, "NOT_FOUND", "조건 수정 기록을 찾을 수 없음")
            before = self.store.snapshot(conn, revision["before_scenario_id"])
            after = self.store.snapshot(conn, revision["after_scenario_id"])
        previous = self.store.get_results(before_run_id)[1] if before_run_id else None
        following = self.store.get_results(after_run_id)[1]
        try:
            value = compare_recalculation(before, previous, after, following, method=method, reason=revision["reason"])
        except (RecalculationError, ValueError):
            raise ApiError(422, "COMPARISON_INVALID", "같은 조건 수정에 해당하는 검증 결과가 필요함") from None
        return {"revision_id": revision_id, "confirmation": revision["confirmation"], "comparison": value}

    @staticmethod
    def assumptions(node):
        if isinstance(node, dict):
            return node.get("kind") == "assumed" or any(WorkflowStore.assumptions(v) for v in node.values())
        return isinstance(node, list) and any(WorkflowStore.assumptions(v) for v in node)

    def approval_guard(self, conn, snapshot):
        revision = conn.execute("SELECT confirmation FROM condition_revisions WHERE after_scenario_id=?",
                                (snapshot["scenario_id"],)).fetchone()
        # The established mock travel matrix is explicitly assumed in v0.1.
        # Preserve that model; block hypothetical readiness/availability edits,
        # not the already-disclosed simulation's reference travel assumptions.
        if (any(row["evidence"]["kind"] == "assumed" for row in snapshot["jobs"] + snapshot["vehicles"])
                or (revision and revision[0] == "assumed")):
            raise ApiError(422, "ASSUMPTION_NOT_APPROVABLE", "가정 시험은 확인된 조건으로 다시 등록·계산해야 확정 가능")

    def authority(self, conn, plan_id, approval_id=None, version=None):
        head = self.store.head(conn, plan_id)
        plan = json.loads(conn.execute("SELECT plan_json FROM plans WHERE plan_id=? AND version=?",
                                      (plan_id, head["current_version"])).fetchone()[0])
        row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (plan["approval_id"],)).fetchone()
        if (not row or row["scenario_id"] != head["active_scenario_id"]
                or (approval_id is not None and approval_id != row["approval_id"])
                or (version is not None and version != head["current_version"])):
            raise ApiError(409, "PLAN_VERSION_CONFLICT", "최신 입력으로 독립 검사·내부 확정한 계획이 필요함")
        snapshot = self.store.snapshot(conn, row["scenario_id"])
        stored_input = conn.execute("SELECT input_sha256 FROM scenarios WHERE scenario_id=?",(row["scenario_id"],)).fetchone()[0]
        stored_run = conn.execute("SELECT input_sha256 FROM runs WHERE run_id=?",(row["run_id"],)).fetchone()[0]
        if stored_input != digest(snapshot) or stored_run != stored_input:
            raise ApiError(422,"APPROVAL_INTEGRITY_FAILED","보존된 입력/실행 해시 재검사 실패")
        if not moment(snapshot["as_of"]) <= self.hub.clock() <= moment(snapshot["policy"]["input_valid_until"]):
            raise ApiError(503, "INPUT_EXPIRED", "유효기간 안의 확인된 입력이 필요함")
        self.approval_guard(conn, snapshot)
        approval = {k: row[k] for k in ("approval_id", "plan_id", "version", "run_id", "method", "approved_by", "approved_at")}
        approval["external_actions_performed"] = False
        run = self.store.run(conn, row["run_id"])
        result = conn.execute("SELECT result_json FROM method_results WHERE run_id=? AND method=?",
                              (row["run_id"], row["method"])).fetchone()
        if not result or run["status"] != "completed" or approval["approved_by"] != self.store.actor_id:
            raise ApiError(409, "PLAN_VERSION_CONFLICT", "현재 세션의 검증된 승인 결과가 필요함")
        results = {"run_id": row["run_id"], "scenario_id": snapshot["scenario_id"],
                   "base_plan_version": snapshot["base_plan_version"], "input_sha256": stored_run,
                   "results": [json.loads(result[0])]}
        try:
            preview = bind_archived_approval(snapshot, results, plan, approval)
        except (ValueError, KeyError, ApiError):
            raise ApiError(422, "APPROVAL_INTEGRITY_FAILED", "입력·계산·확정 계획 재검사 실패") from None
        preview["delivery_authorized"] = False  # Sending requires an additional explicit operation.
        # Include fixed risks even on a vehicle with no changed assignments.
        vehicles = {v["vehicle_id"]: deepcopy(v) | {"followups": []} for v in preview["vehicle_changes"]}
        assignments = snapshot["baseline_assignments"] + plan["assignments"]
        for issue in preview["followups"]:
            for vid in {a["vehicle_id"] for a in assignments if a["job_id"] == issue["job_id"]}:
                vehicle = vehicles.setdefault(vid, {"vehicle_id": vid, "changes": [], "followups": []})
                vehicle["followups"].append(deepcopy(issue))
        preview["vehicle_changes"] = [vehicles[v] for v in sorted(vehicles)]
        preview["stage"] = "current_approved_preview"
        return preview

    def preview(self, plan_id):
        with self.db.connect() as conn:
            value = self.authority(conn, plan_id)
            for vehicle in value["vehicle_changes"]:
                row = conn.execute("SELECT r.recipient_id,r.expires_at,r.revoked,p.status,p.expires_at AS subscription_expires "
                    "FROM recipient_vehicles v JOIN recipients r ON r.recipient_id=v.recipient_id "
                    "LEFT JOIN push_subscriptions p ON p.recipient_id=r.recipient_id WHERE v.plan_id=? AND v.vehicle_id=?",
                    (plan_id, vehicle["vehicle_id"])).fetchone()
                active = row and not row["revoked"] and moment(row["expires_at"]) > self.hub.clock()
                subscribed = active and row["status"] == "active" and moment(row["subscription_expires"]) > self.hub.clock()
                vehicle.update(recipient_id=row["recipient_id"] if active else None,
                               recipient_status="linked" if subscribed else "unsubscribed" if active else "unlinked")
            return value

    def invite(self, body, key):
        self.hub.authorize(self.sid)
        def operation(conn):
            head = self.store.head(conn, body["plan_id"])
            snapshot = self.store.snapshot(conn, head["active_scenario_id"])
            vehicles = {v["vehicle_id"] for v in snapshot["vehicles"]}
            if not set(body["vehicle_ids"]) <= vehicles or len(set(body["vehicle_ids"])) != len(body["vehicle_ids"]):
                raise ApiError(422, "RECIPIENT_SCOPE_INVALID", "해당 계획의 차량 범위를 확인해야 함")
            count = conn.execute("SELECT count(*) FROM invitations WHERE revoked=0 AND expires_at>?",
                                 (self.hub.now(),)).fetchone()[0]
            if count >= 3 or conn.execute("SELECT count(*) FROM invitations").fetchone()[0] >= 10:
                raise ApiError(429, "RECIPIENT_LIMIT", "세션 시험 수신자/초대 상한에 도달함")
            identifier = new_id()
            expires = min(self.hub.clock() + timedelta(minutes=30), moment(self.hub.session(self.sid)["expires_at"]))
            conn.execute("INSERT INTO invitations(invitation_id,plan_id,vehicle_ids_json,expires_at) VALUES(?,?,?,?)",
                         (identifier, body["plan_id"], canonical(body["vehicle_ids"]), stamp(expires)))
            return 201, {"invitation_id": identifier, "expires_at": stamp(expires)}
        status, result = self.store.idempotent("POST /v2/invitations", key, body, operation)
        return status, result | {"invitation_token": self.hub.secrets.token("invite", self.sid, result["invitation_id"])}

    def claim(self, invitation_id, key):
        self.hub.authorize(self.sid)
        def operation(conn):
            invitation = conn.execute("SELECT * FROM invitations WHERE invitation_id=?", (invitation_id,)).fetchone()
            if not invitation or invitation["revoked"]:
                raise ApiError(401, "RECIPIENT_REQUIRED", "유효한 초대가 필요함")
            if moment(invitation["expires_at"]) <= self.hub.clock():
                raise ApiError(410, "INVITATION_EXPIRED", "시험 초대가 만료됨")
            if invitation["consumed_by"]:
                if invitation["claim_key_hash"] != hashed(key):
                    raise ApiError(409, "INVITATION_USED", "이미 연결한 초대임")
                return 200, self.recipient(conn, invitation["consumed_by"])
            if conn.execute("SELECT count(*) FROM recipients WHERE revoked=0 AND expires_at>?", (self.hub.now(),)).fetchone()[0] >= 3:
                raise ApiError(429, "RECIPIENT_LIMIT", "시험 수신자 상한에 도달함")
            identifier = new_id()
            expires = self.hub.session(self.sid)["expires_at"]
            vehicles = json.loads(invitation["vehicle_ids_json"])
            for vehicle in vehicles:
                if conn.execute("SELECT 1 FROM recipient_vehicles WHERE plan_id=? AND vehicle_id=?",
                                (invitation["plan_id"], vehicle)).fetchone():
                    raise ApiError(409, "RECIPIENT_ALREADY_LINKED", "차량에 연결된 기존 수신자를 먼저 해제해야 함")
            conn.execute("INSERT INTO recipients(recipient_id,invitation_id,plan_id,expires_at,created_at) VALUES(?,?,?,?,?)",
                         (identifier, invitation_id, invitation["plan_id"], expires, self.hub.now()))
            for vehicle in vehicles:
                conn.execute("INSERT INTO recipient_vehicles VALUES(?,?,?)", (invitation["plan_id"], vehicle, identifier))
            conn.execute("UPDATE invitations SET consumed_by=?,claim_key_hash=? WHERE invitation_id=?",
                         (identifier, hashed(key), invitation_id))
            return 201, self.recipient(conn, identifier)
        with self.db.transaction() as conn:
            return operation(conn)

    def recipient(self, conn, identifier):
        row = conn.execute("SELECT * FROM recipients WHERE recipient_id=?", (identifier,)).fetchone()
        if not row or row["revoked"] or moment(row["expires_at"]) <= self.hub.clock():
            raise ApiError(401, "RECIPIENT_REQUIRED", "수신자 권한이 만료/해제됨")
        vehicles = [v[0] for v in conn.execute("SELECT vehicle_id FROM recipient_vehicles WHERE recipient_id=? ORDER BY vehicle_id", (identifier,))]
        sub = conn.execute("SELECT status,expires_at FROM push_subscriptions WHERE recipient_id=?", (identifier,)).fetchone()
        status = sub["status"] if sub and moment(sub["expires_at"]) > self.hub.clock() else "expired" if sub else "missing"
        loc = conn.execute("SELECT captured_at FROM recipient_locations WHERE recipient_id=?", (identifier,)).fetchone()
        return {"recipient_id": identifier, "vehicle_ids": vehicles, "expires_at": row["expires_at"],
                "subscription_status": status, "data_mode": "simulated",
                "location_captured_at": loc["captured_at"] if loc else None}

    def recipients(self):
        with self.db.connect() as conn:
            values = []
            for row in conn.execute("SELECT * FROM recipients ORDER BY created_at"):
                sub = conn.execute("SELECT status,expires_at FROM push_subscriptions WHERE recipient_id=?", (row["recipient_id"],)).fetchone()
                values.append({"recipient_id": row["recipient_id"], "plan_id": row["plan_id"], "expires_at": row["expires_at"],
                    "revoked": bool(row["revoked"]), "vehicle_ids": [v[0] for v in conn.execute(
                        "SELECT vehicle_id FROM recipient_vehicles WHERE recipient_id=?", (row["recipient_id"],))],
                    "subscription_status": sub["status"] if sub and moment(sub["expires_at"]) > self.hub.clock() else "expired" if sub else "missing",
                    "location": self.location_of(conn, row)})
            return {"recipients": values}

    # 기사 휴대폰 위치: 동의한 기사가 화면을 연 동안 보낸 최신 1건만 두고, 받은 지 60분이 지나면 보여 주지 않는다.
    LOCATION_TTL = timedelta(minutes=60)

    def location_of(self, conn, row):
        if row["revoked"]:
            return None
        loc = conn.execute("SELECT * FROM recipient_locations WHERE recipient_id=?", (row["recipient_id"],)).fetchone()
        if not loc or moment(loc["received_at"]) < self.hub.clock() - self.LOCATION_TTL:
            return None
        return {"latitude": loc["latitude"], "longitude": loc["longitude"], "accuracy_m": loc["accuracy_m"],
                "captured_at": loc["captured_at"], "received_at": loc["received_at"]}

    def share_location(self, identifier, body):
        try:
            captured = moment(body["captured_at"])
        except ValueError:
            raise ApiError(422, "INVALID_LOCATION", "위치 측정 시각 형식이 맞지 않음")
        if captured.tzinfo is None:
            raise ApiError(422, "INVALID_LOCATION", "위치 측정 시각에 시간대가 없음")
        now = self.hub.clock()
        if captured > now + timedelta(minutes=2) or captured < now - timedelta(minutes=10):
            raise ApiError(422, "LOCATION_STALE", "10분 안에 측정한 위치만 받음")
        values = (identifier, float(body["latitude"]), float(body["longitude"]), float(body["accuracy_m"]),
                  stamp(captured), self.hub.now())
        with self.db.transaction() as conn:
            self.recipient(conn, identifier)
            conn.execute("INSERT INTO recipient_locations VALUES(?,?,?,?,?,?) ON CONFLICT(recipient_id) DO UPDATE SET "
                         "latitude=excluded.latitude,longitude=excluded.longitude,accuracy_m=excluded.accuracy_m,"
                         "captured_at=excluded.captured_at,received_at=excluded.received_at", values)
        return {"location_shared": True, "captured_at": values[4]}

    def stop_location(self, identifier):
        with self.db.transaction() as conn:
            self.recipient(conn, identifier)
            conn.execute("DELETE FROM recipient_locations WHERE recipient_id=?", (identifier,))
        return {"location_shared": False, "captured_at": None}

    def revoke(self, identifier):
        with self.db.transaction() as conn:
            row = conn.execute("SELECT invitation_id FROM recipients WHERE recipient_id=?", (identifier,)).fetchone()
            if not row:
                raise ApiError(404, "NOT_FOUND", "수신자를 찾을 수 없음")
            conn.execute("UPDATE recipients SET revoked=1 WHERE recipient_id=?", (identifier,))
            conn.execute("UPDATE invitations SET revoked=1 WHERE invitation_id=?", (row[0],))
            conn.execute("DELETE FROM recipient_vehicles WHERE recipient_id=?", (identifier,))
            conn.execute("DELETE FROM recipient_locations WHERE recipient_id=?", (identifier,))
            conn.execute("UPDATE push_subscriptions SET status='revoked',encrypted_json=NULL,endpoint_fingerprint=NULL WHERE recipient_id=?", (identifier,))
        with self.hub.registry.transaction() as conn:
            conn.execute("DELETE FROM endpoint_owners WHERE session_id=? AND recipient_id=?", (self.sid, identifier))
        return {"recipient_id": identifier, "revoked": True}

    def subscribe(self, identifier, subscription, key):
        self.hub.authorize(self.sid)
        value = validate_subscription(subscription, now_ms=int(self.hub.clock().timestamp() * 1000))
        fingerprint = self.hub.secrets.fingerprint(value["endpoint"])
        expires = self.hub.session(self.sid)["expires_at"]
        if value["expirationTime"]:
            from datetime import datetime, timezone
            expires = min(expires, stamp(datetime.fromtimestamp(value["expirationTime"] / 1000, timezone.utc)))
        # A registry reservation can remain after a crash, denying rather than
        # granting access; retry by the same owner is safe. Revoke removes it.
        with self.hub.lock:
            with self.hub.registry.transaction() as conn:
                previous = conn.execute("SELECT * FROM endpoint_owners WHERE fingerprint=?", (fingerprint,)).fetchone()
                if previous and (previous["session_id"], previous["recipient_id"]) != (self.sid, identifier):
                    raise ApiError(409, "SUBSCRIPTION_ALREADY_LINKED", "이미 다른 시험 수신자에 연결된 구독임")
                conn.execute("INSERT OR IGNORE INTO endpoint_owners VALUES(?,?,?)", (fingerprint, self.sid, identifier))
            def operation(conn):
                self.recipient(conn, identifier)
                conn.execute("INSERT INTO push_subscriptions VALUES(?,?,?,?,?,?) ON CONFLICT(recipient_id) DO UPDATE SET "
                    "encrypted_json=excluded.encrypted_json,endpoint_fingerprint=excluded.endpoint_fingerprint,"
                    "expires_at=excluded.expires_at,status=excluded.status,created_at=excluded.created_at",
                    (identifier, self.hub.secrets.encrypt(value), fingerprint, expires, "active", self.hub.now()))
                return 201, {"subscription_status": "active", "expires_at": expires}
            # Only the digest of the request enters the v0.1 idempotency table.
            try:
                return self.store.idempotent(f"POST /v2/recipient/{identifier}/subscription", key, value, operation)
            finally:
                # Keep only the actually committed active subscription, including
                # when an old idempotency key is replayed or a write is rejected.
                with self.db.connect() as conn:
                    active = conn.execute("SELECT endpoint_fingerprint,status FROM push_subscriptions WHERE recipient_id=?",
                                          (identifier,)).fetchone()
                keep = active["endpoint_fingerprint"] if active and active["status"] == "active" else None
                with self.hub.registry.transaction() as conn:
                    conn.execute("DELETE FROM endpoint_owners WHERE session_id=? AND recipient_id=? AND fingerprint IS NOT ?",
                                 (self.sid,identifier,keep))

    def unsubscribe(self, identifier):
        with self.db.transaction() as conn:
            self.recipient(conn, identifier)
            conn.execute("UPDATE push_subscriptions SET status='revoked',encrypted_json=NULL,endpoint_fingerprint=NULL WHERE recipient_id=?", (identifier,))
        with self.hub.registry.transaction() as conn:
            conn.execute("DELETE FROM endpoint_owners WHERE session_id=? AND recipient_id=?", (self.sid, identifier))
        return {"subscription_status": "revoked"}

    @staticmethod
    def target_payload(preview, vehicle_ids):
        targets = []
        for vehicle in preview["vehicle_changes"]:
            if vehicle["vehicle_id"] not in vehicle_ids:
                continue
            value = deepcopy(vehicle)
            for change in value["changes"]:
                if change["kind"] != "removed_from_plan":
                    change["instruction"] = "담당자가 확정한 모의 변경 내용입니다. 수행 가능 여부를 응답하세요. 실제 운송/예약 변경을 뜻하지 않습니다."
                for side in ("before", "after"):
                    assignment = change[side]
                    if assignment and assignment["vehicle_id"] not in vehicle_ids:
                        change[side] = None
                        change[side + "_outside_scope"] = True
            targets.append(value)
        return {"data_mode": "simulated", "stage":"approved_simulation_change",
                "plan_id":preview["plan_id"], "plan_version":preview["approved_version"],
                "approval_id":preview["approval_id"], "scenario_id":preview["scenario_id"],
                "run_id":preview["run_id"], "vehicle_changes": targets,
                "transport_completion": "not_claimed", "external_booking_changed": False}

    def dispatch(self, plan_id, body, key):
        self.hub.authorize(self.sid)
        if not self.hub.sender.configured:
            raise ApiError(503, "PUSH_NOT_CONFIGURED", "서버 Web Push 설정이 필요함")
        def operation(conn):
            preview = self.authority(conn, plan_id, body["approval_id"], body["expected_version"])
            prior = conn.execute("SELECT dispatch_id FROM dispatches WHERE approval_id=?", (body["approval_id"],)).fetchone()
            if prior:
                return 200, {"dispatch_id": prior[0]}
            if conn.execute("SELECT count(*) FROM dispatches").fetchone()[0] >= 10:
                raise ApiError(429, "DISPATCH_LIMIT", "세션 전달 상한에 도달함")
            if len(self.hub.sends) >= 8:
                raise ApiError(429, "QUEUE_FULL", "전달 대기열 상한에 도달함")
            dispatch_id = new_id("D-")
            conn.execute("INSERT INTO dispatches VALUES(?,?,?,?,?,?,?)", (dispatch_id, body["approval_id"], plan_id,
                         body["expected_version"], preview["scenario_id"], canonical(preview), self.hub.now()))
            groups = {}
            for vehicle in preview["vehicle_changes"]:
                row = conn.execute("SELECT r.recipient_id,r.revoked,r.expires_at FROM recipient_vehicles v "
                    "JOIN recipients r ON r.recipient_id=v.recipient_id WHERE v.plan_id=? AND v.vehicle_id=?",
                    (plan_id, vehicle["vehicle_id"])).fetchone()
                rid = row["recipient_id"] if row and not row["revoked"] and moment(row["expires_at"]) > self.hub.clock() else None
                groups.setdefault(rid or "unlinked:" + vehicle["vehicle_id"], []).append(vehicle["vehicle_id"])
            for group, vehicles in groups.items():
                rid = None if group.startswith("unlinked:") else group
                sub = conn.execute("SELECT * FROM push_subscriptions WHERE recipient_id=?", (rid,)).fetchone() if rid else None
                subscribed = sub and sub["status"] == "active" and moment(sub["expires_at"]) > self.hub.clock()
                status = "pending" if subscribed else "unsubscribed" if rid else "unlinked"
                conn.execute("INSERT INTO notifications(notification_id,dispatch_id,recipient_id,vehicle_ids_json,"
                    "payload_json,delivery_status,created_at) VALUES(?,?,?,?,?,?,?)", (new_id("N-"), dispatch_id, rid,
                    canonical(vehicles), canonical(self.target_payload(preview, vehicles)), status, self.hub.now()))
            return 202, {"dispatch_id": dispatch_id}
        with self.hub.lock:
            status, result = self.store.idempotent(f"POST /v2/plans/{plan_id}/dispatches", key, body, operation)
            self.hub.enqueue_delivery(self, result["dispatch_id"])
        return status, result

    def is_current(self, conn, dispatch):
        head = self.store.head(conn, dispatch["plan_id"])
        if head["current_version"] != dispatch["plan_version"] or head["active_scenario_id"] != dispatch["scenario_id"]:
            return False
        snapshot = self.store.snapshot(conn, dispatch["scenario_id"])
        return moment(snapshot["as_of"]) <= self.hub.clock() <= moment(snapshot["policy"]["input_valid_until"])

    def notification(self, conn, identifier, *, recipient_id=None):
        row = conn.execute("SELECT * FROM notifications WHERE notification_id=?", (identifier,)).fetchone()
        if not row or (recipient_id is not None and row["recipient_id"] != recipient_id):
            raise ApiError(404, "NOT_FOUND", "알림을 찾을 수 없음")
        dispatch = conn.execute("SELECT * FROM dispatches WHERE dispatch_id=?", (row["dispatch_id"],)).fetchone()
        current = self.is_current(conn, dispatch)
        if recipient_id:
            latest = conn.execute("SELECT dispatch_id FROM notifications WHERE recipient_id=? ORDER BY rowid DESC LIMIT 1", (recipient_id,)).fetchone()
            current = current and latest[0] == row["dispatch_id"]
        value = {k: row[k] for k in ("notification_id", "dispatch_id", "recipient_id", "delivery_status", "error_code",
                 "attempts", "created_at", "accepted_at", "opened_at", "retry_not_before", "response", "responded_at")}
        history = [dict(event) for event in conn.execute("SELECT response,note,created_at FROM recipient_responses "
                    "WHERE notification_id=? ORDER BY rowid", (identifier,))]
        value.update(is_current=current, vehicle_ids=json.loads(row["vehicle_ids_json"]),
                     payload=json.loads(row["payload_json"]) if current or recipient_id is None else None,
                     response_history=history,
                     needs_followup=not current or row["response"] != "can_perform")
        return value

    def get_dispatch(self, identifier):
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM dispatches WHERE dispatch_id=?", (identifier,)).fetchone()
            if not row:
                raise ApiError(404, "NOT_FOUND", "전달 기록을 찾을 수 없음")
            notifications = [self.notification(conn, n[0]) for n in conn.execute("SELECT notification_id FROM notifications WHERE dispatch_id=? ORDER BY rowid", (identifier,))]
            return {"dispatch_id": identifier, "approval_id": row["approval_id"], "plan_id": row["plan_id"],
                    "plan_version": row["plan_version"], "scenario_id": row["scenario_id"],
                    "is_current": self.is_current(conn, row), "notifications": notifications,
                    "followups": json.loads(row["preview_json"])["followups"],
                    "external_transport_completed": False}

    def recipient_notifications(self, identifier, notification_id=None):
        with self.db.connect() as conn:
            self.recipient(conn, identifier)
            if notification_id:
                return self.notification(conn, notification_id, recipient_id=identifier)
            return {"notifications": [self.notification(conn, row[0], recipient_id=identifier) for row in conn.execute(
                "SELECT notification_id FROM notifications WHERE recipient_id=? ORDER BY rowid DESC", (identifier,))]}

    def respond(self, identifier, notification_id, body, key, *, opened=False):
        def operation(conn):
            self.recipient(conn, identifier)
            current = self.notification(conn, notification_id, recipient_id=identifier)
            if not current["is_current"]:
                raise ApiError(409, "NOTIFICATION_SUPERSEDED", "이전 계획 알림에는 응답할 수 없음")
            if opened:
                conn.execute("UPDATE notifications SET opened_at=coalesce(opened_at,?) WHERE notification_id=?", (self.hub.now(), notification_id))
            else:
                if len(current["response_history"]) >= 20:
                    raise ApiError(429, "RESPONSE_LIMIT", "알림별 응답 보관 상한에 도달함")
                if current["response"] in {"can_perform", "cannot_perform"} and body["response"] == "acknowledged":
                    raise ApiError(409, "RESPONSE_TRANSITION", "수행 판단은 가능/곤란의 명시 응답으로 수정해야 함")
                conn.execute("INSERT INTO recipient_responses VALUES(?,?,?,?,?,?)", (new_id("E-"), notification_id,
                             identifier, body["response"], body.get("note", ""), self.hub.now()))
                conn.execute("UPDATE notifications SET response=?,responded_at=? WHERE notification_id=?",
                             (body["response"], self.hub.now(), notification_id))
            return 200, self.notification(conn, notification_id, recipient_id=identifier)
        with self.hub.lock:
            with self.db.connect() as conn:
                self.recipient(conn, identifier)
                if not self.notification(conn, notification_id, recipient_id=identifier)["is_current"]:
                    raise ApiError(409, "NOTIFICATION_SUPERSEDED", "이전 계획 알림에는 응답할 수 없음")
            return self.store.idempotent(f"POST /v2/recipient/{identifier}/notifications/{notification_id}/{'opened' if opened else 'responses'}",
                                         key, body, operation)

    def retry(self, identifier, body, key):
        self.hub.authorize(self.sid)
        if not self.hub.sender.configured:
            raise ApiError(503, "PUSH_NOT_CONFIGURED", "서버 Web Push 설정 필요")
        def operation(conn):
            value = self.notification(conn, identifier)
            if not value["is_current"]:
                raise ApiError(409, "NOTIFICATION_SUPERSEDED", "최신 알림만 재시도 가능")
            if value["delivery_status"] in {"unknown", "sending", "accepted"}:
                raise ApiError(409, "DELIVERY_UNCERTAIN", "중복 가능성이 있어 재전송하지 않음")
            if value["retry_not_before"] and self.hub.clock() < moment(value["retry_not_before"]):
                delay = max(1,math.ceil((moment(value["retry_not_before"])-self.hub.clock()).total_seconds()))
                raise ApiError(429, "PUSH_RATE_LIMITED", "푸시 중계망의 재시도 대기시간이 지나지 않았음",
                               headers={"Retry-After":str(delay)})
            if value["delivery_status"] not in {"failed", "expired", "unsubscribed", "unlinked"} or value["attempts"] >= 3:
                raise ApiError(409, "DELIVERY_NOT_RETRYABLE", "재시도 가능한 확정 실패가 아님")
            rid = value["recipient_id"]
            dispatch = conn.execute("SELECT * FROM dispatches WHERE dispatch_id=?", (value["dispatch_id"],)).fetchone()
            if rid is None:
                mappings = [conn.execute("SELECT recipient_id FROM recipient_vehicles WHERE plan_id=? AND vehicle_id=?",
                                        (dispatch["plan_id"], v)).fetchone() for v in value["vehicle_ids"]]
                if not mappings or any(not r for r in mappings) or len({r[0] for r in mappings}) != 1:
                    raise ApiError(422, "RECIPIENT_UNLINKED", "전달 대상 연결을 먼저 확인해야 함")
                rid = mappings[0][0]
                if body.get("recipient_id") != rid:
                    raise ApiError(409, "RECIPIENT_CHANGED", "새로 연결한 수신자ID를 명시 확인해야 함")
            self.recipient(conn, rid)
            sub = conn.execute("SELECT * FROM push_subscriptions WHERE recipient_id=?", (rid,)).fetchone()
            if not sub or sub["status"] != "active" or moment(sub["expires_at"]) <= self.hub.clock():
                raise ApiError(422, "SUBSCRIPTION_REQUIRED", "유효한 알림 구독이 필요함")
            conn.execute("UPDATE notifications SET recipient_id=?,delivery_status='pending',error_code=NULL,retry_not_before=NULL WHERE notification_id=?", (rid, identifier))
            return 202, {"dispatch_id": value["dispatch_id"], "notification_id": identifier}
        with self.hub.lock:
            status, result = self.store.idempotent(f"POST /v2/notifications/{identifier}/retry", key, body, operation)
            self.hub.enqueue_delivery(self, result["dispatch_id"])
        return status, result

    def deliver(self, dispatch_id):
        with self.db.connect() as conn:
            identifiers = [r[0] for r in conn.execute("SELECT notification_id FROM notifications WHERE dispatch_id=? AND delivery_status='pending' ORDER BY rowid", (dispatch_id,))]
        for identifier in identifiers:
            if self.hub.stop_maintenance.is_set():
                with self.db.transaction() as conn:
                    conn.execute("UPDATE notifications SET delivery_status='failed',error_code='SERVER_STOPPING' "
                                 "WHERE dispatch_id=? AND delivery_status='pending'",(dispatch_id,))
                break
            try:
                self.hub.authorize(self.sid)
            except ApiError:
                with self.db.transaction() as conn:
                    conn.execute("UPDATE notifications SET delivery_status='failed',error_code='PUSH_TEST_NOT_AUTHORIZED' "
                                 "WHERE notification_id=? AND delivery_status='pending'", (identifier,))
                continue
            with self.db.transaction() as conn:
                row = conn.execute("SELECT * FROM notifications WHERE notification_id=?", (identifier,)).fetchone()
                if row["delivery_status"] != "pending":
                    continue
                dispatch = conn.execute("SELECT * FROM dispatches WHERE dispatch_id=?", (dispatch_id,)).fetchone()
                if not self.is_current(conn, dispatch):
                    conn.execute("UPDATE notifications SET delivery_status='superseded' WHERE notification_id=?", (identifier,))
                    continue
                # Re-run current approval/schedule integrity immediately before claim.
                try:
                    self.authority(conn, dispatch["plan_id"], dispatch["approval_id"], dispatch["plan_version"])
                    self.recipient(conn, row["recipient_id"])
                except ApiError:
                    conn.execute("UPDATE notifications SET delivery_status='superseded',error_code='AUTHORITY_CHANGED' WHERE notification_id=?", (identifier,))
                    continue
                sub = conn.execute("SELECT * FROM push_subscriptions WHERE recipient_id=?", (row["recipient_id"],)).fetchone()
                if not sub or sub["status"] != "active" or moment(sub["expires_at"]) <= self.hub.clock():
                    conn.execute("UPDATE notifications SET delivery_status='unsubscribed' WHERE notification_id=?", (identifier,))
                    continue
                try:
                    subscription = self.hub.secrets.decrypt(sub["encrypted_json"])
                except Exception:
                    conn.execute("UPDATE notifications SET delivery_status='failed',error_code='SUBSCRIPTION_UNREADABLE' WHERE notification_id=?", (identifier,))
                    continue
                attempt = new_id("P-")
                conn.execute("UPDATE notifications SET delivery_status='sending',attempts=attempts+1 WHERE notification_id=?", (identifier,))
                conn.execute("INSERT INTO notification_attempts VALUES(?,?,?,NULL,'sending',NULL)", (attempt, identifier, self.hub.now()))
            payload = {"title": "반입맞춤 변경 알림", "body": "변경 내용을 확인해 주세요.",
                       "notification_id": identifier, "url": "/recipient#notification=" + identifier}
            try:
                outcome = self.hub.sender.send(subscription, payload)
                if outcome.get("status") not in {"accepted", "failed", "expired", "unknown"}:
                    raise ValueError
            except Exception:
                outcome = {"status": "unknown", "error_code": "PUSH_OUTCOME_UNKNOWN"}
            # Only our own fixed codes enter history, never a transport exception.
            code = outcome.get("error_code")
            allowed = {None, "PUSH_NOT_CONFIGURED", "PUSH_OUTCOME_UNKNOWN", "PUSH_SUBSCRIPTION_EXPIRED", "PUSH_REJECTED", "PUSH_VALIDATION_FAILED", "PUSH_RATE_LIMITED"}
            code = code if code in allowed else "PUSH_OUTCOME_UNKNOWN"
            delay = outcome.get("retry_after_seconds",60)
            delay = delay if type(delay) is int and 1 <= delay <= 604800 else 60
            retry_at = stamp(self.hub.clock()+timedelta(seconds=delay)) if code == "PUSH_RATE_LIMITED" else None
            with self.hub.lock:
                expired = False
                with self.db.transaction() as conn:
                    conn.execute("UPDATE notifications SET delivery_status=?,error_code=?,accepted_at=?,retry_not_before=? WHERE notification_id=?",
                                 (outcome["status"], code, self.hub.now() if outcome["status"] == "accepted" else None,retry_at,identifier))
                    conn.execute("UPDATE notification_attempts SET finished_at=?,status=?,error_code=? WHERE attempt_id=?",
                                 (self.hub.now(), outcome["status"], code, attempt))
                    if outcome["status"] == "expired":
                        expired = conn.execute("UPDATE push_subscriptions SET status='expired',encrypted_json=NULL,endpoint_fingerprint=NULL "
                            "WHERE recipient_id=? AND encrypted_json=?", (row["recipient_id"], sub["encrypted_json"])).rowcount == 1
                if expired:
                    with self.hub.registry.transaction() as conn:
                        conn.execute("DELETE FROM endpoint_owners WHERE session_id=? AND recipient_id=? AND fingerprint=?",
                                     (self.sid, row["recipient_id"], sub["endpoint_fingerprint"]))
