"""로컬 입력 준비 CLI. HTTP 등록·계산·외부 수집을 실행하지 않는다."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from .inputs import _read_json_document, load_jobs_csv, load_snapshot_json
from .validation import InputIssue, InputReport


def _write_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 기존 입력·이전 결과·심볼릭 링크를 덮어쓰지 않는다.
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="v0.1 로컬 데이터 검사·작업 CSV 변환")
    commands = parser.add_subparsers(dest="command", required=True)
    json_command = commands.add_parser("validate-json", help="전체 Snapshot JSON 검사")
    json_command.add_argument("input", type=Path)
    csv_command = commands.add_parser("import-jobs", help="작업 CSV + 문맥·출처 JSON 결합")
    csv_command.add_argument("input", type=Path)
    csv_command.add_argument("--context", type=Path, required=True)
    csv_command.add_argument("--evidence", type=Path, required=True)
    for command in (json_command, csv_command):
        command.add_argument("--output", type=Path, help="정상 스냅샷을 새 파일로 저장")
        command.add_argument("--report", type=Path, help="오류·검사 결과를 새 JSON 파일로 저장")
    args = parser.parse_args(argv)

    sources = [args.input]
    if args.command == "import-jobs":
        sources.extend([args.context, args.evidence])
    destinations = [path for path in (args.output, args.report) if path is not None]
    try:
        resolved = [path.resolve() for path in destinations]
        if (len(resolved) != len(set(resolved))
                or set(resolved) & {path.resolve() for path in sources}):
            raise ValueError("Output aliases input or report")
        if any(path.exists() or path.is_symlink() for path in destinations):
            raise FileExistsError("Output already exists")
    except (OSError, ValueError):
        print(json.dumps({"valid": False, "input_sha256": None, "issues": [
            asdict(InputIssue("OUTPUT_PATH", "", "출력은 입력·보고서와 다른 새 경로여야 합니다. 기존 파일은 보존했습니다.")),
        ]}, ensure_ascii=True))
        return 1

    if args.command == "validate-json":
        report = load_snapshot_json(args.input)
    else:
        context, context_issues = _read_json_document(args.context)
        evidence, evidence_issues = _read_json_document(args.evidence)
        if context_issues or evidence_issues:
            report = InputReport(None, context_issues + evidence_issues)
        else:
            report = load_jobs_csv(
                args.input, context=context, evidence=evidence,
                context_source=args.context.name, evidence_source=args.evidence.name,
            )
    digest = None
    if report.valid:
        canonical = json.dumps(report.snapshot, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
    summary = {"valid": report.valid, "input_sha256": digest,
               "issues": [asdict(issue) for issue in report.issues]}
    try:
        if report.valid and args.output:
            _write_new(args.output, report.snapshot)
        if args.report:
            _write_new(args.report, summary)
    except OSError:
        summary = {"valid": False, "input_sha256": None, "issues": [
            asdict(InputIssue("OUTPUT_WRITE", "", "출력 파일을 저장하지 못했습니다. 종료코드와 각 출력 경로를 확인하세요.")),
        ]}
        print(json.dumps(summary, ensure_ascii=True))
        return 1
    print(json.dumps(summary, ensure_ascii=True))
    return 0 if report.valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
