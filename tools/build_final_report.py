"""최종 보고서 HTML(docs/report/final/report.html)을 A4 PDF로 인쇄하고 빌드 기록을 남긴다.

PDF 옆에 <이름>.build.json을 만든다. 제출 묶음 도구(tools/build_submission.py)는
이 기록의 커밋·PDF 해시·입력 파일 해시가 묶을 커밋과 같은지 확인한다.
외부 전송·배포는 하지 않는다(웹 글꼴을 내려받기 위한 읽기만 한다).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs/report/final/report.html"
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")


def text_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def inputs() -> list[Path]:
    html = REPORT.read_text(encoding="utf-8")
    images = [(REPORT.parent / src).resolve() for src in re.findall(r'src="([^"]+)"', html)
              if not src.startswith(("http:", "https:", "data:"))]
    return [Path(__file__).resolve(), REPORT, *sorted(set(images))]


def render(output: Path, chrome: Path) -> dict:
    from pypdf import PdfReader

    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    files = inputs()
    missing = [p for p in files if not p.exists()]
    if missing:
        raise FileNotFoundError(", ".join(str(p) for p in missing))
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([str(chrome), "--headless=new", "--disable-gpu", f"--user-data-dir={profile}",
                        "--no-pdf-header-footer", "--virtual-time-budget=15000",
                        f"--print-to-pdf={output}", REPORT.as_uri()], check=True, capture_output=True)
    pages = len(PdfReader(output).pages)
    if not 1 <= pages <= 20:
        raise ValueError(f"보고서는 20쪽 이내여야 한다: {pages}쪽")
    meta = {"stage": "final", "source_commit": commit, "page_count": pages,
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "pdf_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "input_hash_convention": "file bytes with CRLF normalized to LF",
            "inputs": {p.relative_to(ROOT).as_posix(): text_hash(p) for p in files},
            "renderer": "Chrome headless print-to-pdf (A4, CSS @page)",
            "deployment_or_delivery_performed": False}
    output.with_suffix(".build.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                                                 encoding="utf-8", newline="\n")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--chrome", type=Path, default=CHROME)
    meta = render(parser.parse_args().output.resolve(), parser.parse_args().chrome)
    print(json.dumps({k: meta[k] for k in ("source_commit", "page_count", "pdf_sha256")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
