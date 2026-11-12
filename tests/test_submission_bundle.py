import hashlib
import json
from pathlib import Path
import subprocess
import shutil

import pytest

from tools import build_submission as build
from tools.check_submission import verify_files


def fixture_bundle(root):
    pdf=b"%PDF-1.4\nsynthetic manifest test only\n"
    meta={"source_commit":"a"*40,"pdf_sha256":build.sha(pdf),"page_count":10,"stage":"review_draft"}
    files={"source.py":b"print('fixture')\n", "report/report-build.json":json.dumps(meta).encode(),
           "report/반입맞춤_문제해결_보고서_검토본.pdf":pdf}
    manifest={"schema_version":"1","stage":"review_draft","source_commit":"a"*40,
              "files":[{"path":n,"bytes":len(b),"sha256":build.sha(b)} for n,b in files.items()]}
    for name,data in files.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    (root/build.MANIFEST).write_text(json.dumps(manifest),encoding="utf-8")
    return manifest


@pytest.mark.parametrize("name",["../secret","/absolute","a/../../x","C:/secret","a\\b","a//b","a/./b"])
def test_unsafe_paths_rejected(name):
    with pytest.raises(ValueError): build.safe_path(name)


@pytest.mark.parametrize("name",[".env","frontend/.env.local","backend/.ENV","docs/raw/response.json",
                                 "frontend/node_modules/a.js","backend/private/key.json","backend/demo.sqlite3"])
def test_local_material_not_exported(name):
    assert not build.allowed_source(name)


def test_expected_examples_and_source_allowed():
    for name in [".env.example","frontend/.env.example","frontend/package-lock.json","docs/development/v0.1/예제 데이터/01_snapshot.json"]:
        assert build.allowed_source(name)


def test_complete_bundle_and_tampered_file(tmp_path):
    fixture_bundle(tmp_path)
    assert verify_files(tmp_path)["source_commit"]=="a"*40
    (tmp_path/"source.py").write_bytes(b"tampered")
    with pytest.raises(ValueError,match="hash/size"):verify_files(tmp_path)


def test_unlisted_file_rejected(tmp_path):
    fixture_bundle(tmp_path)
    (tmp_path/"secret.env").write_text("not part of original")
    with pytest.raises(ValueError,match="Unexpected"):verify_files(tmp_path)


def test_manifest_cannot_escape_root_or_repeat_entry(tmp_path):
    manifest=fixture_bundle(tmp_path)
    manifest["files"].append(dict(manifest["files"][0]))
    (tmp_path/build.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match="Duplicate"):verify_files(tmp_path)


def test_report_version_mismatch_even_if_file_hashes_match(tmp_path):
    manifest=fixture_bundle(tmp_path)
    manifest["source_commit"]="b"*40
    (tmp_path/build.MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match="Report/source"):verify_files(tmp_path)


def test_builder_checks_report_before_creating_output(tmp_path,monkeypatch):
    monkeypatch.setattr(build,"collect_sources",lambda *a:("a"*40,"b"*40,{},[]))
    report=tmp_path/"report.pdf";report.write_bytes(b"%PDF-test")
    meta=tmp_path/"report.json";meta.write_text(json.dumps({"source_commit":"wrong"}))
    out=tmp_path/"output.zip"
    with pytest.raises(ValueError,match="Report commit"):build.build(tmp_path,"HEAD",report,meta,out)
    assert not out.exists()
    out.write_bytes(b"keep")
    with pytest.raises(FileExistsError):build.build(tmp_path,"HEAD",report,meta,out)
    assert out.read_bytes()==b"keep"


def test_changed_report_generator_cannot_claim_old_commit(tmp_path,monkeypatch):
    sources={"tools/build_submission_report.py":b"old generator", "requirements-report.txt":b"requirements"}
    monkeypatch.setattr(build,"collect_sources",lambda *a:("a"*40,"b"*40,sources,[]))
    report=tmp_path/"report.pdf";report.write_bytes(b"%PDF-test")
    meta=tmp_path/"report.json"
    meta.write_text(json.dumps({"source_commit":"a"*40,"pdf_sha256":build.sha(report.read_bytes()),
        "stage":"review_draft","page_count":10,"inputs":{"tools/build_submission_report.py":build.sha(b"uncommitted generator"),
        "requirements-report.txt":build.sha(b"requirements")}}))
    with pytest.raises(ValueError,match="differs from committed"):
        build.build(tmp_path,"HEAD",report,meta,tmp_path/"output.zip")
    assert not (tmp_path/"output.zip").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="Export-only fixture needs Git; delivered bundle verification does not")
def test_export_uses_committed_bytes_and_excludes_tracked_env(tmp_path):
    def git(*args):
        return subprocess.check_output(["git",*args],cwd=tmp_path,stderr=subprocess.STDOUT)
    git("init","-q")
    names=["backend/api/contracts.py","frontend/package-lock.json","requirements-dev.txt",
           build.EVALUATION+"/results/metadata.json","tools/check_submission.py",".env"]
    for name in names:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"committed\r\n")
    (tmp_path/".gitattributes").write_text("* -text\n")
    git("add",".")
    git("-c","user.name=Submission Test","-c","user.email=test@example.invalid","commit","-qm","fixture")
    (tmp_path/"backend/api/contracts.py").write_bytes(b"uncommitted")
    commit,tree,files,excluded=build.collect_sources(tmp_path,"HEAD")
    assert len(commit)==len(tree)==40
    assert files["backend/api/contracts.py"]==b"committed\r\n"
    assert ".env" not in files and ".env" in excluded


def test_final_stage_bundle_uses_final_report_name(tmp_path):
    pdf=b"%PDF-1.4\nsynthetic final\n"
    meta={"source_commit":"a"*40,"pdf_sha256":build.sha(pdf),"page_count":19,"stage":"final"}
    files={"source.py":b"x\n","report/report-build.json":json.dumps(meta).encode(),
           "report/"+build.REPORT_NAMES["final"]:pdf}
    manifest={"schema_version":"1","stage":"final","source_commit":"a"*40,
              "files":[{"path":n,"bytes":len(b),"sha256":build.sha(b)} for n,b in files.items()]}
    for name,data in files.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    (tmp_path/build.MANIFEST).write_text(json.dumps(manifest),encoding="utf-8")
    assert verify_files(tmp_path)["stage"]=="final"


def test_final_stage_requires_final_report_inputs(tmp_path,monkeypatch):
    monkeypatch.setattr(build,"collect_sources",lambda *a:("a"*40,"b"*40,{},[]))
    report=tmp_path/"report.pdf";report.write_bytes(b"%PDF-test")
    meta=tmp_path/"report.json"
    meta.write_text(json.dumps({"source_commit":"a"*40,"pdf_sha256":build.sha(report.read_bytes()),
        "stage":"final","page_count":19,"inputs":{"tools/build_submission_report.py":"x"}}))
    with pytest.raises(ValueError,match="generator"):
        build.build(tmp_path,"HEAD",report,meta,tmp_path/"output.zip")
