"""Run the published draft's checks on a disposable copy, preserving its bytes."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    source = root / "docs" / "development" / "v0.1"
    with tempfile.TemporaryDirectory(prefix="banipmatch-check-") as directory:
        draft = Path(directory) / "v0.1"
        shutil.copytree(source, draft)
        qa = draft / "검수"
        for script, report_name in (
            ("validate_contracts.py", "계약_예제_검증.json"),
            ("validate_db.py", "DB검증.json"),
        ):
            report_path = qa / report_name
            # A stale published report must never stand in for this execution.
            report_path.unlink(missing_ok=True)
            subprocess.run([sys.executable, str(qa / script)], cwd=draft, check=True)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report.get("passed") is not True:
                raise RuntimeError(f"Check did not pass: {script}")
    print("Development contract/example/DB checks passed; published files unchanged.")
    print("This does not validate a running app, solver, or real-world performance.")


if __name__ == "__main__":
    main()
