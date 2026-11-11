"""Team #56 inputs through #54 HTTP/storage and #57 real B1 comparisons.

Synthetic inputs, temporary databases and injected transport only. No listening
server, provider call, real condition confirmation or phone delivery occurs.
"""
from copy import deepcopy
from datetime import datetime

import pytest

from backend.api.contracts import digest
from tools.response_acceptance import DEFAULT, read
from test_workflow_api import (approve, calculate, new_manager, workflow)


@pytest.mark.parametrize("case", ["ready-only", "missing-repaired", "extra-vehicle", "later-ready"])
@pytest.mark.parametrize("confirmation", ["assumed", "confirmed_simulation"])
def test_team_condition_pairs_through_persisted_api(workflow, monkeypatch, case, confirmation):
    client, transport, _ = workflow
    pair = read(DEFAULT / "pairs" / (case + ".json"))
    before, proposed = deepcopy(pair["before"]), deepcopy(pair["after"])
    # Freeze only this test's clock. Archived fixture bytes and their claims stay intact.
    now = before["as_of"]
    monkeypatch.setattr(client.app.state.workflow, "clock", lambda: datetime.fromisoformat(now.replace("Z", "+00:00")))
    monkeypatch.setattr("backend.db.store.utc_now", lambda: now)
    manager = new_manager(client)
    saved = manager.post("/v2/scenarios", before)
    assert saved.status_code == 201, saved.text
    old = None
    if case == "missing-repaired":
        blocked = manager.post("/v2/runs", {"scenario_id": before["scenario_id"], "base_plan_version": 1,
            "methods": ["B1"], "time_limit_seconds": 1, "seed": 42})
        assert blocked.status_code == 422, blocked.text
    else:
        old = calculate(manager, before)

    body = {"snapshot": proposed, "reason": pair["reason"], "confirmation": confirmation}
    path = f"/v2/scenarios/{before['scenario_id']}/revisions"
    revision = manager.post(path, body, key="pair-revision")
    assert revision.status_code == 201, revision.text
    assert manager.post(path, body, key="pair-revision").json() == revision.json()
    state = revision.json()
    after = manager.get("/v2/scenarios/" + state["scenario_id"]).json()
    assert after["scenario_id"] != before["scenario_id"]
    assert after == proposed | {"scenario_id": state["scenario_id"]}
    assert state["input_sha256"] == digest(after)
    assert manager.get("/v2/scenarios/" + before["scenario_id"]).json() == before
    following = calculate(manager, after)
    comparison_path = f"/v2/revisions/{state['revision_id']}/comparison?after_run_id={following['run_id']}"
    if old:
        comparison_path += "&before_run_id=" + old["run_id"]
    response = manager.get(comparison_path)
    assert response.status_code == 200, response.text
    assert response.json()["confirmation"] == confirmation
    compared = response.json()["comparison"]
    assert compared["revision"]["before_input_sha256"] == digest(before)
    assert compared["revision"]["after_input_sha256"] == digest(after)
    assert compared["delivery_authorized"] is False
    assert compared["external_actions_performed"] is False
    if case == "missing-repaired":
        assert compared["before"]["status"] == "input_blocked"
        assert compared["metric_deltas"] is None
    elif case == "ready-only":
        assert compared["job_transitions"]["remained_unassigned"] == ["J3"]
    elif case == "later-ready":
        assert compared["job_transitions"]["became_unassigned"] == ["J2"]
    else:
        assert compared["job_transitions"]["became_assigned"]
        assert compared["efficiency_delta"] is None

    # A different visitor or result/input pairing cannot reuse this comparison.
    stranger = new_manager(client)
    assert stranger.get(comparison_path).status_code == 404
    wrong = manager.get(comparison_path + "&before_run_id=" + following["run_id"])
    assert wrong.status_code == 422, wrong.text
    approval = approve(manager, after, following)
    if confirmation == "assumed":
        assert approval.status_code == 422, approval.text
        assert approval.json()["code"] == "ASSUMPTION_NOT_APPROVABLE"
        assert manager.get(f"/v2/plans/{after['plan_id']}/dispatch-preview").status_code == 409
    else:
        # This branch confirms a synthetic scenario only, never actual conditions.
        assert approval.status_code == 201, approval.text
        preview = manager.get(f"/v2/plans/{after['plan_id']}/dispatch-preview")
        assert preview.status_code == 200, preview.text
        assert preview.json()["scenario_id"] == after["scenario_id"]
        assert preview.json()["run_id"] == following["run_id"]
        assert preview.json()["approval_id"] == approval.json()["approval_id"]
        current = manager.get(f"/v2/plans/{after['plan_id']}").json()
        rebased = manager.get(f"/v2/plans/{after['plan_id']}/next-input").json()
        assert rebased["base_plan_version"] == current["version"]
        assert rebased["baseline_assignments"] == current["assignments"]
        assert rebased["baseline_unassigned_job_ids"] == current["unassigned_job_ids"]
        assert manager.post("/v2/scenarios", rebased).status_code == 201
        assert manager.get(f"/v2/plans/{after['plan_id']}/dispatch-preview").status_code == 409
    assert not transport.calls
