"""N명이 한 네트워크에서 동시에 접속·예제 등록·B0~B3 계산을 요청하는 부하 시험(우리 서버 전용).

사용: python tools/load_test_sessions.py --base https://banipmatch.duckdns.org --users 30
결과: 성공/실패 수, 대기열로 기다린 횟수, 첫 결과까지 걸린 시간(중앙값·최대).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import http.cookiejar
import json
from pathlib import Path
import statistics
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "frontend/src/fixtures/demo-02-evening.synthetic.json"


def shifted(snapshot: dict, tag: str) -> dict:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    delta = now - datetime.fromisoformat(snapshot["as_of"].replace("Z", "+00:00"))

    def walk(node):
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, dict):
            return {k: ((datetime.fromisoformat(v.replace("Z", "+00:00")) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
                        if isinstance(v, str) and (k.endswith("_at") or k in ("as_of", "input_valid_until")) else walk(v))
                    for k, v in node.items()}
        return node
    out = walk(snapshot)
    out["scenario_id"] = "S-load-" + tag
    out["plan_id"] = "P-load-" + tag
    return out


def one(base: str, origin: str, index: int) -> dict:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    csrf = ""
    waits = 0

    def call(method, path, body=None, retry_busy=False):
        nonlocal waits
        for _ in range(60):
            data = json.dumps(body).encode() if body is not None else None
            req = urllib.request.Request(base + path, data=data, method=method, headers={
                "Origin": origin, "Content-Type": "application/json", "X-CSRF-Token": csrf,
                "Idempotency-Key": f"load-{index}-{path}-{method}"})
            try:
                with opener.open(req, timeout=60) as r:
                    return r.status, json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as e:
                payload = json.loads(e.read() or b"{}")
                if retry_busy and e.code == 429 and payload.get("code") == "QUEUE_FULL":
                    waits += 1
                    time.sleep(2)
                    continue
                return e.code, payload
        return 0, {"code": "GAVE_UP"}

    start = time.monotonic()
    status, sess = call("POST", "/v2/session", {})
    if status != 201:
        return {"ok": False, "stage": "session", "status": status, "code": sess.get("code")}
    csrf = sess["csrf_token"]
    snap = shifted(json.loads(DEMO.read_text(encoding="utf-8")), f"{index}-{uuid.uuid4().hex[:6]}")
    status, body = call("POST", "/v2/scenarios", snap)
    if status not in (200, 201):
        return {"ok": False, "stage": "register", "status": status, "code": body.get("code")}
    status, run = call("POST", "/v2/runs", {"scenario_id": snap["scenario_id"], "base_plan_version": 1,
                                            "methods": ["B0", "B1", "B2", "B3"], "time_limit_seconds": 10, "seed": 42}, retry_busy=True)
    if status != 202:
        return {"ok": False, "stage": "run", "status": status, "code": run.get("code")}
    for _ in range(300):
        status, state = call("GET", "/v2/runs/" + run["run_id"])
        if state.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(1)
    return {"ok": state.get("status") == "completed", "stage": "done", "status": state.get("status"),
            "seconds": round(time.monotonic() - start, 1), "waits": waits}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--origin")
    ap.add_argument("--users", type=int, default=30)
    a = ap.parse_args()
    origin = a.origin or a.base
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.users) as pool:
        results = list(pool.map(lambda i: one(a.base, origin, i), range(a.users)))
    ok = [r for r in results if r["ok"]]
    secs = [r["seconds"] for r in ok]
    print(json.dumps({
        "users": a.users, "completed": len(ok), "failed": [r for r in results if not r["ok"]][:5],
        "queue_waits": sum(r.get("waits", 0) for r in results),
        "seconds_median": statistics.median(secs) if secs else None, "seconds_max": max(secs) if secs else None,
        "wall_seconds": round(time.monotonic() - t0, 1)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
