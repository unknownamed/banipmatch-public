"""실행 중인 로컬 모의 서버의 등록→조회→실행→결과→승인 차단 확인."""
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    token = os.environ.get("BANIPMATCH_DEMO_TOKEN", "")
    if not token:
        raise SystemExit("서버와 같은 BANIPMATCH_DEMO_TOKEN 설정 필요")

    def call(method: str, path: str, body=None):
        headers = {"Authorization": f"Bearer {token}"}
        if body is not None:
            headers.update({"Content-Type": "application/json", "Idempotency-Key": uuid4().hex})
        request = Request("http://127.0.0.1:8000" + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers=headers, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    examples = ROOT / "docs" / "development" / "v0.1" / "예제 데이터"
    snapshot = json.loads((examples / "01_snapshot.json").read_text(encoding="utf-8"))
    suffix = uuid4().hex[:12]
    snapshot.update(scenario_id=f"S-{suffix}", plan_id=f"P-{suffix}")
    status, registered = call("POST", "/v1/scenarios", snapshot)
    if status != 201:
        raise RuntimeError(f"등록 실패: HTTP {status}, {registered.get('code')}")
    status, saved = call("GET", f"/v1/scenarios/{registered['scenario_id']}")
    if status != 200 or saved != snapshot:
        raise RuntimeError("입력 조회 불일치")
    run_request = json.loads((examples / "02_run_request.json").read_text(encoding="utf-8"))
    run_request["scenario_id"] = snapshot["scenario_id"]
    status, run = call("POST", "/v1/runs", run_request)
    if status != 202:
        raise RuntimeError(f"실행 등록 실패: HTTP {status}, {run.get('code')}")
    deadline = time.monotonic() + 10
    while True:
        status, results = call("GET", f"/v1/runs/{run['run_id']}/results")
        if status != 202 or time.monotonic() > deadline:
            break
        time.sleep(0.1)
    if status != 200:
        raise RuntimeError(f"결과 조회 실패: HTTP {status}, {results.get('code')}")
    approval = {"run_id": run["run_id"], "method": "B3", "expected_version": 1,
                "acknowledged_job_ids": ["J3"]}
    status, error = call("POST", f"/v1/plans/{snapshot['plan_id']}/approvals", approval)
    if status != 422 or error.get("code") != "RESULT_NOT_COMPUTED":
        raise RuntimeError("설명용 결과 승인 차단 실패")
    print(json.dumps({"scenario_id": snapshot["scenario_id"], "run_id": run["run_id"],
                      "methods": [r["method"] for r in results["results"]],
                      "result_origin": "illustrative_fixture", "approval_blocked": True}, indent=2))


if __name__ == "__main__":
    main()
