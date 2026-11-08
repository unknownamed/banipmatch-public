from dataclasses import dataclass, field
import os
from pathlib import Path

from backend.api.contracts import ROOT


@dataclass(frozen=True)
class Settings:
    db_path: Path = ROOT / "local" / "banipmatch-demo.sqlite3"
    demo_enabled: bool = False
    demo_token: str = ""
    run_mode: str = "fixture"
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
            cors_origins=tuple(x.strip() for x in os.getenv(
                "BANIPMATCH_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",") if x.strip()),
        )

    def check(self) -> None:
        if not self.demo_enabled or len(self.demo_token) < 24 or not self.demo_token.isascii():
            raise RuntimeError("BANIPMATCH_DEMO=1 및 24자 이상 ASCII 모의 토큰이 필요함")
        if self.run_mode not in ("fixture", "engine"):
            raise RuntimeError("BANIPMATCH_RUN_MODE는 fixture 또는 engine이어야 함")
