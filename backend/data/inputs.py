"""기존 JSON 스냅샷과 작업 CSV를 읽는다. 외부 호출·원본 덮어쓰기는 없다."""
from __future__ import annotations

from copy import deepcopy
import csv
from dataclasses import replace
import json
from pathlib import Path
import re
from typing import Any

from .validation import InputIssue, InputReport, contract_validator, validate_snapshot

JOB_COLUMNS = (
    "job_id", "voyage_id", "origin_id", "terminal_id", "return_location_id",
    "ready_at", "gross_weight_kg", "equipment_type", "service_minutes",
    "state", "frozen", "freeze_reason",
)
INTEGER_COLUMNS = frozenset({"gross_weight_kg", "service_minutes"})
NULLABLE_COLUMNS = frozenset({"ready_at", "gross_weight_kg", "service_minutes", "freeze_reason"})


class _DuplicateKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey("Duplicate JSON key")
        result[key] = value
    return result


def load_snapshot_json(path: str | Path) -> InputReport:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
    except _DuplicateKey:
        return InputReport(None, (InputIssue("JSON_DUPLICATE_KEY", "", "JSON 객체의 키가 중복됩니다.", path.name),))
    except json.JSONDecodeError as error:
        return InputReport(None, (InputIssue("JSON_INVALID", "", "JSON 문법이 올바르지 않습니다.", path.name, error.lineno),))
    except (OSError, UnicodeError):
        return InputReport(None, (InputIssue("FILE_READ", "", "UTF-8 파일을 읽을 수 없습니다.", path.name),))
    except ValueError:
        return InputReport(None, (InputIssue("JSON_INVALID", "", "처리 가능한 JSON 숫자 범위를 초과했습니다.", path.name),))
    return validate_snapshot(value, source=path.name)


def load_jobs_csv(path: str | Path, *, context: dict, evidence: dict) -> InputReport:
    """context의 jobs를 CSV 전체로 교체한다. 새 출처는 호출자가 명시해야 한다."""
    path = Path(path)
    if not isinstance(context, dict):
        return InputReport(None, (InputIssue("CONTEXT_INVALID", "", "전체 스냅샷 문맥이 필요합니다.", path.name),))
    if not contract_validator("Evidence").is_valid(evidence):
        return InputReport(None, (InputIssue("EVIDENCE_INVALID", "/evidence", "CSV 자료의 출처·유형·시각을 명시해야 합니다.", path.name),))
    jobs = []
    rows: list[int] = []
    issues = []
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            header = next(reader, [])
            if len(header) != len(set(header)) or set(header) != set(JOB_COLUMNS):
                return InputReport(None, (InputIssue("CSV_HEADER", "", "작업 템플릿과 동일한 열이 중복 없이 필요합니다.", path.name, 1),))
            while True:
                row_number = reader.line_num + 1
                values = next(reader, None)
                if values is None:
                    break
                if not values:
                    continue
                if len(values) != len(header):
                    issues.append(InputIssue("CSV_COLUMNS", "", "행의 열 수가 헤더와 다릅니다.", path.name, row_number))
                    continue
                job: dict[str, Any] = dict(zip(header, values))
                for key, raw in list(job.items()):
                    if raw == "" and key in NULLABLE_COLUMNS:
                        job[key] = None
                    elif key in INTEGER_COLUMNS:
                        if re.fullmatch(r"-?[0-9]+", raw):
                            try:
                                job[key] = int(raw)
                            except ValueError:
                                issues.append(InputIssue("CSV_INTEGER", "/" + key, "처리 가능한 범위의 정수가 필요합니다.", path.name, row_number))
                        else:
                            issues.append(InputIssue("CSV_INTEGER", "/" + key, "정수 값이 필요합니다.", path.name, row_number))
                    elif key == "frozen":
                        if raw.lower() in ("true", "false"):
                            job[key] = raw.lower() == "true"
                        else:
                            issues.append(InputIssue("CSV_BOOLEAN", "/frozen", "True 또는 False가 필요합니다.", path.name, row_number))
                job["evidence"] = deepcopy(evidence)
                jobs.append(job)
                rows.append(row_number)
    except (OSError, UnicodeError):
        return InputReport(None, (InputIssue("FILE_READ", "", "UTF-8 파일을 읽을 수 없습니다.", path.name),))
    except csv.Error:
        return InputReport(None, (InputIssue("CSV_INVALID", "", "CSV 문법이 올바르지 않습니다.", path.name, reader.line_num),))
    if issues:
        return InputReport(None, tuple(issues))
    snapshot = deepcopy(context)
    snapshot["jobs"] = jobs
    report = validate_snapshot(snapshot)
    mapped = []
    for issue in report.issues:
        parts = issue.path.split("/")
        if len(parts) > 2 and parts[1] == "jobs" and parts[2].isdigit():
            mapped.append(replace(issue, source=path.name, row=rows[int(parts[2])]))
        else:
            # 문맥 오류를 CSV 행의 오류로 잘못 표시하지 않는다.
            mapped.append(issue)
    return InputReport(report.snapshot, tuple(mapped))
