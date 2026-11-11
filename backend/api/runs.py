"""실행 상태와 저장 관리. 실계산은 어댑터가 별도 프로세스로 실행."""
from concurrent.futures import ThreadPoolExecutor

from backend.api.contracts import ApiError, canonical, utc_now, validate
from backend.api.engine_replay import EngineExecutionError
from backend.api.result_integrity import check_result_integrity, verify_schedule
from backend.db.store import Store, insert


class ReplayJobs:
    def __init__(self, store: Store, replay, *, executor=None, before_execute=None):
        self.store, self.replay = store, replay
        self.owns_executor = executor is None
        self.executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="fixture-replay")
        self.before_execute = before_execute

    def recover(self) -> None:
        error = ApiError(503, "RUN_INTERRUPTED", "이전 서버 실행이 중단됨. 새 멱등키로 다시 요청 필요").body()
        with self.store.db.transaction() as conn:
            conn.execute("UPDATE runs SET status='failed', finished_at=?, error_json=? "
                         "WHERE status IN ('queued','running')", (utc_now(), canonical(error)))

    def submit(self, run_id: str) -> None:
        return self.executor.submit(self._execute, run_id)

    def close(self) -> None:
        if self.owns_executor:
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
            if self.before_execute:
                self.before_execute(run)
            results = self.replay.replay(snapshot, run["methods"], run["config"])
            if [r["method"] for r in results] != run["methods"]:
                raise ValueError("fixture method mismatch")
            for result in results:
                validate("MethodResult", result)
                if (result["result_origin"] != self.replay.result_origin or result["approval_eligible"]
                        or result["validation_status"] != "not_run"
                        or (result["result_origin"] == "illustrative_fixture" and result["objective_proven"])):
                    raise ValueError("독립 검사 전 승인 불가 결과만 저장 가능")
                if result["result_origin"] == "computed":
                    check_result_integrity(snapshot, result)
                    if verify_schedule(snapshot, result):
                        result["validation_status"] = "passed"
                        result["approval_eligible"] = True
                    elif result["method"] != "B0" and result["solution_status"] in {"HEURISTIC", "FEASIBLE", "OPTIMAL"}:
                        result["validation_status"] = "failed"
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
        except Exception as exc:
            # 예외 본문에는 요청·파일 경로·외부 응답이 포함될 수 있어 저장/반환하지 않음.
            reason = f"{exc.method}: {exc.reason}" if isinstance(exc, EngineExecutionError) else "실행 결과 처리 실패"
            error = ApiError(503, "RUN_EXECUTION_FAILED", "실행 실패",
                             [{"path": "/methods", "reason": reason}]).body()
            with self.store.db.transaction() as conn:
                conn.execute("UPDATE runs SET status='failed', finished_at=?, error_json=? WHERE run_id=?",
                             (utc_now(), canonical(error), run_id))
