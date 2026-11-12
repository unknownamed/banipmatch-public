"""팀 시연 코드로 앱 알림 시험 권한을 여는 경로: 틀리면 거절·횟수 제한, 맞으면 그 세션만 허용."""
from dataclasses import replace

from fastapi.testclient import TestClient

from backend.api.app import create_app
from test_workflow_api import ORIGIN, Transport, new_manager


def make(settings, tmp_path, code="BM2611"):
    path = tmp_path / "team-code.txt"
    path.write_text(code + "\n", encoding="utf-8")
    config = replace(settings, workflow_enabled=True, workflow_dir=tmp_path / "workflow", push_team_code_file=path)
    return TestClient(create_app(config, push_sender=Transport()), base_url=ORIGIN, client=("127.0.0.1", 50000))


def test_team_code_opens_only_this_session(settings, tmp_path):
    with make(settings, tmp_path) as client:
        a, b = new_manager(client), new_manager(client)
        wrong = a.post("/v2/session/push-authorization", {"team_code": "nope"})
        assert wrong.status_code == 403 and wrong.json()["code"] == "TEAM_CODE_INVALID"
        ok = a.post("/v2/session/push-authorization", {"team_code": " bm2611 "})
        assert ok.status_code == 200 and ok.json()["push_test_authorized"] is True
        assert "BM2611" not in ok.text
        assert b.get("/v2/session").json()["push_test_authorized"] is False


def test_team_code_is_rate_limited_and_absent_when_not_configured(settings, tmp_path):
    with make(settings, tmp_path) as client:
        actor = new_manager(client)
        codes = [actor.post("/v2/session/push-authorization", {"team_code": f"x{i}"}).status_code for i in range(6)]
        assert codes[:5] == [403] * 5 and codes[5] == 429
    config = replace(settings, workflow_enabled=True, workflow_dir=tmp_path / "w2")
    with TestClient(create_app(config, push_sender=Transport()), base_url=ORIGIN, client=("127.0.0.1", 50000)) as client:
        actor = new_manager(client)
        r = actor.post("/v2/session/push-authorization", {"team_code": "BM2611"})
        assert r.status_code == 503 and r.json()["code"] == "TEAM_CODE_NOT_CONFIGURED"
