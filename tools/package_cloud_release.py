"""Build an allowlisted cloud artifact; private runtime files are never included."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]


def included(path: str) -> bool:
    p = Path(path)
    if any(part.startswith('.') or part in {'local', 'secrets', '__pycache__', 'node_modules'} for part in p.parts):
        return False
    if path.startswith(('backend/', 'tools/')) and p.suffix == '.py':
        return True
    if path.startswith(('docs/development/v0.1/공통 규격/', 'docs/development/v0.1/예제 데이터/', 'docs/development/v0.2/')) and p.suffix in {'.json', '.sql'}:
        return True
    return path.startswith('deployment/cloud/') or (p.name.startswith('requirements') and p.suffix == '.txt')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT):
        raise SystemExit('Commit the intended source first; refuse an unversioned release.')
    files = subprocess.check_output(['git', '-c', 'core.quotepath=false', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    paths = [ROOT / s for s in files if s and included(s)]
    dist = ROOT / 'frontend/dist'
    if not (dist / 'index.html').is_file():
        raise SystemExit('Build the frontend before packaging.')
    paths.extend(p for p in dist.rglob('*') if p.is_file())
    forbidden = [p.read_bytes().strip() for p in (ROOT/'local/secrets').glob('*')
                 if p.is_file() and p.name != 'kakao-js-key.txt' and 8 <= p.stat().st_size <= 10000]
    manifest = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(args.output, 'x', compression=ZIP_DEFLATED) as bundle:
        for p in sorted(paths):
            if p.is_symlink() or not p.resolve().is_relative_to(ROOT):
                raise ValueError('Artifact path outside repository')
            data = p.read_bytes()
            if any(secret in data for secret in forbidden):
                raise ValueError('Private value detected; refusing artifact')
            relative = p.relative_to(ROOT).as_posix()
            bundle.writestr(relative, data)
            manifest.append({'path': relative, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes':len(data)})
        bundle.writestr('release-manifest.json', json.dumps({'git_commit':head,'files':manifest}, ensure_ascii=False, indent=2))
    print(json.dumps({'git_commit':head, 'files':len(paths), 'bytes':args.output.stat().st_size,
                      'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    main()
