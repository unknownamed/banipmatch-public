"""계산 요청 전 데이터 담당의 입력 의미 검사를 공통 오류로 변환."""
from backend.api.contracts import ApiError
from backend.data import validate_snapshot


def check_input(snapshot: dict) -> None:
    report = validate_snapshot(snapshot, source="stored-snapshot")
    if report.valid:
        return
    details = [{"path": issue.path or "/", "reason": f"{issue.code}: {issue.message}"}
               for issue in report.issues]
    codes = {issue.code for issue in report.issues}
    if codes & {"WINDOW_UNCONFIRMED", "CONFIRMATION_MISSING"}:
        raise ApiError(503, "WINDOW_UNCONFIRMED", "반입시간 변경 확인이 필요함", details)
    if codes & {"INPUT_MISSING", "TRAVEL_TIME_MISSING"}:
        raise ApiError(422, "INPUT_INCOMPLETE", "계산에 필요한 입력을 확인해야 함", details)
    raise ApiError(422, "INPUT_INVALID", "입력 관계를 확인해야 함", details)
