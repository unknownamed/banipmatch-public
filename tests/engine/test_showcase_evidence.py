"""Frozen evidence must remain traceable, complete, and unapproved."""
from copy import deepcopy
import json
import shutil
import subprocess

import pytest

from tools import build_showcase_evidence as showcase
from tools import evaluate_engine

# 공개 저장소는 개인 이메일을 지우려고 커밋 이력을 다시 쓴 사본이라 평가 실행 커밋(SOURCE_COMMIT)이 없다.
# 이 검사는 그 커밋의 원본 파일을 읽으므로, 커밋이 없으면 건너뛴다(원 저장소와 제출 ZIP의 검사로 확인).
_HAS_SOURCE = subprocess.run(["git", "cat-file", "-e", f"{showcase.SOURCE_COMMIT}^{{commit}}"],
                             cwd=showcase.ROOT, capture_output=True).returncode == 0
pytestmark = pytest.mark.skipif(not _HAS_SOURCE, reason="평가 실행 커밋이 없는 재작성 이력(공개 저장소 사본)")


@pytest.fixture(scope="module")
def bundle():
    return showcase.build_bundle()


@pytest.fixture(scope="module")
def raw():
    protocol = showcase.read_json(showcase.EVALUATION / "protocol.json")
    snapshots = {c["id"]: showcase.read_json(showcase.EVALUATION / c["input"]) for c in protocol["cases"]}
    rows = [json.loads(line) for line in (showcase.EVALUATION / "results/results.jsonl").read_text(encoding="utf-8").splitlines()]
    return protocol, snapshots, rows


def test_selected_records_are_exact_raw_rows_and_never_approved(bundle, raw):
    protocol, snapshots, rows = raw
    assert len(bundle["cases"]) == 10
    assert bundle["context"]["total_records"] == 80
    assert len(bundle["context"]["pairs"]) == 20
    assert {c["case_id"] for c in bundle["cases"]} == {c["id"] for c in protocol["cases"]}
    for case in bundle["cases"]:
        assert case["snapshot"] == snapshots[case["case_id"]]
        for method, row in case["methods"].items():
            original = rows[row["source_jsonl_line"] - 1]
            assert {k: v for k, v in row.items() if k != "source_jsonl_line"} == original
            assert row["method"] == method and row["seed"] == 0
            assert row["result"]["validation_status"] == "not_run"
            assert row["result"]["approval_eligible"] is False
            assert row["audit"]["schedule"] == ("baseline_not_applicable" if method == "B0" else "passed")


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "seed", "method", "audit", "metric", "approval"])
def test_grid_and_independent_audit_reject_corruption(raw, corruption):
    protocol, snapshots, originals = raw
    rows = deepcopy(originals)
    if corruption == "missing":
        rows.pop()
    elif corruption == "duplicate":
        rows[-1] = deepcopy(rows[0])
    elif corruption == "seed":
        rows[0]["seed"] = 99
    elif corruption == "method":
        rows[1]["result"]["method"] = "B3"
    elif corruption == "audit":
        rows[1]["audit"]["schedule"] = "failed"
    elif corruption == "metric":
        rows[1]["result"]["metrics"]["movable_travel_minutes"] += 1
    else:
        rows[1]["result"]["approval_eligible"] = True
    with pytest.raises(ValueError):
        showcase.validate_records(protocol, snapshots, rows)


@pytest.mark.parametrize("name", ["protocol.json", "results/results.jsonl", "results/metadata.json", "results/summary.json", "inputs/eval_cutoff_8_101.json"])
@pytest.mark.parametrize("eol", [b"\n", b"\r\n"])
def test_frozen_files_and_inputs_cannot_be_rewritten(tmp_path, name, eol):
    directory = tmp_path / "evidence"
    shutil.copytree(showcase.EVALUATION, directory)
    path = directory / name
    path.write_bytes(showcase.normalized_bytes(path.read_bytes()).replace(b"\n", eol) + b" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        showcase.build_bundle(directory)


def test_source_metadata_requires_clean_completed_original_run(raw):
    protocol, _, _ = raw
    metadata = showcase.read_json(showcase.EVALUATION / "results/metadata.json")
    metadata["git_head"] = "f" * 40
    with pytest.raises(ValueError, match="source metadata"):
        showcase.check_source_metadata(protocol, metadata, showcase.EVALUATION)


def test_same_count_is_not_same_work_and_50_jobs_has_no_improvement(bundle):
    fixed = next(c for c in bundle["cases"] if c["case_id"] == "eval_fixed_8_101")
    assert fixed["comparison"]["equal_unassigned_count"]
    assert not fixed["comparison"]["same_served_job_set"]
    assert fixed["comparison"]["b2_served_job_ids"] != fixed["comparison"]["b3_served_job_ids"]
    for method in ("B2", "B3"):
        assert fixed["methods"][method]["result"]["metrics"]["fixed_risk_count"] == 1
    large = next(c for c in bundle["cases"] if c["job_count"] == 50)
    assert large["comparison"]["same_served_job_set"]
    assert large["comparison"]["delta_changed_jobs"] == large["comparison"]["delta_travel_minutes"] == 0
    for method in ("B2", "B3"):
        result = large["methods"][method]["result"]
        assert result["solution_status"] == "FEASIBLE"
        assert not result["objective_proven"]
        assert result["metrics"]["unassigned_count"] == 9


def test_check_reproduces_outputs_without_solver(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Frozen showcase must never rerun solver")
    monkeypatch.setattr(evaluate_engine, "solve", forbidden)
    monkeypatch.setattr("sys.argv", ["build_showcase_evidence.py", "--check"])
    assert showcase.main() == 0


@pytest.mark.parametrize("eol", [b"\n", b"\r\n"])
def test_checkout_line_endings_produce_identical_bundle_and_check(tmp_path, bundle, monkeypatch, eol):
    directory = tmp_path / "evidence"
    shutil.copytree(showcase.EVALUATION, directory)
    for path in directory.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".jsonl", ".md", ".diff"}:
            path.write_bytes(showcase.normalized_bytes(path.read_bytes()).replace(b"\n", eol))
    assert showcase.build_bundle(directory) == bundle
    monkeypatch.setattr(showcase, "EVALUATION", directory)
    monkeypatch.setattr("sys.argv", ["build_showcase_evidence.py", "--check"])
    assert showcase.main() == 0
    # Output checking tolerates EOL conversion, but never ignores other bytes.
    path = directory / "showcase.json"
    path.write_bytes(path.read_bytes() + b" ")
    assert showcase.main() == 1


def test_committed_git_blobs_reproduce_linux_checkout(tmp_path, bundle):
    directory = tmp_path / "git-blobs"
    prefix = showcase.EVALUATION.relative_to(showcase.ROOT).as_posix() + "/"
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", "HEAD", "--", prefix], cwd=showcase.ROOT).decode().splitlines()
    for name in names:
        path = directory / name.removeprefix(prefix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(subprocess.check_output(["git", "show", f"HEAD:{name}"], cwd=showcase.ROOT))
    assert showcase.build_bundle(directory) == bundle


def test_newline_normalization_does_not_ignore_other_bytes():
    assert showcase.normalized_bytes(b"a\r\nb\n") == b"a\nb\n"
    assert showcase.normalized_bytes(b"a\rb\n") == b"a\rb\n"
    assert showcase.normalized_bytes(b"\xef\xbb\xbfa \n") == b"\xef\xbb\xbfa \n"
