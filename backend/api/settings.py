from dataclasses import dataclass, field
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from backend.api.contracts import ROOT


@dataclass(frozen=True)
class Settings:
    db_path: Path = ROOT / "local" / "banipmatch-demo.sqlite3"
    demo_enabled: bool = False
    demo_token: str = ""
    run_mode: str = "fixture"
    workflow_enabled: bool = False
    public_enabled: bool = False
    workflow_dir: Path = ROOT / "local" / "workflow"
    public_hosts: tuple[str, ...] = ()
    push_enabled: bool = False
    vapid_private_key: Path | None = None
    vapid_subject: str = ""
    reference_file: Path | None = None
    cors_origins: tuple[str, ...] = field(default_factory=lambda: (
        "http://localhost:5173", "http://127.0.0.1:5173",
    ))

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=Path(os.getenv("BANIPMATCH_DB_PATH", str(cls.db_path))).resolve(),
            demo_enabled=os.getenv("BANIPMATCH_DEMO") == "1",
            demo_token=os.getenv("BANIPMATCH_DEMO_TOKEN", ""),
            run_mode=os.getenv("BANIPMATCH_RUN_MODE", "fixture"),
            workflow_enabled=os.getenv("BANIPMATCH_WORKFLOW") == "1",
            public_enabled=os.getenv("BANIPMATCH_PUBLIC") == "1",
            workflow_dir=Path(os.getenv("BANIPMATCH_WORKFLOW_DIR", str(cls.workflow_dir))).resolve(),
            public_hosts=tuple(x.strip() for x in os.getenv("BANIPMATCH_PUBLIC_HOSTS", "").split(",") if x.strip()),
            push_enabled=os.getenv("BANIPMATCH_PUSH_ENABLED") == "1",
            vapid_private_key=Path(os.environ["BANIPMATCH_VAPID_PRIVATE_KEY_FILE"]).resolve()
            if os.getenv("BANIPMATCH_VAPID_PRIVATE_KEY_FILE") else None,
            vapid_subject=os.getenv("BANIPMATCH_VAPID_SUBJECT", ""),
            reference_file=Path(os.environ['BANIPMATCH_REFERENCE_FILE']).resolve() if os.getenv('BANIPMATCH_REFERENCE_FILE') else None,
            cors_origins=tuple(x.strip() for x in os.getenv(
                "BANIPMATCH_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",") if x.strip()),
        )

    def check(self) -> None:
        if not self.demo_enabled or (not self.public_enabled and (
                len(self.demo_token) < 24 or not self.demo_token.isascii())):
            raise RuntimeError("BANIPMATCH_DEMO=1 및 24자 이상 ASCII 모의 토큰이 필요함")
        if self.run_mode not in ("fixture", "engine"):
            raise RuntimeError("BANIPMATCH_RUN_MODE는 fixture 또는 engine이어야 함")
        if self.public_enabled:
            if not self.workflow_enabled or self.run_mode != "engine" or not self.public_hosts:
                raise RuntimeError("공개 모드는 v0.2 세션·실계산·명시적 Host 설정이 필요함")
            if any(not h.isascii() or not h or any(c in h for c in '/:@*?#') for h in self.public_hosts):
                raise RuntimeError("공개 Host는 포트·와일드카드 없는 호스트명이어야 함")
            if not self.cors_origins or any(urlsplit(o).scheme != "https" or not urlsplit(o).hostname
                                           or urlsplit(o).path or urlsplit(o).query or urlsplit(o).fragment
                                           for o in self.cors_origins):
                raise RuntimeError("공개 모드는 명시적 HTTPS Origin이 필요함")
        if self.push_enabled and (not self.workflow_enabled or self.vapid_private_key is None
                                  or not self.vapid_subject.startswith(("https://", "mailto:"))):
            raise RuntimeError("푸시에는 v0.2와 서버 VAPID 키 파일·연락 출처가 필요함")
        if self.push_enabled:
            subject = urlsplit(self.vapid_subject)
            valid_mail = bool(re.fullmatch(r"mailto:[^@\s]+@[^@\s]+\.[^@\s]+", self.vapid_subject))
            valid_https = (subject.scheme == "https" and subject.hostname and not subject.path
                           and not subject.query and not subject.fragment and subject.username is None)
            if len(self.vapid_subject) > 512 or not (valid_mail or valid_https):
                raise RuntimeError("VAPID subject는 mailto 주소 또는 경로 없는 HTTPS origin이어야 함")
