"""고정 입력에 대한 설명용 응답 어댑터. 계산 엔진이 아님."""
from copy import deepcopy
import json

from backend.api.contracts import ApiError, DRAFT, canonical


class FixtureReplay:
    result_origin = "illustrative_fixture"
    def __init__(self):
        examples = DRAFT / "예제 데이터"
        self.snapshot = json.loads((examples / "01_snapshot.json").read_text(encoding="utf-8"))
        self.results = json.loads((examples / "04_results_설명용.json").read_text(encoding="utf-8"))["results"]

    @staticmethod
    def comparable(snapshot: dict) -> dict:
        # 저장 ID만 바꿀 수 있음. 시각·원안·근거 등 모든 업무 입력은 동일해야 함.
        return {k: v for k, v in snapshot.items() if k not in ("scenario_id", "plan_id")}

    def check(self, snapshot: dict, methods: list[str]) -> None:
        if snapshot["change"]["verification"] != "confirmed" or any(
            w["verification"] != "confirmed" for w in snapshot["windows"]
        ):
            raise ApiError(503, "WINDOW_UNCONFIRMED", "반입시간 변경 확인이 필요함")
        if any(j[k] is None for j in snapshot["jobs"]
               for k in ("ready_at", "gross_weight_kg", "service_minutes")):
            raise ApiError(422, "INPUT_INCOMPLETE", "미확인 입력이 있어 설명용 결과를 적용할 수 없음")
        if canonical(self.comparable(snapshot)) != canonical(self.comparable(self.snapshot)):
            raise ApiError(422, "DEMO_INPUT_MISMATCH", "설명용 결과는 공통 예제 01의 동일 입력에만 제공됨")
        if not set(methods) <= {r["method"] for r in self.results}:
            raise ApiError(422, "DEMO_METHOD_UNAVAILABLE", "제공된 설명용 결과는 B0·B3뿐임")

    def replay(self, snapshot: dict, methods: list[str], config: dict) -> list[dict]:
        self.check(snapshot, methods)
        indexed = {r["method"]: r for r in self.results}
        return [deepcopy(indexed[method]) for method in methods]
