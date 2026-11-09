from pathlib import Path

import pytest

from tools.check_showcase_dist import CANARY, check


@pytest.fixture
def artifact(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/main-abc.js").write_text("console.log('static archive')", encoding="utf-8")
    (tmp_path / "assets/main-def.css").write_text("body{color:black}", encoding="utf-8")
    (tmp_path / "index.html").write_text('''<html><head>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
<script type="module" src="./assets/main-abc.js"></script>
<link rel="stylesheet" href="./assets/main-def.css"></head><body></body></html>''', encoding="utf-8")
    return tmp_path


def test_relative_static_artifact(artifact):
    assert check(artifact) == 3


@pytest.mark.parametrize("problem", ["token", "api", "source_map", "private_file", "network", "external_script", "missing_asset", "inline_script"])
def test_rejects_boundary_violations(artifact, problem):
    html = artifact / "index.html"
    js = artifact / "assets/main-abc.js"
    if problem == "token":
        js.write_text(CANARY, encoding="utf-8")
    elif problem == "api":
        js.write_text("fetch('/v1/runs')", encoding="utf-8")
    elif problem == "source_map":
        (artifact / "assets/main.js.map").write_text('{}', encoding="utf-8")
    elif problem == "private_file":
        (artifact / ".env").write_text('demo-secret', encoding="utf-8")
    elif problem == "network":
        html.write_text(html.read_text(encoding="utf-8").replace("connect-src 'none'", "connect-src *"), encoding="utf-8")
    elif problem == "external_script":
        html.write_text(html.read_text(encoding="utf-8").replace('./assets/main-abc.js', 'https://example.org/main.js'), encoding="utf-8")
    elif problem == "missing_asset":
        js.unlink()
    else:
        html.write_text(html.read_text(encoding="utf-8").replace('</head>', '<script>alert(1)</script></head>'), encoding="utf-8")
    with pytest.raises(ValueError):
        check(artifact)
