"""Serve only the built UI; never expose the repository, local secrets or SPA-fallback API errors."""
from pathlib import Path
import re

from fastapi.responses import FileResponse


def install_assets(app, directory) -> set[str]:
    root = Path(directory).resolve(strict=True)
    index = root / "index.html"
    if not index.is_file() or index.is_symlink():
        raise ValueError("built frontend index.html required")
    files = {"/": index, "/recipient": index, "/recipient/": index}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root):
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {"sw.js", "manifest.webmanifest", "icon-180.png", "icon-192.png", "icon-512.png"} or re.fullmatch(
                r"assets/[A-Za-z0-9_.-]+\.(?:js|css|png|svg|woff2?)", relative):
            files["/" + relative] = path
    for url, path in files.items():
        # No query parameter may override the file path.
        def factory(file):
            def serve():
                return FileResponse(file)
            return serve
        app.add_api_route(url, factory(path), methods=["GET", "HEAD"], include_in_schema=False)
    return set(files)
