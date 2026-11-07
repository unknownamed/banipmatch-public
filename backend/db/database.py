from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import sqlite3

from backend.api.contracts import DRAFT


class Database:
    """연결마다 외래키/재귀 트리거를 설정하고 성공한 쓰기만 원자적으로 저장."""

    def __init__(self, path: Path):
        self.path = Path(path).resolve()
        self._lock_file = None

    def acquire(self) -> None:
        # 재시작 복구가 다른 실행 서버의 running을 실패로 바꾸지 못하게 단일 소유권 보장.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.with_suffix(self.path.suffix + ".lock").open("a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            raise RuntimeError("같은 DB를 사용 중인 백엔드가 있음. 단일 프로세스로 실행") from None
        self._lock_file = handle

    def release(self) -> None:
        if self._lock_file is not None:
            self._lock_file.close()
            self._lock_file = None

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA recursive_triggers=ON")
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def initialize(self) -> None:
        with self.connect() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'").fetchone():
                    raise RuntimeError("버전 없는 기존 DB는 자동 변경하지 않음")
                conn.executescript((DRAFT / "공통 규격" / "schema.sql").read_text(encoding="utf-8"))
            elif version != 1:
                raise RuntimeError("지원하지 않는 DB 버전. 별도 이전 필요")
            conn.execute("PRAGMA journal_mode=WAL")
