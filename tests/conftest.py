import json

from fastapi.testclient import TestClient
import pytest

from backend.api.app import create_app
from backend.api.contracts import DRAFT
from backend.api.settings import Settings

TOKEN = "test-only-not-a-production-token-1234"


@pytest.fixture
def snapshot():
    return json.loads((DRAFT / "예제 데이터" / "01_snapshot.json").read_text(encoding="utf-8"))


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "demo.sqlite3", demo_enabled=True, demo_token=TOKEN)


def make_client(settings, **kwargs):
    return TestClient(create_app(settings, **kwargs), base_url="http://127.0.0.1",
                      client=("127.0.0.1", 50000), headers={"Authorization": f"Bearer {TOKEN}"})


@pytest.fixture
def client(settings):
    with make_client(settings) as client:
        yield client
