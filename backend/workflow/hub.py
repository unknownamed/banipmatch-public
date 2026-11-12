"""Single-process admission and independent per-visitor immutable databases."""
from __future__ import annotations

from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import threading
import time

from backend.api.contracts import ApiError, ROOT, utc_now
from backend.api.engine_replay import EngineReplay
from backend.api.runs import ReplayJobs
from backend.db.database import Database
from backend.db.database import ensure_field_columns
from backend.db.store import Store
from .push import WebPushSender
from .security import IDENTIFIER, Secrets, csrf, hashed

CONTRACT = ROOT / "docs" / "development" / "v0.2"


def moment(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Registry(Database):
    def initialize(self):
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if version not in (0, 1) or (version == 0 and tables) or (version == 1 and not {"sessions","endpoint_owners"} <= tables):
                raise RuntimeError("지원하지 않는 세션 registry 버전")
            conn.executescript((CONTRACT / "registry.sql").read_text(encoding="utf-8"))
            conn.execute("PRAGMA journal_mode=WAL")


# 기사가 동의해 보낸 휴대폰 위치(차량별 최신 1건만, 이력 없음). 예전 세션 DB에도 없으면 만든다.
LOCATION_DDL = ("CREATE TABLE IF NOT EXISTS recipient_locations ("
                " recipient_id TEXT PRIMARY KEY REFERENCES recipients(recipient_id),"
                " latitude REAL NOT NULL, longitude REAL NOT NULL, accuracy_m REAL NOT NULL,"
                " captured_at TEXT NOT NULL, received_at TEXT NOT NULL) STRICT;")


class DomainDatabase(Database):
    def initialize(self):
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version in (0, 1):
            super().initialize()
            with self.connect() as conn:
                conn.executescript((CONTRACT / "schema.sql").read_text(encoding="utf-8"))
        elif version != 2:
            raise RuntimeError("지원하지 않는 세션 DB 버전")
        else:
            with self.connect() as conn:
                ensure_field_columns(conn)
                conn.commit()
        with self.connect() as conn:
            conn.executescript(LOCATION_DDL)


# 발표장 30명 동시 계산 요청을 받는 대기열 상한(세션당 1건).
QUEUE_LIMIT = 30

class Hub:
    def __init__(self, settings, *, replay=None, sender=None, clock=None):
        self.settings = settings
        self.root = settings.workflow_dir.resolve()
        self.registry = Registry(self.root / "registry.sqlite3")
        self.adapter = replay or EngineReplay()
        self.sender = sender
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock = threading.RLock()
        self.domains, self.pending, self.sends = {}, {}, {}
        self.rates = defaultdict(deque)

    def now(self) -> str:
        return stamp(self.clock())

    def start(self):
        self.registry.acquire()
        try:
            self.registry.initialize()
            with self.registry.connect() as conn:
                count = conn.execute("SELECT count(*) FROM sessions WHERE ready=1").fetchone()[0]
            if count and not (self.root / "secrets.key").exists():
                raise RuntimeError("기존 세션 보호키 유실. 원래 키를 복구해야 함")
            self.secrets = Secrets(self.root / "secrets.key")
            self.sender = self.sender or WebPushSender(self.settings)
            # 서버 vCPU 2개에 맞춘 동시 계산 2건. 세션별 DB가 분리되고 같은 세션은 한 건만 대기한다.
            self.calculations = ThreadPoolExecutor(max_workers=2, thread_name_prefix="session-calculation")
            self.deliveries = ThreadPoolExecutor(max_workers=1, thread_name_prefix="push-delivery")
            with self.registry.connect() as conn:
                rows = conn.execute("SELECT session_id FROM sessions WHERE ready=1").fetchall()
            for row in rows:
                self.domain(row[0])  # Interrupted computations/sends are recovered once.
            self.cleanup()
            self.stop_maintenance = threading.Event()
            self.maintenance = threading.Thread(target=self.maintain, daemon=True, name="session-retention")
            self.maintenance.start()
        except BaseException:
            self.close()
            raise

    def close(self):
        if hasattr(self, "stop_maintenance"):
            self.stop_maintenance.set()
            self.maintenance.join()
        if hasattr(self, "deliveries"):
            self.deliveries.shutdown(wait=True, cancel_futures=True)
        if hasattr(self, "calculations"):
            self.calculations.shutdown(wait=True, cancel_futures=True)
        self.registry.release()

    def maintain(self):
        while not self.stop_maintenance.wait(60):
            try:
                with self.lock:
                    self.cleanup()
                self.maintenance_failed = False
            except Exception:
                # Health exposes only a flag; never a DB path or secret-bearing error.
                self.maintenance_failed = True

    def rate(self, bucket: str, *, limit=60, seconds=60):
        with self.lock:
            now = time.monotonic()
            if bucket not in self.rates and len(self.rates) >= 4096:
                for key in list(self.rates):
                    if not self.rates[key] or self.rates[key][-1] <= now - 3600:
                        del self.rates[key]
                if len(self.rates) >= 4096:
                    raise ApiError(429, "RATE_LIMITED", "요청량 제한. 잠시 후 다시 시도해야 함")
            queue = self.rates[bucket]
            while queue and queue[0] <= now - seconds:
                queue.popleft()
            if len(queue) >= limit:
                raise ApiError(429, "RATE_LIMITED", "요청량 제한. 잠시 후 다시 시도해야 함")
            queue.append(now)

    def session(self, sid: str) -> dict:
        if not isinstance(sid, str) or not IDENTIFIER.fullmatch(sid):
            raise ApiError(401, "SESSION_REQUIRED", "모의 세션이 필요함")
        with self.registry.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (sid,)).fetchone()
        if row is None or not row["ready"]:
            raise ApiError(401, "SESSION_REQUIRED", "모의 세션이 필요함")
        if row["revoked"] or moment(row["expires_at"]) <= self.clock():
            raise ApiError(410, "SESSION_EXPIRED", "모의 세션이 만료됨. 새 시연을 시작해야 함")
        return dict(row)

    def authenticate(self, cookie: str) -> dict:
        try:
            sid, secret = cookie.split(".")
            if len(secret) != 43:
                raise ValueError
        except (ValueError, AttributeError):
            raise ApiError(401, "SESSION_REQUIRED", "모의 세션이 필요함") from None
        row = self.session(sid)
        if not secrets.compare_digest(row["token_hash"], hashed(cookie)):
            raise ApiError(401, "SESSION_REQUIRED", "모의 세션이 필요함")
        return row

    def session_response(self, cookie: str, row: dict) -> dict:
        domain = self.domain(row["session_id"])
        with domain.db.connect() as conn:
            plans = []
            for plan in conn.execute("SELECT * FROM plan_heads ORDER BY updated_at DESC"):
                run = conn.execute("SELECT run_id FROM runs WHERE scenario_id=? ORDER BY rowid DESC LIMIT 1",
                                   (plan["active_scenario_id"],)).fetchone()
                revision = conn.execute("SELECT revision_id FROM condition_revisions WHERE after_scenario_id=?",
                                        (plan["active_scenario_id"],)).fetchone()
                plans.append({"plan_id": plan["plan_id"], "version": plan["current_version"],
                    "scenario_id": plan["active_scenario_id"], "latest_run_id": run[0] if run else None,
                    "latest_revision_id": revision[0] if revision else None})
        return {"session_id": row["session_id"], "expires_at": row["expires_at"],
                "csrf_token": csrf(cookie), "push_test_authorized": bool(row["push_authorized"]),
                "data_mode": "simulated", "plans": plans, "limits": {"jobs": 20, "vehicles": 10, "max_seconds": 10,
                "queued_and_running": 4, "active_per_session": 1, "recipients": 3,
                "write_operations":300,"scenarios":20,"runs":20}}

    def create_session(self, cookie: str | None, client_bucket: str) -> tuple[str, dict]:
        if cookie:
            try:
                return cookie, self.session_response(cookie, self.authenticate(cookie))
            except ApiError:
                pass
        # A classroom/demo group can share one public IP. Keep admission bounded
        # while allowing a presentation room (30+ visitors, reloads) to open sessions.
        self.rate("new-session:" + client_bucket, limit=60)
        with self.lock:
            self.cleanup()
            sid = secrets.token_hex(16)
            cookie = sid + "." + secrets.token_urlsafe(32)
            now, expires = self.now(), stamp(self.clock() + timedelta(hours=24))
            with self.registry.transaction() as conn:
                if conn.execute("SELECT count(*) FROM sessions").fetchone()[0] >= 200:
                    raise ApiError(429, "SESSION_LIMIT", "서버 세션 보관 상한에 도달함")
                conn.execute("INSERT INTO sessions(session_id,token_hash,created_at,expires_at) VALUES(?,?,?,?)",
                             (sid, hashed(cookie), now, expires))
            self.domain(sid, create=True)
            with self.registry.transaction() as conn:
                conn.execute("UPDATE sessions SET ready=1 WHERE session_id=?",(sid,))
            return cookie, self.session_response(cookie, self.session(sid))

    def domain(self, sid: str, *, create=False):
        if not IDENTIFIER.fullmatch(sid):
            raise ApiError(401, "SESSION_REQUIRED", "세션 ID 형식 오류")
        with self.lock:
            if sid not in self.domains:
                from .store import WorkflowStore
                directory = self.root / "sessions"
                directory.mkdir(parents=True, exist_ok=True)
                path = directory / (sid + ".sqlite3")
                if path.resolve().parent != directory.resolve():
                    raise RuntimeError("세션 DB 경로가 보관 디렉터리 밖임")
                if not create and not path.exists():
                    raise RuntimeError("세션 DB 유실. 원본 DB 복구가 필요함")
                database = DomainDatabase(path)
                database.initialize()
                store = Store(database, actor_id="session:" + sid, max_operations=300)
                jobs = ReplayJobs(store, self.adapter, executor=self.calculations,
                                  before_execute=lambda run: self.check_queued(sid, run))
                jobs.recover()
                domain = WorkflowStore(self, sid, store, jobs)
                domain.recover()
                self.domains[sid] = domain
            return self.domains[sid]

    def check_queued(self, sid: str, run: dict):
        self.session(sid)
        if (self.clock() - moment(run["created_at"])).total_seconds() > 300:
            raise ApiError(503, "QUEUE_TIMEOUT", "대기시간 상한을 넘음. 새 실행 필요")

    def authorize(self, sid: str):
        if not self.session(sid)["push_authorized"]:
            raise ApiError(403, "PUSH_TEST_NOT_AUTHORIZED", "운영자가 허용한 팀원 시험 세션만 전달 가능")

    def authorize_with_team_code(self, sid: str, code: str):
        """팀 시연 코드가 맞으면 이 세션만 앱 알림 시험 권한을 연다. 코드 값은 응답·로그에 남기지 않는다."""
        import hmac
        path = self.settings.push_team_code_file
        if not path or not path.is_file():
            raise ApiError(503, "TEAM_CODE_NOT_CONFIGURED", "이 서버는 팀 시연 코드를 쓰지 않음")
        self.rate("team-code:" + sid, limit=5, seconds=600)
        self.rate("team-code:all", limit=60, seconds=600)
        expected = path.read_text(encoding="utf-8").strip().upper()
        given = (code or "").strip().upper()
        if not expected or not hmac.compare_digest(given.encode(), expected.encode()):
            raise ApiError(403, "TEAM_CODE_INVALID", "팀 시연 코드가 맞지 않음")
        with self.registry.transaction() as conn:
            conn.execute("UPDATE sessions SET push_authorized=1, consent_note=? WHERE session_id=? AND revoked=0",
                         ("팀 시연 코드로 허용(동의한 팀원 기기 시험)", sid))

    def enqueue_run(self, domain, request: dict, key: str):
        from backend.api.input_preflight import check_input
        with self.lock:
            def check(snapshot, methods):
                if len(self.pending) >= QUEUE_LIMIT or any(s == domain.sid for s, _ in self.pending):
                    raise ApiError(429, "QUEUE_FULL", "계산 중인 작업을 확인하고 잠시 후 요청해야 함")
                with domain.db.connect() as conn:
                    if conn.execute("SELECT count(*) FROM runs").fetchone()[0] >= 100:
                        raise ApiError(429, "RUN_LIMIT", "세션 계산 보관 상한에 도달함")
                check_input(snapshot)
                self.adapter.check(snapshot, methods)
            status, response = domain.store.create_run(request, key, check)
            item = (domain.sid, response["run_id"])
            if domain.store.get_run(response["run_id"])["status"] == "queued" and item not in self.pending:
                future = domain.jobs.submit(response["run_id"])
                self.pending[item] = future
                future.add_done_callback(lambda f: self.run_finished(domain, item, f))
            return status, response

    def run_finished(self, domain, item, future):
        with self.lock:
            self.pending.pop(item, None)
        if future.cancelled():
            with domain.db.transaction() as conn:
                conn.execute("UPDATE runs SET status='failed',finished_at=?,error_json=? WHERE run_id=? AND status='queued'",
                             (self.now(), json.dumps(ApiError(503, "RUN_INTERRUPTED", "실행 전 서버 종료").body()), item[1]))

    def enqueue_delivery(self, domain, dispatch_id: str):
        with self.lock:
            with domain.db.connect() as conn:
                if not conn.execute("SELECT 1 FROM notifications WHERE dispatch_id=? AND delivery_status='pending'",
                                    (dispatch_id,)).fetchone():
                    return
            item = (domain.sid, dispatch_id)
            if item in self.sends:
                return
            if len(self.sends) >= 8:
                raise ApiError(429, "QUEUE_FULL", "전달 대기열 상한. 잠시 후 상태 확인 필요")
            future = self.deliveries.submit(domain.deliver, dispatch_id)
            self.sends[item] = future
            future.add_done_callback(lambda f: self.send_finished(domain, item, f))

    def send_finished(self, domain, item, future):
        with self.lock:
            self.sends.pop(item, None)
        if future.cancelled() or future.exception() is not None:
            with domain.db.transaction() as conn:
                conn.execute("UPDATE notifications SET delivery_status=CASE WHEN delivery_status='sending' "
                             "THEN 'unknown' ELSE 'failed' END,error_code='DELIVERY_INTERRUPTED' "
                             "WHERE dispatch_id=? AND delivery_status IN ('pending','sending')", (item[1],))
                conn.execute("UPDATE notification_attempts SET status='unknown',error_code='DELIVERY_INTERRUPTED',finished_at=? "
                             "WHERE finished_at IS NULL AND notification_id IN "
                             "(SELECT notification_id FROM notifications WHERE dispatch_id=?)", (self.now(), item[1]))

    def expire(self, sid: str):
        with self.registry.transaction() as conn:
            conn.execute("UPDATE sessions SET revoked=1,push_authorized=0 WHERE session_id=?", (sid,))
            conn.execute("DELETE FROM endpoint_owners WHERE session_id=?", (sid,))
        domain = self.domains.get(sid)
        if domain:
            domain.revoke_all()

    def cleanup(self):
        with self.registry.connect() as conn:
            rows = conn.execute("SELECT session_id,expires_at,ready FROM sessions").fetchall()
        for row in rows:
            if hasattr(self,"stop_maintenance") and self.stop_maintenance.is_set():
                break
            sid = row["session_id"]
            if row["ready"] and moment(row["expires_at"]) > self.clock():
                continue
            self.expire(sid)
            if row["ready"] and self.clock() < moment(row["expires_at"]) + timedelta(days=7):
                continue
            if any(s == sid for s, _ in self.pending) or any(s == sid for s, _ in self.sends):
                continue
            # Immutable data is retained as a whole file, then removed only after
            # expiry+7d and after our tasks end. Never drop v0.1 immutable triggers.
            directory = (self.root / "sessions").resolve()
            for suffix in (".sqlite3-wal", ".sqlite3-shm", ".sqlite3.lock", ".sqlite3"):
                target = directory / (sid + suffix)
                if target.resolve().parent != directory or not IDENTIFIER.fullmatch(sid):
                    raise RuntimeError("삭제 경로가 세션 보관 범위를 벗어남")
                target.unlink(missing_ok=True)
            self.domains.pop(sid, None)
            with self.registry.transaction() as conn:
                conn.execute("DELETE FROM sessions WHERE session_id=?", (sid,))
