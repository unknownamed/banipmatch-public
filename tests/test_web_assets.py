from dataclasses import replace
from fastapi.testclient import TestClient
from backend.api.app import create_app


def test_public_build_serves_only_allowlisted_assets(settings, tmp_path):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<h1>반입맞춤</h1>", encoding="utf-8")
    (root / "sw.js").write_text("// sw")
    (root / ".env").write_text("PRIVATE")
    (root / "config.json").write_text("PRIVATE")
    (root / "assets").mkdir()
    (root / "assets" / "app.js").write_text("// app")
    (root / "assets" / "app.js.map").write_text("PRIVATE")
    config = replace(settings, public_enabled=True, workflow_enabled=True, run_mode="engine",
                     workflow_dir=tmp_path / "workflow", public_hosts=("demo.example",), cors_origins=("https://demo.example",))
    with TestClient(create_app(config, frontend_dir=root), base_url="https://demo.example") as client:
        for url in ("/", "/recipient", "/recipient/", "/sw.js", "/assets/app.js"):
            assert client.get(url).status_code == 200
        assert "PRIVATE" not in client.get("/?file=.env").text
        for url in ("/.env", "/config.json", "/assets/app.js.map", "/v1/plans/x", "/local/workflow/registry.sqlite3", "/unknown"):
            assert client.get(url).status_code == 404
        assert client.get("/v2/session").status_code == 401
        assert client.get("/", headers={"Host": "wrong.example"}).status_code == 400
        assert client.post("/v2/session", headers={"Origin": "https://evil.example"}).status_code == 403
