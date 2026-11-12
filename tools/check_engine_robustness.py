"""
사용: python tools/check_engine_robustness.py [저장소 경로]
하드코딩 여부 점검: 시연 입력을 무작위로 바꿔 실제 엔진(B1·B3)에 넣고, 결과 일정을 엔진과 별개인 규칙 검사기로 확인한다."""
import copy, json, random, sys
from datetime import datetime, timedelta, timezone

ROOT = sys.argv[1] if len(sys.argv) > 1 else '.'
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding='utf-8')
from backend.engine.solver import solve  # noqa: E402
from backend.data.validation import validate_snapshot  # noqa: E402

T = lambda s: datetime.fromisoformat(s.replace('Z', '+00:00'))
Z = lambda d: d.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
base = json.load(open(ROOT + '/frontend/src/fixtures/demo-02-evening.synthetic.json', encoding='utf-8'))


def perturb(seed):
    r = random.Random(seed)
    s = copy.deepcopy(base)
    for j in s['jobs']:
        if not j['frozen'] and r.random() < 0.4:
            j['ready_at'] = Z(T(j['ready_at']) + timedelta(minutes=r.randint(-60, 90)))
    for w in s['windows']:
        if w['window_id'] == s['change']['new_window_id']:
            w['closes_at'] = Z(T(w['closes_at']) + timedelta(minutes=r.choice([-60, -30, 0, 30, 60])))
    busy = {a['vehicle_id'] for a in s['baseline_assignments'] if next(j for j in s['jobs'] if j['job_id'] == a['job_id'])['frozen']}
    free = [v for v in s['vehicles'] if v['vehicle_id'] not in busy]
    if free and r.random() < 0.5:
        v = r.choice(free)
        v['shift_end_at'] = v['available_at']  # 오늘 운행 불가
    return s


def check(s, res):
    jobs = {j['job_id']: j for j in s['jobs']}
    veh = {v['vehicle_id']: v for v in s['vehicles']}
    tt = {(t['from_location_id'], t['to_location_id']): t['minutes'] for t in s['travel_times']}
    cut = {(w['voyage_id'], w['terminal_id']): T(w['closes_at']) for w in s['windows']}
    buf = timedelta(minutes=s['policy']['buffer_minutes'])
    flagged = {(i['job_id'], i['code']) for i in res['issues']}
    errs = []
    ids = [a['job_id'] for a in res['assignments']] + res['unassigned_job_ids']
    if sorted(ids) != sorted(jobs):
        errs.append('작업 누락·중복')
    base_a = {a['job_id']: a for a in s['baseline_assignments']}
    by_v = {}
    for a in res['assignments']:
        j = jobs[a['job_id']]
        if j['frozen']:
            if a != base_a[a['job_id']]:
                errs.append(f"고정 작업 변경 {a['job_id']}")
            by_v.setdefault(a['vehicle_id'], []).append(a)
            continue
        v = veh[a['vehicle_id']]
        dep, arr, ret = T(a['pickup_departure_at']), T(a['gate_arrival_at']), T(a['return_at'])
        if dep < T(j['ready_at']) and (a['job_id'], 'READY_TOO_LATE') not in flagged:
            errs.append(f"준비 전 출발 {a['job_id']}")
        if arr < dep + timedelta(minutes=tt[(j['origin_id'], j['terminal_id'])]):
            errs.append(f"이동시간 부족 {a['job_id']}")
        if arr + buf > cut[(j['voyage_id'], j['terminal_id'])] and (a['job_id'], 'CUTOFF_EXCEEDED') not in flagged:
            errs.append(f"표시 안 된 마감 초과 {a['job_id']}")
        if ret < arr + timedelta(minutes=j['service_minutes'] + tt[(j['terminal_id'], j['return_location_id'])]):
            errs.append(f"복귀 시간 부족 {a['job_id']}")
        if ret > T(v['shift_end_at']) and (a['job_id'], 'SHIFT_EXCEEDED') not in flagged:
            errs.append(f"표시 안 된 근무 초과 {a['job_id']}")
        if j['equipment_type'] not in v['equipment_types'] or j['gross_weight_kg'] > v['capacity_kg']:
            errs.append(f"규격·중량 불일치 {a['job_id']}")
        by_v.setdefault(a['vehicle_id'], []).append(a)
    for vid, lst in by_v.items():
        lst.sort(key=lambda a: a['pickup_departure_at'])
        v = veh[vid]
        loc, free = v['start_location_id'], T(v['available_at'])
        for a in lst:
            j = jobs[a['job_id']]
            if not j['frozen'] and T(a['pickup_departure_at']) < free + timedelta(minutes=tt[(loc, j['origin_id'])]):
                errs.append(f"차량 일정 겹침 {vid}:{a['job_id']}")
            loc, free = j['return_location_id'], T(a['return_at'])
    return errs


seen, rows, bad = set(), [], 0
for seed in range(12):
    s = perturb(seed)
    rep = validate_snapshot(s)
    if not getattr(rep, 'ok', True) and getattr(rep, 'errors', None):
        rows.append((seed, '입력 거절', '')); continue
    for m in ('B1', 'B3'):
        res = solve(s, m, dict(seed=seed, time_limit_seconds=3))
        e = check(s, res)
        bad += len(e)
        key = (m, tuple(sorted((a['job_id'], a['vehicle_id'], a['pickup_departure_at']) for a in res['assignments'])))
        seen.add(key)
        rows.append((seed, m, f"미배정 {len(res['unassigned_job_ids'])}, 변경 {len(res['metrics']['changed_job_ids'])}, 상태 {res['solution_status']}, 규칙 위반 {len(e)}" + (f" {e[:3]}" if e else '')))
for r in rows:
    print(*r)
print('서로 다른 결과 수:', len(seen), '/ 실행', sum(1 for r in rows if r[1] in ('B1', 'B3')), '/ 표시 안 된 규칙 위반 합계:', bad)
