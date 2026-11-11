import json
import shutil

import pytest

from tools.response_acceptance import DEFAULT, audit, evaluate_case, evaluate_pair, fixtures, read


def test_archived_acceptance_inputs_replay_with_independent_schedule_checks():
    report = audit()
    assert report == {'valid': True, 'calculated_cases': 9, 'condition_pairs': 4,
                      'delivery_examples': 15, 'external_calls': 0}
    cases, pairs = fixtures()
    for group, generated in [('cases', cases), ('pairs', pairs)]:
        assert [read(DEFAULT / f'{group}/{row["id"]}.json') for row in generated] == generated


def test_readiness_repair_is_not_guaranteed_success_or_a_zero_baseline():
    _, pairs = fixtures()
    outputs = {p['id']: evaluate_pair(p)['comparison'] for p in pairs}
    assert outputs['ready-only']['job_transitions']['remained_unassigned'] == ['J3']
    assert outputs['missing-repaired']['before']['status'] == 'input_blocked'
    assert outputs['missing-repaired']['metric_deltas'] is None
    assert outputs['extra-vehicle']['efficiency_delta'] is None
    assert outputs['later-ready']['job_transitions']['became_unassigned'] == ['J2']
    assert all(p['confirmation'] == 'assumed' and not p['actual_condition_confirmed'] for p in pairs)
    assert all(not x['external_actions_performed'] and not x['delivery_authorized'] for x in outputs.values())


def test_issue_proof_and_refs_survive_instructions_and_timeout_is_not_impossible():
    cases, _ = fixtures()
    timeout = evaluate_case(next(c for c in cases if c['id'] == 'search-limit'))
    result, preview = timeout['result'], timeout['preview']
    assert result['execution_metadata']['solver_settings']['time_limit_reached']
    assert not result['objective_proven']
    for issue in result['issues']:
        if issue['code'] == 'SEARCH_LIMIT':
            assert issue['proof_level'] == 'not_proven'
            followup = next(f for f in preview['followups'] if all(f[k] == v for k, v in issue.items()))
            assert '단정하지' in followup['check_next']
    assert not preview['delivery_authorized']


def test_vehicle_targets_preserve_both_sides_exclude_unchanged_and_do_not_cancel_transport():
    cases, _ = fixtures()
    output = {c['id']: evaluate_case(c) for c in cases}
    assert output['unchanged-vehicles']['preview']['vehicle_changes'] == []
    groups = output['reassigned-both-vehicles']['preview']['vehicle_changes']
    assert {g['vehicle_id'] for g in groups if any(c['job_id'] == 'J1' for c in g['changes'])} == {'T1', 'T2'}
    removed = next(c for c in output['ready-too-late']['preview']['changes'] if c['job_id'] == 'J3')
    assert removed['kind'] == 'removed_from_plan'
    assert '실제 운송 취소를 뜻하지' in removed['instruction']


@pytest.mark.parametrize('mutation', ['bytes', 'path', 'case_path', 'claims'])
def test_archive_corruption_and_real_delivery_claims_are_rejected(tmp_path, mutation):
    target = tmp_path/'fixtures'
    shutil.copytree(DEFAULT, target)
    if mutation == 'bytes':
        (target/'cases/ready-too-late.json').write_bytes(b'{}')
    else:
        path = target/'manifest.json'
        manifest = read(path)
        if mutation == 'path':
            manifest['sha256']['../../private-file'] = '0'*64
        elif mutation == 'case_path':
            manifest['cases'][0] = '../../private-file'
        else:
            manifest['external_actions_performed'] = True
        path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        audit(target)


def test_delivery_expectations_do_not_promote_network_or_human_states():
    data = read(DEFAULT/'delivery-cases.json')
    assert not data['real_phone_verified'] and not data['external_actions_performed']
    cases = {c['id']: c for c in data['cases']}
    assert cases['accepted-unread']['expected']['response'] == 'none'
    assert cases['opened-only']['expected']['response'] == 'none'
    assert cases['acknowledged']['expected']['response'] == 'acknowledged'
    assert cases['cannot-perform']['expected']['automatic_recalculation'] is False
    assert cases['unknown']['expected']['additional_provider_calls'] == 0
    assert cases['old-plan']['expected']['payload'] is None
    assert cases['other-recipient']['expected']['response_saved'] is False
