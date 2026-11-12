"""현장 식별 필드(컨테이너 번호·번호판 등)가 저장·계산·명세까지 이어지는지, 기존 DB도 열이 보강되는지."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from backend.db.database import FIELD_COLUMNS, ensure_field_columns
from test_workflow_api import new_manager, workflow  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "frontend/src/fixtures/demo-02-evening.synthetic.json"


def shifted(snapshot: dict) -> dict:
    """화면의 shiftSnapshot과 같은 규칙: 모든 *_at·as_of·input_valid_until을 지금(분 단위)으로 옮긴다."""
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    delta = now - datetime.fromisoformat(snapshot["as_of"].replace("Z", "+00:00"))

    def walk(node):
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, dict):
            return {k: ((datetime.fromisoformat(v.replace("Z", "+00:00")) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")
                        if isinstance(v, str) and (k.endswith("_at") or k in ("as_of", "input_valid_until")) else walk(v))
                    for k, v in node.items()}
        return node
    return walk(snapshot)


def test_example_02_with_field_identifiers_registers_and_keeps_them(workflow):
    client, _, _ = workflow
    manager = new_manager(client)
    snapshot = shifted(json.loads(DEMO.read_text(encoding="utf-8")))
    saved = manager.post("/v2/scenarios", snapshot)
    assert saved.status_code == 201, saved.text
    stored = manager.get("/v2/scenarios/" + snapshot["scenario_id"]).json()
    job = next(j for j in stored["jobs"] if j["job_id"] == "J03")
    assert job["container_no"] == "BNJU1002036" and job["cargo_owner"] == "가람정밀(주)"
    assert next(v for v in stored["vehicles"] if v["vehicle_id"] == "T1")["plate_no"] == "부산 90바 1201"


def test_existing_database_gets_new_optional_columns_without_losing_rows(tmp_path):
    db = tmp_path / "old.sqlite3"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE jobs (scenario_id TEXT, job_id TEXT)")
        conn.execute("CREATE TABLE vehicles (scenario_id TEXT, vehicle_id TEXT)")
        conn.execute("INSERT INTO jobs VALUES ('S', 'J1')")
        ensure_field_columns(conn)
        ensure_field_columns(conn)  # 두 번 불러도 안전
        for table, columns in FIELD_COLUMNS.items():
            present = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            assert set(columns) <= present
        assert conn.execute("SELECT job_id, container_no FROM jobs").fetchall() == [("J1", None)]
