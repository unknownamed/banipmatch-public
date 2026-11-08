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


def create_app(settings: Settings | None = None, *, replay: FixtureReplay | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.db_path)
    store = Store(database)
    adapter = replay or (EngineReplay() if settings.run_mode == "engine" else FixtureReplay())

    @asynccontextmanager
    async def lifespan(app):
        settings.check()
        database.acquire()
        jobs = None
        try:
            database.initialize()
            jobs = ReplayJobs(store, adapter)
            jobs.recover()
            app.state.jobs = jobs
            yield
        finally:
            if jobs is not None:
                jobs.close()
            database.release()

    app = FastAPI(title="반입맞춤 로컬 모의 API", version="0.1.0", lifespan=lifespan,
                  swagger_ui_parameters={"persistAuthorization": False})
    app.state.store = store
    app.openapi = lambda: runtime_openapi(settings.run_mode)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
                       expose_headers=["X-Request-ID", "Retry-After"])

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        request.state.request_id = uuid4().hex
        try:
            loopback = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
        except ValueError:
            loopback = False
        if request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            response = JSONResponse(ApiError(400, "INVALID_HOST", "로컬 호스트 주소가 필요함").body(
                request.state.request_id), status_code=400)
        elif not loopback:
            response = JSONResponse(ApiError(403, "LOCAL_DEMO_ONLY", "모의 API는 로컬 연결만 허용").body(
                request.state.request_id), status_code=403)
        elif ((origin := request.headers.get("origin"))
              and origin not in settings.cors_origins
              and origin != str(request.base_url).rstrip("/")):
            response = JSONResponse(ApiError(403, "ORIGIN_NOT_ALLOWED", "허용하지 않은 브라우저 출처").body(
                request.state.request_id), status_code=403)
        else:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError):
        headers = {"WWW-Authenticate": "Bearer"} if error.status == 401 else None
        return JSONResponse(error.body(request.state.request_id), status_code=error.status, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def request_error(request: Request, error: RequestValidationError):
        details = [{"path": "/" + "/".join(map(str, item["loc"])),
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

    return app
