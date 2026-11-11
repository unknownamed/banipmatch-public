"""Server-owner commands. No push sends, deployment or private-key output."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from backend.workflow.hub import moment
from backend.workflow.push import public_key
from backend.workflow.security import IDENTIFIER


def generate(path: Path):
    private = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(private)
    return public_key(path)


def authorize(directory: Path, session_id: str, *, consent_note: str, revoke=False):
    if not IDENTIFIER.fullmatch(session_id) or not 1 <= len(consent_note.strip()) <= 200:
        raise ValueError("session/consent record required")
    path = directory.resolve() / "registry.sqlite3"
    with sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5) as conn:
        if conn.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ValueError("registry version mismatch")
        row = conn.execute("SELECT revoked,expires_at FROM sessions WHERE session_id=? AND ready=1", (session_id,)).fetchone()
        if not row or row[0] or moment(row[1]) <= datetime.now(timezone.utc):
            raise ValueError("active session required")
        conn.execute("UPDATE sessions SET push_authorized=?,consent_note=? WHERE session_id=?",
                     (0 if revoke else 1, consent_note.strip(), session_id))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    vapid = commands.add_parser("generate-vapid")
    vapid.add_argument("--output", type=Path, required=True)
    grant = commands.add_parser("authorize-test-session")
    grant.add_argument("--workflow-dir", type=Path, required=True)
    grant.add_argument("--session-id", required=True)
    grant.add_argument("--consent-note", required=True)
    grant.add_argument("--consent-confirmed", action="store_true", required=True)
    grant.add_argument("--revoke", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "generate-vapid":
            print("VAPID 공개키:", generate(args.output))
            print("개인키는 지정한 서버 파일에만 보존함. Git/프론트/채팅으로 공유하지 마세요.")
        else:
            authorize(args.workflow_dir, args.session_id, consent_note=args.consent_note, revoke=args.revoke)
            print("팀원 시험 세션 권한 변경 완료. 초대/휴대폰 동의/실수신은 별도 확인 사항임.")
        return 0
    except (OSError, ValueError, sqlite3.Error):
        print("설정 실패: 기존 파일 보존·세션/수신 동의·경로/만료 상태를 확인하세요. 비밀값은 출력하지 않음.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
