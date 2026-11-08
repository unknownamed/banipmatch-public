"""배포된 JSON Schema를 직접 사용해 별도 필드 정의의 불일치를 방지."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "docs" / "development" / "v0.1"
SCHEMA = json.loads((DRAFT / "공통 규격" / "contracts.schema.json").read_text(encoding="utf-8"))
OPENAPI = json.loads((DRAFT / "공통 규격" / "openapi.json").read_text(encoding="utf-8"))


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list | None = None):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message
        self.details = details or []

    def body(self, request_id: str | None = None) -> dict:
        return {"request_id": request_id or uuid4().hex, "code": self.code,
                "message": self.message, "details": self.details}


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate(name: str, value: object) -> None:
    def finite(node):
        if isinstance(node, float) and not math.isfinite(node):
            raise ApiError(422, "INVALID_JSON_NUMBER", "NaN·Infinity는 JSON 값으로 허용하지 않음")
        if isinstance(node, dict):
            for child in node.values():
                finite(child)
        elif isinstance(node, list):
            for child in node:
                finite(child)
    finite(value)
    validator = Draft202012Validator(
        {"$schema": SCHEMA["$schema"], "$defs": SCHEMA["$defs"], "$ref": f"#/$defs/{name}"},
        format_checker=FormatChecker(),
    )
    errors = list(validator.iter_errors(value))
    if errors:
        # jsonschema의 원문 메시지는 요청 값 자체를 포함할 수 있어 반환하지 않음.
        details = [{"path": "/" + "/".join(map(str, e.absolute_path)),
                    "reason": f"계약 검사 실패: {e.validator}"} for e in errors[:20]]
        raise ApiError(422, "SCHEMA_VALIDATION_FAILED", f"{name} 형식이 공통 규격과 다름", details)


def runtime_openapi(run_mode: str = "fixture") -> dict:
    spec = deepcopy(OPENAPI)
    # Swagger를 연 현재 호스트·포트를 유지. 배포 예제 URL이나 허용 출처는 변경하지 않음.
    spec["servers"] = [{"url": "/", "description": "현재 로컬 API 서버"}]
    spec["info"]["description"] = (
        "로컬 모의 API. " + ("B0~B3 실계산 모드. " if run_mode == "engine" else "설명용 결과 재생 모드. ")
        + "단일 로컬 모의 주체의 내부 승인만 지원하며 운영 인증·외부 반영은 제공하지 않음."
    )
    for path, operations in spec["paths"].items():
        for operation in operations.values():
            operation["x-implementation-status"] = "local-demo"
    return spec
