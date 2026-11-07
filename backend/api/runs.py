"""가벼운 설명용 응답 작업만 별도 스레드에서 실행. 실제 엔진 실행기가 아님."""
from concurrent.futures import ThreadPoolExecutor

from backend.api.contracts import ApiError, canonical, utc_now, validate
from backend.db.store import Store, insert


class ReplayJobs:
    def __init__(self, store: Store, replay):
        self.store, self.replay = store, replay
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fixture-replay")

    def recover(self) -> None:
        error = ApiError(503, "RUN_INTERRUPTED", "이전 서버 실행이 중단됨. 새 멱등키로 다시 요청 필요").body()
        with self.store.db.transaction() as conn:
            conn.execute("UPDATE runs SET status='failed', finished_at=?, error_json=? "
                         "WHERE status IN ('queued','running')", (utc_now(), canonical(error)))

    def submit(self, run_id: str) -> None:
        self.executor.submit(self._execute, run_id)

    def close(self) -> None:
        self.executor.shutdown(wait=True)

    def _execute(self, run_id: str) -> None:
        try:
            with self.store.db.transaction() as conn:
                claimed = conn.execute("UPDATE runs SET status='running', started_at=? "
                                       "WHERE run_id=? AND status='queued'", (utc_now(), run_id)).rowcount
                if claimed != 1:
                    return
                run = self.store.run(conn, run_id)
                snapshot = self.store.snapshot(conn, run["scenario_id"])
            results = self.replay.replay(snapshot, run["methods"], run["config"])
            if [r["method"] for r in results] != run["methods"]:
                raise ValueError("fixture method mismatch")
            for result in results:
                validate("MethodResult", result)
                if (result["result_origin"] != "illustrative_fixture" or result["approval_eligible"]
                        or result["objective_proven"] or result["validation_status"] != "not_run"):
                    raise ValueError("first phase only permits unapproved illustrative fixtures")
            with self.store.db.transaction() as conn:
                for result in results:
                    insert(conn, "method_results", {
                        "run_id": run_id, "method": result["method"], "scenario_id": run["scenario_id"],
                        "plan_id": run["plan_id"], "base_plan_version": run["base_plan_version"],
                        **{k: result[k] for k in ("result_origin", "solution_status", "objective_proven", "approval_eligible")},
                        "result_json": canonical(result),
                    })
                conn.execute("UPDATE runs SET status='completed', finished_at=? WHERE run_id=?",
                             (utc_now(), run_id))
        except Exception:
            # 예외 본문에는 요청·파일 경로·외부 응답이 포함될 수 있어 저장/반환하지 않음.
            error = ApiError(503, "RUN_EXECUTION_FAILED", "설명용 결과 작업 실패",
                             [{"path": "/methods", "reason": "이 실행의 모든 결과는 승인 불가"}]).body()
            with self.store.db.transaction() as conn:
                conn.execute("UPDATE runs SET status='failed', finished_at=?, error_json=? WHERE run_id=?",
                             (utc_now(), canonical(error), run_id))
