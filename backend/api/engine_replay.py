"""로컬 모의 입력의 B0~B3 계산을 별도 자식 프로세스에서 실행."""
import json
import os
import subprocess
import sys

from backend.api.contracts import ApiError, ROOT


class EngineExecutionError(Exception):
    def __init__(self, method: str, reason: str):
        self.method, self.reason = method, reason
        super().__init__(reason)


class EngineReplay:
    result_origin = "computed"

    def check(self, snapshot: dict, methods: list[str]) -> None:
        if not set(methods) <= {"B0", "B1", "B2", "B3"}:
            raise ApiError(422, "METHOD_NOT_IMPLEMENTED", "현재 실계산은 B0~B3만 지원함")

    def replay(self, snapshot: dict, methods: list[str], config: dict) -> list[dict]:
        self.check(snapshot, methods)
        script = ("import json,sys; from backend.engine import solve; "
                  "d=json.load(sys.stdin); "
                  "print(json.dumps(solve(d['snapshot'], d['method'], d['config']), ensure_ascii=False))")
        results = []
        for method in methods:
            try:
                child = subprocess.run(
                    [sys.executable, "-X", "utf8", "-c", script], cwd=ROOT,
                    input=json.dumps({"snapshot": snapshot, "method": method, "config": config}, ensure_ascii=False),
                    text=True, encoding="utf-8", capture_output=True, check=True,
                    timeout=config["time_limit_seconds"] + 5,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                results.append(json.loads(child.stdout))
            except subprocess.TimeoutExpired as exc:
                raise EngineExecutionError(method, "실행 제한시간 초과") from exc
            except (subprocess.SubprocessError, ValueError) as exc:
                raise EngineExecutionError(method, "엔진 실행 또는 결과 처리 실패") from exc
        return results
