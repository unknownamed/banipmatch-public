"""Offline synthetic acceptance data for #56; never sends or approves a plan."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from backend.api.contracts import ApiError, DRAFT, digest
from backend.api.input_preflight import check_input
from backend.api.result_integrity import verify_schedule
from backend.engine import solve
from backend.engine.recalculation import compare_recalculation
from tools.dispatch_response import CHECKS, build_response_preview

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'docs/data/response-acceptance-2026-11-11'
CONFIG = {'seed': 42, 'time_limit_seconds': 10}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')


def fixtures():
    base = read(DRAFT / '예제 데이터/01_snapshot.json')
    cases = []

    def add(name, snapshot, expected):
        snapshot['scenario_id'] = 'S56-' + name
        cases.append({'id': name, 'snapshot': snapshot, 'expected': expected})

    sequence = deepcopy(base)
    sequence['jobs'] = [j for j in sequence['jobs'] if j['job_id'] != 'J3']
    sequence['baseline_assignments'] = [a for a in sequence['baseline_assignments'] if a['job_id'] != 'J3']
    sequence['baseline_unassigned_job_ids'] = []
    add('sequence-resolves', sequence, {'unassigned': [], 'movable_violation_count': 0})
    late = deepcopy(base)
    late['jobs'][3]['ready_at'] = '2026-11-07T06:00:00Z'
    add('ready-too-late', late, {'unassigned': ['J3'], 'issue_code': 'READY_TOO_LATE'})
    shortage = deepcopy(base)
    for v in shortage['vehicles']:
        v['equipment_types'] = ['DRY20']
    add('equipment-shortage', shortage, {'unassigned': ['J1', 'J2', 'J3'], 'issue_code': 'INCOMPATIBLE_EQUIPMENT'})
    for name, source, expected in (
        ('fixed-risk', 'fixed_risk', {'issue_code': 'FIXED_RESIDUAL_RISK'}),
        ('missing-ready', 'ready_missing', {'blocked': 'INPUT_INCOMPLETE'}),
        ('unconfirmed-window', 'window_unconfirmed', {'blocked': 'WINDOW_UNCONFIRMED'}),
    ):
        add(name, read(ROOT / f'docs/experiments/data-demo-2026-11-10/inputs/{source}.json'), expected)
    add('search-limit', deepcopy(base), {'issue_code': 'SEARCH_LIMIT', 'proof_level': 'not_proven'})
    cases[-1]['fault_injection'] = 'solver monotonic [0, 11, 11], 10-second budget; not a speed benchmark'
    aligned = deepcopy(base)
    aligned_result = computed(aligned)
    aligned['baseline_assignments'] = deepcopy(aligned_result['assignments'])
    aligned['baseline_unassigned_job_ids'] = deepcopy(aligned_result['unassigned_job_ids'])
    add('unchanged-vehicles', deepcopy(aligned), {'no_changes': True})
    moved = deepcopy(aligned)
    old = next(a for a in moved['baseline_assignments'] if a['job_id'] == 'J1')
    old.update(vehicle_id='T1' if old['vehicle_id'] == 'T2' else 'T2', sequence=3)
    add('reassigned-both-vehicles', moved, {'reassignment_vehicles': ['T1', 'T2']})

    pairs = []
    for name in ('ready-only', 'extra-vehicle', 'missing-repaired', 'later-ready'):
        before, after = deepcopy(base), deepcopy(base)
        if name == 'missing-repaired':
            before['jobs'][3]['ready_at'] = None
        else:
            after['jobs'][3]['ready_at'] = '2026-11-07T00:00:00Z'
        if name == 'later-ready':
            after['jobs'][2]['ready_at'] = '2026-11-07T06:00:00Z'
        if name == 'extra-vehicle':
            vehicle = deepcopy(after['vehicles'][1])
            vehicle['vehicle_id'] = 'T3'
            vehicle['evidence']['source_ref'] = 'fixture:S56-assumed-extra-vehicle-not-recruited'
            after['vehicles'].append(vehicle)
        after['jobs'][3]['evidence']['source_ref'] = 'fixture:S56-assumed-ready-not-field-confirmed'
        before['scenario_id'] = after['scenario_id'] = 'S56-' + name
        pairs.append({'id': name, 'before': before, 'after': after,
                      'reason': '시연 가정: 준비/가용 조건 보완의 모의 비교, 현장 확인·차량 확보 아님',
                      'confirmation': 'assumed', 'actual_condition_confirmed': False})
    return cases, pairs


def computed(snapshot, *, force_timeout=False):
    check_input(snapshot)
    if force_timeout:
        with patch('backend.engine.solver.monotonic', side_effect=[0, 11, 11]):
            result = solve(snapshot, 'B1', CONFIG)
    else:
        result = solve(snapshot, 'B1', CONFIG)
    if not verify_schedule(snapshot, result):
        raise ValueError('Independent schedule check failed')
    result.update(validation_status='passed', approval_eligible=True)
    return result


def envelope(snapshot, result, run_id):
    return {'run_id': run_id, 'scenario_id': snapshot['scenario_id'],
            'base_plan_version': snapshot['base_plan_version'],
            'input_sha256': digest(snapshot), 'results': [result]}


def evaluate_case(case):
    snapshot, expected = case['snapshot'], case['expected']
    if snapshot['data_mode'] != 'simulated':
        raise ValueError('Only simulated acceptance inputs are supported')
    try:
        result = computed(snapshot, force_timeout=case['id'] == 'search-limit')
    except ApiError as error:
        if expected.get('blocked') != error.code:
            raise ValueError('Unexpected input rejection') from error
        return {'status': 'input_blocked', 'code': error.code, 'details': error.details}
    if 'blocked' in expected:
        raise ValueError('Incomplete input unexpectedly computed')
    if 'unassigned' in expected and result['unassigned_job_ids'] != expected['unassigned']:
        raise ValueError('Unexpected unassigned set')
    if 'movable_violation_count' in expected and result['metrics']['movable_violation_count'] != expected['movable_violation_count']:
        raise ValueError('Movable violation remains')
    if 'issue_code' in expected and expected['issue_code'] not in {i['code'] for i in result['issues']}:
        raise ValueError('Required reason missing')
    if 'proof_level' in expected and any(i['proof_level'] != expected['proof_level'] for i in result['issues'] if i['code'] == expected['issue_code']):
        raise ValueError('Search limit was presented as proof')
    preview = build_response_preview(snapshot, result)
    if expected.get('no_changes') and (preview['changes'] or preview['vehicle_changes']):
        raise ValueError('Unchanged vehicle was included as a delivery target')
    if 'reassignment_vehicles' in expected:
        targets = sorted(g['vehicle_id'] for g in preview['vehicle_changes'] if any(c['job_id'] == 'J1' for c in g['changes']))
        if targets != expected['reassignment_vehicles']:
            raise ValueError('Reassignment must include old and new vehicle')
    for followup in preview['followups']:
        if followup['code'] in CHECKS and followup['check_next'] != CHECKS[followup['code']][1]:
            raise ValueError('Followup mapping differs')
        original = next((i for i in result['issues'] if i == {k: followup[k] for k in i}), None)
        if followup['code'] != 'REASON_NOT_PROVIDED' and original is None:
            raise ValueError('Issue proof/evidence was changed')
    frozen = {j['job_id'] for j in snapshot['jobs'] if j['frozen']}
    for assignment in snapshot['baseline_assignments']:
        if assignment['job_id'] in frozen and assignment not in result['assignments']:
            raise ValueError('Frozen assignment lost')
    return {'status': 'computed', 'result': result, 'preview': preview}


def evaluate_pair(pair):
    before, after = pair['before'], pair['after']
    if (before['data_mode'] != 'simulated' or after['data_mode'] != 'simulated'
            or pair['confirmation'] != 'assumed' or pair['actual_condition_confirmed'] is not False):
        raise ValueError('Condition fixtures must preserve the hypothetical boundary')
    try:
        old = envelope(before, computed(before), pair['id'] + '-before')
    except ApiError:
        old = None
    new = envelope(after, computed(after), pair['id'] + '-after')
    comparison = compare_recalculation(before, old, after, new, method='B1', reason=pair['reason'])
    transitions = comparison['job_transitions']
    if pair['id'] == 'ready-only' and transitions['remained_unassigned'] != ['J3']:
        raise ValueError('Readiness alone incorrectly promised success')
    if pair['id'] == 'extra-vehicle' and (transitions['became_assigned'] != ['J3'] or comparison['efficiency_delta'] is not None):
        raise ValueError('Additional capacity must not imply same-work efficiency')
    if pair['id'] == 'missing-repaired' and (comparison['before']['status'] != 'input_blocked' or comparison['metric_deltas'] is not None):
        raise ValueError('Blocked input was invented as zero baseline')
    if pair['id'] == 'later-ready' and transitions['became_unassigned'] != ['J2']:
        raise ValueError('New unresolved job was hidden')
    return {'before_results': old, 'after_results': new, 'comparison': comparison}


def audit(directory=DEFAULT):
    manifest = read(directory / 'manifest.json')
    if manifest['kind'] != 'simulated' or manifest['external_actions_performed'] is not False:
        raise ValueError('Synthetic boundary missing')
    for name, expected in manifest['sha256'].items():
        path = (directory/name).resolve()
        if not path.is_relative_to(directory.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Fixture path or hash differs')
    for entry in manifest['cases']:
        if entry not in manifest['sha256']:
            raise ValueError('Case is not a hashed archive member')
        evaluate_case(read(directory / entry))
    for entry in manifest['pairs']:
        if entry not in manifest['sha256']:
            raise ValueError('Pair is not a hashed archive member')
        evaluate_pair(read(directory / entry))
    delivery = read(directory/'delivery-cases.json')
    if (delivery['kind'] != 'simulated' or delivery['real_phone_verified'] is not False
            or delivery['external_actions_performed'] is not False):
        raise ValueError('Delivery examples cannot claim real phone verification')
    if len({c['id'] for c in delivery['cases']}) != len(delivery['cases']):
        raise ValueError('Duplicate delivery case')
    return {'valid': True, 'calculated_cases': len(manifest['cases']), 'condition_pairs': len(manifest['pairs']),
            'delivery_examples': len(read(directory/'delivery-cases.json')['cases']), 'external_calls': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--directory', type=Path, default=DEFAULT)
    args = parser.parse_args()
    try:
        if not args.check:
            cases, pairs = fixtures()
            args.directory.mkdir(parents=True, exist_ok=False)
            files, manifest = {}, {'kind': 'simulated', 'source_main': 'e18b77f',
                'external_actions_performed': False, 'method': 'B1', 'config': CONFIG, 'cases': [], 'pairs': []}
            for group, rows, evaluate in (('cases', cases, evaluate_case), ('pairs', pairs, evaluate_pair)):
                for row in rows:
                    name = group + '/' + row['id'] + '.json'
                    files[name] = encoded(row)
                    files['results/' + row['id'] + '.json'] = encoded(evaluate(row))
                    manifest[group].append(name)
            # Delivery fixtures are curated separately; no fake provider success is generated here.
            files['delivery-cases.json'] = (ROOT/'tools/fixtures/response-delivery-cases.json').read_bytes()
            manifest['sha256'] = {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}
            files['manifest.json'] = encoded(manifest)
            for name, raw in files.items():
                path = args.directory/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
        print(json.dumps(audit(args.directory)))
        return 0
    except (OSError, ValueError, KeyError, TypeError):
        print('검수 실패: 새 출력 폴더·자료 해시·예상 판정을 확인하세요. 원문은 출력하지 않습니다.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
