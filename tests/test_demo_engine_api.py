from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from backend.api.engine_replay import EngineReplay
from backend.api.contracts import digest
from conftest import make_client
from tools.demo_engine_api import http_client, main, prepare_snapshot, run_demo


def times(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and (key.endswith('_at') or key in {'as_of', 'input_valid_until'}):
                yield datetime.fromisoformat(value.replace('Z', '+00:00'))
            else:
                yield from times(value)
    elif isinstance(node, list):
        for value in node:
            yield from times(value)


def test_demo_shift_preserves_every_interval_and_original(snapshot):
    original = deepcopy(snapshot)
    anchor = datetime(2026, 12, 2, 8, 3, 59, tzinfo=timezone(timedelta(hours=9)))
    shifted = prepare_snapshot(snapshot, anchor, 'test')
    old_times, new_times = list(times(snapshot)), list(times(shifted))
    deltas = {new - old for old, new in zip(old_times, new_times, strict=True)}
    assert len(deltas) == 1
    assert shifted['as_of'] == '2026-12-01T23:03:00Z'
    assert shifted['scenario_id'] == 'S-demo-test' and shifted['plan_id'] == 'P-demo-test'
    assert shifted['baseline_assignments'][0]['pickup_departure_at'] < shifted['as_of']
    assert shifted['jobs'][0]['evidence']['observed_at'] is None
    assert snapshot == original


@pytest.mark.parametrize('url', ['https://127.0.0.1:8000', 'http://example.com',
                                 'http://localhost@evil.example', 'http://localhost:8000/path',
                                 'http://localhost:8000?token=x'])
def test_demo_never_sends_token_to_external_api(url):
    with pytest.raises(ValueError):
        http_client(url, 'test')


def test_demo_refuses_real_input_time_rewrite(snapshot):
    snapshot['data_mode'] = 'observed'
    with pytest.raises(ValueError):
        prepare_snapshot(snapshot, datetime.now(timezone.utc), 'test')


@pytest.mark.parametrize('review_only', [False, True])
def test_real_demo_flow_against_api(settings, snapshot, review_only):
    prepared = prepare_snapshot(snapshot, datetime.now(timezone.utc), 'roundtrip')
    with make_client(settings, replay=EngineReplay()) as client:
        def call(method, path, body=None, key=None):
            response = client.request(method, path, json=body if method == 'POST' else None,
                                      headers={'Idempotency-Key': key} if key else {})
            return response.status_code, response.json()
        result = run_demo(call, prepared, review_only=review_only)
        assert result['input_sha256'] == digest(prepared)
        assert result['current_plan']['version'] == (1 if review_only else 2)
        if review_only:
            assert result['approval'] is None
            assert not any(s['path'].endswith('/approvals') for s in result['http_steps'])
        else:
            assert result['approval']['external_actions_performed'] is False
            assert any(s['response'].get('code') == 'PLAN_VERSION_CONFLICT' for s in result['http_steps'])
            assert any(s['response'].get('code') == 'ACKNOWLEDGEMENT_REQUIRED' for s in result['http_steps'])
        assert [r['method'] for r in result['results']['results']] == ['B0', 'B1', 'B2', 'B3']
        assert 'Authorization' not in json.dumps(result)
        with client.app.state.store.db.connect() as conn:
            assert conn.execute('SELECT count(*) FROM runs').fetchone()[0] == 1
            assert conn.execute('SELECT count(*) FROM approvals').fetchone()[0] == (0 if review_only else 1)


def test_existing_evidence_directory_is_never_overwritten(tmp_path, monkeypatch):
    path = tmp_path / 'evidence'
    path.mkdir()
    marker = path / 'snapshot.json'
    marker.write_text('original', encoding='utf-8')
    monkeypatch.setenv('BANIPMATCH_DEMO_TOKEN', 'test-only-token')
    assert main(['--output', str(path)]) == 1
    assert marker.read_text(encoding='utf-8') == 'original'


def test_wrong_registered_input_hash_stops_before_run_or_approval(snapshot):
    calls = []
    def call(method, path, body=None, key=None):
        calls.append(path)
        return 201, {'input_sha256': 'wrong'}
    with pytest.raises(ValueError, match='해시'):
        run_demo(call, snapshot)
    assert calls == ['/v1/scenarios']
