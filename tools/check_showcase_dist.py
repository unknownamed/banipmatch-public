"""Check the static publish boundary; not a substitute for hosting/browser QA."""
from html.parser import HTMLParser
from pathlib import Path
import argparse
import re

ROOT = Path(__file__).resolve().parents[1]
CANARY = "banipmatch-public-build-must-not-include-this"


class Entry(HTMLParser):
    def __init__(self):
        super().__init__()
        self.csp = None
        self.assets = []
        self.scripts = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "meta" and values.get("http-equiv", "").lower() == "content-security-policy":
            self.csp = values.get("content", "")
        if tag == "script":
            self.scripts += 1
            if not values.get("src"):
                raise ValueError("Inline script is not part of the static publish boundary")
            self.assets.append(values["src"])
        if tag == "link" and values.get("rel") in {"stylesheet", "modulepreload"}:
            self.assets.append(values.get("href", ""))


def check(directory: Path):
    directory = directory.resolve()
    files = list(directory.rglob("*"))
    if not files or not (directory / "index.html").is_file():
        raise ValueError("Missing built showcase/index.html")
    for p in files:
        if p.is_symlink():
            raise ValueError("Symlinks are not allowed in public artifacts")
        if p.is_file() and p.relative_to(directory).as_posix() != "index.html":
            if not re.fullmatch(r"assets/[\w-]+\.(js|css)", p.relative_to(directory).as_posix()):
                raise ValueError(f"Unexpected public file: {p.relative_to(directory)}")
    entry = Entry()
    entry.feed((directory / "index.html").read_text(encoding="utf-8"))
    directives = {parts[0]: parts[1:] for item in (entry.csp or "").split(";") if (parts := item.split())}
    for name, expected in {"default-src": ["'none'"], "script-src": ["'self'"],
                           "style-src": ["'self'"], "connect-src": ["'none'"],
                           "object-src": ["'none'"], "base-uri": ["'none'"],
                           "form-action": ["'none'"]}.items():
        if directives.get(name) != expected:
            raise ValueError(f"Unexpected or missing CSP {name}")
    if entry.scripts != 1 or len(entry.assets) < 2:
        raise ValueError("Expected one module entry and a local stylesheet")
    for asset in entry.assets:
        if not re.fullmatch(r"\./assets/[\w-]+\.(js|css)", asset) or not (directory / asset).is_file():
            raise ValueError(f"Missing or nonrelative asset: {asset}")
    blocked = (CANARY, "VITE_API_TOKEN", "BANIPMATCH_DEMO_TOKEN", "/v1/", "sourceMappingURL",
               "http://127.0.0.1", "localhost:", "XMLHttpRequest", "WebSocket(", "fetch(")
    for path in files:
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            for marker in blocked:
                if marker in content:
                    raise ValueError(f"Live API/environment marker in public artifact: {marker}")
    return len([p for p in files if p.is_file()])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "frontend/dist-showcase")
    args = parser.parse_args()
    print(f"Static showcase boundary passed: {check(args.directory)} files; no publish performed.")
