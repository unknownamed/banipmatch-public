"""동일 모의 사례의 실계산·독립 검사·내부 승인 근거를 로컬 API에서 저장."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from backend.api.contracts import DRAFT, digest, validate
from backend.api.input_preflight import check_input

SOURCE = DRAFT / "예제 데이터" / "01_snapshot.json"
METHODS = ["B0", "B1", "B2", "B3"]


def prepare_snapshot(source: dict, anchor: datetime, suffix: str) -> dict:
    if source["data_mode"] != "simulated":
        raise ValueError("모의 입력만 시연 시각으로 이동 가능")
    if anchor.tzinfo is None:
        raise ValueError("시연 기준시각에 시간대 필요")
    anchor = anchor.astimezone(timezone.utc).replace(second=0, microsecond=0)
    original = datetime.fromisoformat(source["as_of"].replace("Z", "+00:00"))
    delta = anchor - original

    def shift(node):
        if isinstance(node, dict):
            return {key: (datetime.fromisoformat(value.replace("Z", "+00:00")) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if isinstance(value, str) and (key.endswith("_at") or key in {"as_of", "input_valid_until"})
                    else shift(value) for key, value in node.items()}
        if isinstance(node, list):
            return [shift(value) for value in node]
        return node

    result = shift(deepcopy(source))
    result.update(scenario_id=f"S-demo-{suffix}", plan_id=f"P-demo-{suffix}")
    validate("Snapshot", result)
    check_input(result)
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_client(base_url: str, token: str):
    url = urlsplit(base_url)
    if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}
            or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}):
        raise ValueError("로컬 HTTP API 주소만 허용")
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(method, path, body=None, key=None):
        headers = {"Authorization": f"Bearer {token}"}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Idempotency-Key": key or uuid4().hex})
        request = Request(base_url.rstrip("/") + path, method=method, headers=headers,
                          data=json.dumps(body).encode("utf-8") if body is not None else None)
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)
    return call


POLL_SECONDS = 1.0
DEFAULT_TIME_LIMIT = 10


def run_demo(call, snapshot: dict, *, time_limit=DEFAULT_TIME_LIMIT, seed=42, record=None, review_only=False):
    """call은 헤더를 저장하지 않는 HTTP 경계. 서버 시계와 원본 자료는 변경하지 않음."""
    evidence = []

    def save_step(step):
        evidence.append(step)
        if record:
            record(step)

    def expect(method, path, body, status, key=None, code=None):
        actual, response = call(method, path, body, key)
        save_step({"method": method, "path": path, "request": body,
                   "status": actual, "response": response, "idempotency_key": key})
        if actual != status or (code is not None and response.get("code") != code):
            raise ValueError(f"시연 단계 실패: {method} {path}, HTTP {actual}")
        return response

    sid, pid = snapshot["scenario_id"], snapshot["plan_id"]
    registered = expect("POST", "/v1/scenarios", snapshot, 201, f"{sid}-register")
    if registered["input_sha256"] != digest(snapshot):
        raise ValueError("등록 입력 해시 불일치")
    saved = expect("GET", f"/v1/scenarios/{sid}", None, 200)
    if saved != snapshot:
        raise ValueError("저장 입력 불일치")
    request = {"scenario_id": sid, "base_plan_version": snapshot["base_plan_version"],
               "methods": METHODS, "time_limit_seconds": time_limit, "seed": seed}
    run = expect("POST", "/v1/runs", request, 202, f"{sid}-run")
    validate("Run", run)
    if expect("POST", "/v1/runs", request, 202, f"{sid}-run") != run:
        raise ValueError("동일 실행 요청의 멱등 응답 불일치")
    deadline = time.monotonic() + len(METHODS) * (time_limit + 5) + 10
    path = f"/v1/runs/{run['run_id']}/results"
    while True:
        status, result = call("GET", path, None, None)
        if status != 202:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("결과 조회 대기시간 초과")
        # 서버의 Retry-After: 1에 맞춰 조회 부하를 줄임. 짧은 프로세스 제한의 성공을 보장하는 것은 아님.
        time.sleep(POLL_SECONDS)
    save_step({"method": "GET", "path": path, "request": None, "status": status, "response": result})
    if status != 200:
        raise ValueError(f"결과 조회 실패: HTTP {status}")
    validate("Results", result)
    if (result["run_id"] != run["run_id"] or result["scenario_id"] != sid
            or result["input_sha256"] != digest(snapshot) or result["base_plan_version"] != snapshot["base_plan_version"]
            or [r["method"] for r in result["results"]] != METHODS
            or any(r["result_origin"] != "computed" for r in result["results"])):
        raise ValueError("동일 입력의 실계산 결과가 아님")
    frozen_ids = {job["job_id"] for job in snapshot["jobs"] if job["frozen"]}
    fixed = {row["job_id"]: row for row in snapshot["baseline_assignments"] if row["job_id"] in frozen_ids}
    for method_result in result["results"]:
        actual_fixed = {row["job_id"]: row for row in method_result["assignments"] if row["job_id"] in frozen_ids}
        if actual_fixed != fixed:
            raise ValueError("고정 작업 원안 보존 실패")
    chosen = next(r for r in result["results"] if r["method"] == "B3")
    if chosen["validation_status"] != "passed" or not chosen["approval_eligible"]:
        raise ValueError("B3 독립 검사 또는 승인 적격성 확인 실패")
    required = sorted(set(chosen["unassigned_job_ids"]) | {i["job_id"] for i in chosen["issues"]
                      if i["code"] == "FIXED_RESIDUAL_RISK" and i["job_id"] is not None})
    if review_only:
        plan = expect("GET", f"/v1/plans/{pid}", None, 200)
        validate("Plan", plan)
        if plan["version"] != run["base_plan_version"] or plan["approval_id"] is not None:
            raise ValueError("승인 전 계획 상태 불일치")
        return {"data_mode": "simulated", "scenario_id": sid, "run_id": run["run_id"], "plan_id": pid,
                "input_sha256": digest(snapshot), "config": run["config"], "approval": None,
                "acknowledged_job_ids": required, "results": result, "current_plan": plan, "http_steps": evidence}
    approval_request = {"run_id": run["run_id"], "method": "B3",
                        "expected_version": run["base_plan_version"], "acknowledged_job_ids": required}
    approval_path = f"/v1/plans/{pid}/approvals"
    if required:
        expect("POST", approval_path, {**approval_request, "acknowledged_job_ids": []}, 422,
               f"{sid}-missing-ack", "ACKNOWLEDGEMENT_REQUIRED")
    approval = expect("POST", approval_path, approval_request, 201, f"{sid}-approve")
    validate("Approval", approval)
    if (approval["plan_id"] != pid or approval["run_id"] != run["run_id"] or approval["method"] != "B3"
            or approval["version"] != run["base_plan_version"] + 1 or approval["external_actions_performed"] is not False):
        raise ValueError("내부 승인 응답 불일치")
    if expect("POST", approval_path, approval_request, 201, f"{sid}-approve") != approval:
        raise ValueError("동일 승인 요청의 멱등 응답 불일치")
    expect("POST", approval_path, approval_request, 409, f"{sid}-old-version", "PLAN_VERSION_CONFLICT")
    plan = expect("GET", f"/v1/plans/{pid}", None, 200)
    validate("Plan", plan)
    if (plan["plan_id"] != pid or plan["scenario_id"] != sid or plan["approval_id"] != approval["approval_id"]
            or plan["version"] != approval["version"] or plan["assignments"] != chosen["assignments"]
            or plan["unassigned_job_ids"] != chosen["unassigned_job_ids"]):
        raise ValueError("승인 결과와 현재 계획 불일치")
    return {"data_mode": "simulated", "scenario_id": sid, "run_id": run["run_id"], "plan_id": pid,
            "input_sha256": digest(snapshot), "config": run["config"], "approval": approval,
            "acknowledged_job_ids": required, "results": result, "current_plan": plan, "http_steps": evidence}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, help="새 증거 디렉터리. 기존 디렉터리 덮어쓰기 불가")
    parser.add_argument("--time-limit", type=int, choices=range(1, 121), default=DEFAULT_TIME_LIMIT)
    parser.add_argument("--review-only", action="store_true", help="계산·검사 후 멈추고 실제 승인은 화면에서 수행")
    args = parser.parse_args(argv)
    token = os.environ.get("BANIPMATCH_DEMO_TOKEN", "")
    if not token:
        parser.error("서버와 같은 BANIPMATCH_DEMO_TOKEN 설정 필요")
    output = None
    try:
        call = http_client(args.base_url, token)
        source = json.loads(SOURCE.read_text(encoding="utf-8"))
        suffix = uuid4().hex[:12]
        snapshot = prepare_snapshot(source, datetime.now(timezone.utc), suffix)
        output = args.output or Path("local/demo-evidence") / suffix
        output.mkdir(parents=True, exist_ok=False)
        (output / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest = {"data_mode": "simulated", "source": "docs/development/v0.1/예제 데이터/01_snapshot.json",
                    "source_sha256": digest(source), "input_sha256": digest(snapshot),
                    "source_as_of": source["as_of"], "demo_as_of": snapshot["as_of"],
                    "time_shift_seconds": int((datetime.fromisoformat(snapshot["as_of"].replace("Z", "+00:00"))
                                               - datetime.fromisoformat(source["as_of"].replace("Z", "+00:00"))).total_seconds()),
                    "assumptions": "모든 업무·출처 시각을 같은 간격으로 이동한 모의 자료. 서버 시계 변경 없음. 현장 효과·운영 인증 검증 아님."}
        root = SOURCE.parents[4]
        sources = sorted((root / "backend").rglob("*.py")) + [Path(__file__).resolve()]
        manifest["local_source_sha256"] = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                                           for path in sources}
        try:
            solver_version = version("ortools")
        except PackageNotFoundError:
            solver_version = None
        manifest["client_environment"] = {"python": platform.python_version(), "ortools": solver_version}
        manifest["environment_limit"] = "소스와 환경은 실행 도구 측 기준. 연결한 서버와 같은 체크아웃·환경인지 별도 확인 필요."
        (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        def record(step):
            with (output / "http_steps.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(step, ensure_ascii=False) + "\n")
        try:
            result = run_demo(call, snapshot, time_limit=args.time_limit, record=record, review_only=args.review_only)
        except Exception:
            (output / "failed.json").write_text('{"passed": false}', encoding="utf-8")
            raise
        (output / "evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"passed": True, "output": str(output), "scenario_id": result["scenario_id"],
                          "run_id": result["run_id"], "plan_version": result["current_plan"]["version"],
                          "approval_performed": result["approval"] is not None}, ensure_ascii=True))
        return 0
    except Exception as error:
        # 예외 원문은 요청·인증정보를 포함할 수 있어 출력하지 않음.
        print(json.dumps({"passed": False, "error_type": type(error).__name__,
                          "output": str(output) if output else None,
                          "message": "실계산 모드·로컬 서버·입력 유효기간·출력 경로 확인 필요"}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
