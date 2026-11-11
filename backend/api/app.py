from __future__ import annotations

from contextlib import asynccontextmanager
import ipaddress
import secrets
import sqlite3
from typing import Any
from uuid import uuid4

from fastapi import Body, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware

from backend.api.contracts import ApiError, runtime_openapi, validate
from backend.api.fixture import FixtureReplay
from backend.api.engine_replay import EngineReplay
from backend.api.input_preflight import check_input
from backend.api.runs import ReplayJobs
from backend.api.settings import Settings
from backend.api.storage_checks import storage_checks
from backend.db.database import Database
from backend.db.store import Store


def create_app(settings: Settings | None = None, *, replay: FixtureReplay | None = None,
               workflow_replay=None, push_sender=None, workflow_clock=None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.db_path)
    store = Store(database)
    adapter = replay or (EngineReplay() if settings.run_mode == "engine" else FixtureReplay())
    workflow = None

    @asynccontextmanager
    async def lifespan(app):
        settings.check()
        jobs = None
        try:
            if not settings.public_enabled:
                database.acquire()
                database.initialize()
                jobs = ReplayJobs(store, adapter)
                jobs.recover()
                app.state.jobs = jobs
            if workflow is not None:
                workflow.start()
            yield
        finally:
            if workflow is not None:
                workflow.close()
            if jobs is not None:
                jobs.close()
            database.release()

    app = FastAPI(title="반입맞춤 로컬 모의 API", version="0.1.0", lifespan=lifespan,
                  swagger_ui_parameters={"persistAuthorization": False})
    app.state.store = store
    app.openapi = lambda: runtime_openapi(settings.run_mode)
    if settings.workflow_enabled:
        from backend.workflow.middleware import BodyLimit
        app.add_middleware(BodyLimit)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "DELETE"],
                       allow_credentials=settings.workflow_enabled,
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-CSRF-Token"],
                       expose_headers=["X-Request-ID", "Retry-After"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        request.state.request_id = uuid4().hex
        try:
            loopback = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            loopback = False
        public = settings.public_enabled
        v2 = settings.workflow_enabled and request.url.path.startswith("/v2/")
        origin = request.headers.get("origin")
        origin_allowed = origin in settings.cors_origins or origin == str(request.base_url).rstrip("/")
        if public and (request.url.hostname not in settings.public_hosts or request.url.scheme != "https"):
            response = JSONResponse(ApiError(400, "INVALID_PUBLIC_ORIGIN", "설정한 HTTPS Host로 접근해야 함").body(
                request.state.request_id), status_code=400)
        elif public and not v2 and request.url.path not in {"/health", "/docs", "/openapi.json", "/docs/oauth2-redirect"}:
            response = JSONResponse(ApiError(404, "HTTP_ERROR", "공개 모드에서 제공하지 않는 경로").body(
                request.state.request_id), status_code=404)
        elif not public and request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            response = JSONResponse(ApiError(400, "INVALID_HOST", "로컬 호스트 주소가 필요함").body(
                request.state.request_id), status_code=400)
        elif not public and not loopback:
            response = JSONResponse(ApiError(403, "LOCAL_DEMO_ONLY", "모의 API는 로컬 연결만 허용").body(
                request.state.request_id), status_code=403)
        elif (origin and not origin_allowed) or (v2 and request.method in {"POST", "DELETE"} and not origin_allowed):
            response = JSONResponse(ApiError(403, "ORIGIN_NOT_ALLOWED", "허용하지 않은 브라우저 출처").body(
                request.state.request_id), status_code=403)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError):
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 and not request.url.path.startswith("/v2/") else {}
        headers.update(error.headers)
        if error.code == "PUSH_RATE_LIMITED":
            headers.setdefault("Retry-After","60")
        return JSONResponse(error.body(request.state.request_id), status_code=error.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def request_error(request: Request, error: RequestValidationError):
        details = [{"path": "/request" if request.url.path.startswith("/v2/") else "/" + "/".join(map(str, item["loc"])),
                    "reason": "필수 요청 본문 또는 JSON 형식 확인 필요"} for item in error.errors()[:20]]
        return JSONResponse(ApiError(422, "REQUEST_VALIDATION_FAILED", "요청 형식 오류", details).body(
            request.state.request_id), status_code=422)

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request: Request, error: sqlite3.IntegrityError):
        return JSONResponse(ApiError(422, "DATA_INTEGRITY_FAILED", "ID·참조·중복·값 범위 확인 필요").body(
            request.state.request_id), status_code=422)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(request: Request, error: sqlite3.OperationalError):
        return JSONResponse(ApiError(503, "STORAGE_UNAVAILABLE", "저장소를 사용할 수 없음").body(
            request.state.request_id), status_code=503)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        return JSONResponse(ApiError(error.status_code, "HTTP_ERROR", "요청 경로·방식 확인 필요").body(
            request.state.request_id), status_code=error.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        return JSONResponse(ApiError(500, "INTERNAL_ERROR", "내부 처리 오류").body(
            request.state.request_id), status_code=500)

    def authenticate(request: Request) -> None:
        token = request.headers.get("authorization", "")
        scheme, _, value = token.partition(" ")
        if (scheme.lower() != "bearer" or not value.isascii()
                or not secrets.compare_digest(value, settings.demo_token)):
            raise ApiError(401, "AUTH_REQUIRED", "설정한 로컬 모의 Bearer 토큰이 필요함")

    def key(request: Request) -> str:
        value = request.headers.get("idempotency-key", "")
        if not value.strip():
            raise ApiError(422, "IDEMPOTENCY_KEY_REQUIRED", "모든 POST에 Idempotency-Key가 필요함")
        return value

    dependencies = [Depends(authenticate)]

    @app.post("/v1/scenarios", dependencies=dependencies)
    def register_scenario(request: Request, body: Any = Body(...)):
        validate("Snapshot", body)
        storage_checks(body)
        status, response = store.register(body, key(request))
        return JSONResponse(response, status_code=status)

    @app.get("/v1/scenarios/{scenario_id}", dependencies=dependencies)
    def get_scenario(scenario_id: str):
        return store.get_snapshot(scenario_id)

    @app.post("/v1/runs", dependencies=dependencies)
    def create_run(request: Request, body: Any = Body(...)):
        validate("RunRequest", body)
        def check(snapshot, methods):
            check_input(snapshot)
            adapter.check(snapshot, methods)
        status, response = store.create_run(body, key(request), check)
        app.state.jobs.submit(response["run_id"])
        return JSONResponse(response, status_code=status)

    @app.get("/v1/runs/{run_id}", dependencies=dependencies)
    def get_run(run_id: str):
        return store.get_run(run_id)

    @app.get("/v1/runs/{run_id}/results", dependencies=dependencies)
    def get_results(run_id: str):
        status, response = store.get_results(run_id)
        return JSONResponse(response, status_code=status, headers={"Retry-After": "1"} if status == 202 else None)

    @app.get("/v1/plans/{plan_id}", dependencies=dependencies)
    def get_plan(plan_id: str):
        return store.get_plan(plan_id)

    @app.post("/v1/plans/{plan_id}/approvals", dependencies=dependencies)
    def approve_plan(plan_id: str, request: Request, body: Any = Body(...)):
        validate("ApprovalRequest", body)
        status, response = store.approve(plan_id, body, key(request))
        return JSONResponse(response, status_code=status)

    @app.get("/health")
    def health():
        healthy = workflow is None or not getattr(workflow, "maintenance_failed", False)
        return JSONResponse({"status": "ok" if healthy else "degraded", "workflow_enabled": settings.workflow_enabled},
                            status_code=200 if healthy else 503)

    if settings.workflow_enabled:
        from backend.workflow.routes import install
        from fastapi.openapi.utils import get_openapi
        workflow = install(app, settings, replay=workflow_replay, sender=push_sender, clock=workflow_clock)
        def workflow_openapi():
            if app.openapi_schema is not None:
                return app.openapi_schema
            base = runtime_openapi(settings.run_mode)
            added = get_openapi(title="반입맞춤 담당자 대응", version="0.2.0", routes=[
                r for r in app.routes if getattr(r, "path", "").startswith("/v2/")])
            base["paths"].update(added["paths"])
            base.setdefault("components", {}).setdefault("schemas", {}).update(added.get("components", {}).get("schemas", {}))
            schemes = base["components"].setdefault("securitySchemes", {})
            schemes["DispatcherCookie"] = {"type": "apiKey", "in": "cookie", "name": "banipmatch_session"}
            schemes["RecipientCookie"] = {"type": "apiKey", "in": "cookie", "name": "banipmatch_recipient"}
            for path, operations in added["paths"].items():
                for verb in operations:
                    anonymous = verb == "post" and path in {"/v2/session", "/v2/recipient/session"}
                    base["paths"][path][verb]["security"] = [] if anonymous else [
                        {"RecipientCookie" if path.startswith("/v2/recipient/") else "DispatcherCookie": []}]
            base["info"]["version"] = "0.2.0"
            base["info"]["description"] += " v0.2는 격리된 모의 세션/수신자 흐름. 공개 모드에서 v0.1은 비활성. 실제 기기 검수 별도."
            from backend.workflow.openapi import augment
            app.openapi_schema = augment(base)
            return app.openapi_schema
        app.openapi = workflow_openapi

    return app
