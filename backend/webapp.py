"""Production UI + isolated calculation API on the same origin.

Run with uvicorn backend.webapp:create --factory --host 127.0.0.1 --port 8000.
The reverse proxy must terminate HTTPS; only its loopback address may be trusted.
"""
from pathlib import Path
from backend.api.app import create_app
from backend.api.settings import Settings


def create():
    return create_app(Settings.from_env(), frontend_dir=Path(__file__).resolve().parents[1] / "frontend" / "dist")
