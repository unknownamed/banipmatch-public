"""Acceptance artifacts must retain failures and never solve rejected inputs."""
from copy import deepcopy
import json

import pytest

from backend.api.contracts import ApiError
from backend.api.input_preflight import check_input
from backend.engine import solve
from tools import data_demo_acceptance as demo


def test_all_cases_have_explicit_preflight_expectations_and_distinct_ids():
    cases = demo.make_cases()
    assert len(cases) == len({c['snapshot']['scenario_id'] for c in cases}) == 9
    for case in cases:
        try:
            check_input(case['snapshot'])
            actual = None
        except ApiError as error:
            actual = error.code
        assert actual == case['expected_preflight']
        assert case['snapshot']['data_mode'] == 'simulated'
        assert not case['snapshot']['policy']['external_actions_enabled']
    route = next(c['snapshot'] for c in cases if c['id'] == 'route_missing')
    assert not any((r['from_location_id'], r['to_location_id']) == ('O', 'HJNC') for r in route['travel_times'])
    assert any((r['from_location_id'], r['to_location_id']) == ('HJNC', 'O') for r in route['travel_times'])


def test_time_shift_preserves_intervals_and_missing_values():
    a, b = demo.make_cases(), demo.make_cases('2026-12-01T07:30:00Z')
    delta = demo.at(b[0]['snapshot']['as_of']) - demo.at(a[0]['snapshot']['as_of'])
    for first, second in zip(a, b):
        assert first['expected_preflight'] == second['expected_preflight']
        for old, new in zip(first['snapshot']['baseline_assignments'], second['snapshot']['baseline_assignments']):
            assert old['job_id'] == new['job_id']
            if old['return_at'] is None:
                assert new['return_at'] is None
            else:
                assert demo.at(new['return_at']) - demo.at(old['return_at']) == delta


def test_real_solver_pack_preserves_fixed_records_and_does_not_solve_missing_data(tmp_path):
    demo.build(tmp_path / 'pack', '2026-11-10T00:00:00Z')
    called = []
    def recording(snapshot, method, config):
        called.append(snapshot['scenario_id'])
        return solve(snapshot, method, config)
    summary = demo.run(tmp_path / 'pack/protocol.json', tmp_path / 'results', recording)
    assert summary['passed'] and summary['solver_calls'] == len(called) == 16
    assert len(summary['pairs']) == 4
    assert all(c['solver_calls'] == 0 for c in summary['cases'] if c['expected'])
    records = [json.loads(s) for s in (tmp_path / 'results/results.jsonl').read_text(encoding='utf-8').splitlines()]
    assert all(r['fixed_preserved'] for r in records)
    assert all(r['result']['metrics']['fixed_risk_count'] > 0 for r in records if r['case_id'] == 'fixed_risk')
    assert all(r['result']['metrics']['movable_violation_count'] == 0 for r in records if r['method'] != 'B0')
    assert all(not r['result']['approval_eligible'] for r in records)


@pytest.mark.parametrize('mode', ['exception', 'mutation', 'fixed_loss'])
def test_bad_solver_output_is_preserved_as_failure_not_retried(tmp_path, mode):
    demo.build(tmp_path / 'pack', '2026-11-10T00:00:00Z')
    fixture = demo.make_cases()[0]['snapshot']
    base = solve(fixture, 'B1', {'seed': 42, 'time_limit_seconds': 3})
    def broken(snapshot, method, config):
        if mode == 'exception':
            raise RuntimeError('deliberate test')
        result = deepcopy(base)
        result['method'] = method
        if mode == 'mutation':
            snapshot['scenario_id'] = 'changed'
        else:
            result['assignments'] = [r for r in result['assignments'] if r['job_id'] != 'J0']
        return result
    summary = demo.run(tmp_path / 'pack/protocol.json', tmp_path / 'results', broken)
    assert not summary['passed'] and summary['solver_calls'] == 16
    assert all(not p['equal_count_comparable'] for p in summary['pairs'])
    records = [json.loads(s) for s in (tmp_path / 'results/results.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(records) == 16 and all('error_type' in r for r in records)


def test_changed_input_and_existing_output_are_not_overwritten(tmp_path):
    demo.build(tmp_path / 'pack', '2026-11-10T00:00:00Z')
    with pytest.raises(FileExistsError):
        demo.build(tmp_path / 'pack', '2026-11-10T00:00:00Z')
    path = tmp_path / 'pack/inputs/cutoff.json'
    value = json.loads(path.read_text(encoding='utf-8'))
    value['policy']['buffer_minutes'] += 1
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError, match='hash mismatch'):
        demo.run(tmp_path / 'pack/protocol.json', tmp_path / 'results')
    assert not (tmp_path / 'results').exists()
