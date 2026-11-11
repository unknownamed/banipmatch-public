"""Export a committed, review-stage source/data bundle without local secrets or Git.

No server, network request, solver rerun, or deployment is performed.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "submission-manifest.json"
EVALUATION = "docs/experiments/engine-evaluation-2026-11-08"
SOURCE_COMMIT = "0d2640bec9886fe344166809123bc9a2cc19bb92"
ALLOWED_ROOTS = {"backend", "frontend", "tools", "tests", "docs", ".github", ".cursor"}
ALLOWED_FILES = {".env.example", ".gitattributes", ".gitignore", "AGENTS.md", "CLAUDE.md",
                 "CONTRIBUTING.md", "README.md", "pytest.ini", "requirements.txt",
                 "requirements-dev.txt", "requirements-report.txt", "requirements-aisstream.txt"}
DENIED_PARTS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
                "local", "tmp", "private", "raw", "secrets", "credentials", "dist", "dist-showcase"}
DENIED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".log", ".pyc", ".pyo"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_path(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or "\\" in name or path.is_absolute() or ":" in name
            or any(p in {"", ".", ".."} for p in name.split("/"))):
        raise ValueError(f"Unsafe archive path: {name}")
    return name


def allowed_source(name: str) -> bool:
    path = PurePosixPath(safe_path(name))
    if any(p.lower() in DENIED_PARTS for p in path.parts):
        return False
    if path.suffix.lower() in DENIED_SUFFIXES or path.name.endswith((".db-wal", ".db-shm")):
        return False
    if path.name.lower().startswith(".env") and path.name != ".env.example":
        return False
    return name in ALLOWED_FILES or (len(path.parts) > 1 and path.parts[0] in ALLOWED_ROOTS)


def git_bytes(repo: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=repo)


def collect_sources(repo: Path, revision: str) -> tuple[str, str, dict[str, bytes], list[str]]:
    commit = git_bytes(repo, "rev-parse", "--verify", revision + "^{commit}").decode().strip()
    tree = git_bytes(repo, "rev-parse", commit + "^{tree}").decode().strip()
    blobs: dict[str, bytes] = {}
    excluded = []
    with tarfile.open(fileobj=io.BytesIO(git_bytes(repo, "archive", "--format=tar", commit))) as archive:
        for entry in archive:
            if entry.isdir():
                continue
            safe_path(entry.name)
            if not entry.isfile():
                raise ValueError(f"Links/submodules are not supported: {entry.name}")
            if not allowed_source(entry.name):
                excluded.append(entry.name)
                continue
            data = archive.extractfile(entry).read()
            if re.search(rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", data):
                raise ValueError(f"Private key material in tracked source: {entry.name}")
            blobs[entry.name] = data
    required = ["backend/api/contracts.py", "frontend/package-lock.json", "requirements-dev.txt",
                f"{EVALUATION}/results/metadata.json", "tools/check_submission.py"]
    for name in required:
        if name not in blobs:
            raise ValueError(f"Required file absent from commit: {name}")
    return commit, tree, blobs, excluded


def historical_sources(repo: Path, blobs: dict[str, bytes]) -> dict[str, bytes]:
    metadata = json.loads(blobs[f"{EVALUATION}/results/metadata.json"])
    if metadata["git_head"] != SOURCE_COMMIT:
        raise ValueError("Unexpected historical source commit")
    result = {}
    for name, expected in metadata["source_sha256"].items():
        safe_path(name)
        data = git_bytes(repo, "show", f"{SOURCE_COMMIT}:{name}")
        if sha(data) != expected:
            raise ValueError(f"Historical source mismatch: {name}")
        result[f"submission-evidence/historical/{SOURCE_COMMIT}/{name}"] = data
    return result


def build(repo: Path, revision: str, report: Path, report_meta: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(output)
    commit, tree, blobs, excluded = collect_sources(repo, revision)
    meta = json.loads(report_meta.read_text(encoding="utf-8"))
    report_bytes = report.read_bytes()
    if (meta.get("source_commit") != commit or meta.get("pdf_sha256") != sha(report_bytes)
            or meta.get("stage") != "review_draft" or not 1 <= meta.get("page_count", 0) <= 20):
        raise ValueError("Report commit/hash/stage/page-count does not match this source bundle")
    if not report_bytes.startswith(b"%PDF-"):
        raise ValueError("Report is not a PDF")
    if not {"tools/build_submission_report.py", "requirements-report.txt"}.issubset(meta.get("inputs", {})):
        raise ValueError("Report generator and dependency hashes are required")
    for name, expected in meta["inputs"].items():
        safe_path(name)
        if name not in blobs or sha(blobs[name].replace(b"\r\n", b"\n")) != expected:
            raise ValueError(f"Report input differs from committed source: {name}")
    blobs.update(historical_sources(repo, blobs))
    blobs["report/반입맞춤_문제해결_보고서_검토본.pdf"] = report_bytes
    blobs["report/report-build.json"] = report_meta.read_bytes()
    manifest = {"schema_version": "1", "stage": "review_draft", "source_commit": commit,
                "source_tree": tree, "historical_source_commit": SOURCE_COMMIT,
                "external_actions_performed": False, "excluded_tracked_paths": excluded,
                "limits": ["Not a completed deployment or final submission approval",
                           "No credentials, local runtime DB, Git history, or installed dependencies",
                           "Historical Git-dependent tests require the original repository; see docs/submission/README.md"],
                "files": [{"path": n, "bytes": len(b), "sha256": sha(b)} for n, b in sorted(blobs.items())]}
    blobs[MANIFEST] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation protects prior deliverables. Fixed ZIP metadata permits byte reproducibility.
    with output.open("xb") as handle:
        with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted(blobs.items()):
                info = zipfile.ZipInfo("banipmatch/" + safe_path(name), date_time=(2026, 11, 10, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
    return {"source_commit": commit, "files": len(manifest["files"]), "zip_sha256": sha(output.read_bytes()),
            "report_sha256": sha(report_bytes), "stage": "review_draft", "excluded_tracked_paths": excluded}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--report-meta", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(ROOT, args.ref, args.report, args.report_meta, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
