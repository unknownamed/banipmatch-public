"""Read one authorized local sample; print metadata only, never provider rows."""
import argparse
import json
from pathlib import Path

from .adapters import MAX_BYTES
from .service import ReferenceReader, SampleResponse


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "인수 오류: --help의 형식을 확인하세요.\n")


def metadata(view: dict) -> dict:
    """Allowlist output: no identifiers, raw fields or exception strings."""
    current = view["current"]
    return {key: view[key] for key in (
        "model_version", "source", "source_ref", "kind", "checked_at", "last_attempt",
        "last_success", "engine_conversion", "approval_eligible", "automatic_mock_fallback"
    )} | {"current": None if current is None else {
        key: current[key] for key in ("status", "received_at", "receipt_provenance", "freshness",
                                     "row_count", "reported_count", "excluded_rows", "blockers")},
          "cache_enabled": False}


def main(argv=None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--source", choices=("hjnc", "road"), required=True)
    parser.add_argument("--kind", choices=("reference", "simulated"), required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--received-at", required=True)
    parser.add_argument("--sample-permission-ref", required=True)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args(argv)
    try:
        direction = (args.start, args.end) if args.source == "road" else None
        if args.source != "road" and (args.start is not None or args.end is not None):
            raise ValueError("unexpected direction")
        reader = ReferenceReader(args.source, kind=args.kind,
                                 sample_permission_ref=args.sample_permission_ref, direction=direction)
        # Bounded read even if the path grows between stat and read.
        with args.input.open("rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
        result = reader.ingest(SampleResponse(raw, args.received_at))
    except (OSError, ValueError, TypeError):
        print("표본 읽기 실패: 파일·수신시각·권한 근거·방향을 확인하세요. 원문은 출력하지 않습니다.")
        return 2
    print(json.dumps(metadata(result), ensure_ascii=False, indent=2))
    return 2 if result["last_attempt"]["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
