"""보고서 5.2 추가 실험 2가지 (2026-11-13).

1) 실제 HJNC 항차 사례: HJNC 공개 선석 배정을 두 번 수집한 기록(11/11 18:53, 11/13 00:26 KST)에서
   같은 항차의 반입 마감이 실제로 바뀐 것을 찾고, 앞당겨진 항차 가운데 시연 사례(2시간 30분)와 크기가
   가장 가까운 항차를 미리 정한 규칙으로 고른다. 그 항차의 실제 반입 시작·이전 마감·새 마감을 넣고,
   배차표(작업 20건·차량 8대)는 시연과 같은 모의 자료를 시각만 옮겨 쓴다. 변경을 알게 된 시점은 알 수
   없으므로 시연과 같이 '이전 마감 4시간 전'으로 가정한다.
2) 50건 분할 계산: 80회 평가의 50건 입력(항차 2개 × 25건, 차량 8대)을 전체로 한 번에 계산한 것과,
   마감이 바뀐 항차의 작업만 다시 계산하고 다른 항차 작업은 원래 배차로 고정한 것(항차 단위 분할)을 비교한다.

사용: python docs/experiments/real-voyage-and-split-2026-11-13/run.py
HJNC 수집본 두 개는 같은 폴더의 hjnc-snapshots.json에 있다(항차·반입 시작·마감·접안 예정만).
"""
import copy, json, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from backend.engine.solver import solve  # noqa: E402
from backend.data.validation import validate_snapshot  # noqa: E402

# 엔진과 별개인 일정 검사기(tools/check_engine_robustness.py의 check)를 그대로 쓴다.
_src = (ROOT / 'tools/check_engine_robustness.py').read_text(encoding='utf-8')
_ns = dict(T=lambda v: datetime.fromisoformat(v.replace('Z', '+00:00')), timedelta=timedelta)
exec(_src[_src.index('def check('):_src.index('seen, rows, bad')], _ns)
check = _ns['check']

KST = timezone(timedelta(hours=9))
ISO = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')


def utc(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def z(d):
    return d.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def hjnc_local(s):  # HJNC 화면 시각(한국 시각, 분 단위)
    return datetime.strptime(s, '%Y-%m-%d %H:%M').replace(tzinfo=KST)


def shift_all(o, delta):
    if isinstance(o, dict):
        return {k: shift_all(v, delta) for k, v in o.items()}
    if isinstance(o, list):
        return [shift_all(v, delta) for v in o]
    if isinstance(o, str) and ISO.match(o):
        return z(utc(o) + delta)
    return o


def summarize(snap, res):
    late = {i['job_id'] for i in res['issues'] if i.get('job_id') and i['code'] in ('CUTOFF_EXCEEDED', 'READY_TOO_LATE')}
    st = res.get('objective_stages') or []
    return dict(status=res['solution_status'], proven=res.get('objective_proven'),
                stages=[(s['objective'], s['status']) for s in st],
                unassigned=len(res['unassigned_job_ids']), late_or_unassigned=len(late | set(res['unassigned_job_ids'])),
                changed=len(res['metrics']['changed_job_ids']), travel_min=res['metrics']['movable_travel_minutes'],
                fixed_risk=res['metrics']['fixed_risk_count'], ms=res['metrics'].get('solve_time_ms'),
                drivers=len({a['vehicle_id'] for a in res['assignments'] if a['job_id'] in set(res['metrics']['changed_job_ids'])}),
                rule_violations=check(snap, res))


out = {}

# ---------- 1) 실제 HJNC 항차 ----------
if len(sys.argv) > 2:  # 서버 수집 파일 두 개를 직접 줄 때
    A, B = (json.loads(Path(p).read_text(encoding='utf-8'))['hjnc']['current'] for p in sys.argv[1:3])
else:  # 기본: 같은 폴더에 남긴 두 수집본
    A, B = json.loads(Path(__file__).with_name('hjnc-snapshots.json').read_text(encoding='utf-8'))['snapshots']
a = {i['values']['VOY_NO']: i['values'] for i in A['items']}
b = {i['values']['VOY_NO']: i['values'] for i in B['items']}
common = sorted(set(a) & set(b))
changes = []
for v in common:
    if a[v]['YARD_CLOSE'] != b[v]['YARD_CLOSE']:
        mins = int((hjnc_local(b[v]['YARD_CLOSE']) - hjnc_local(a[v]['YARD_CLOSE'])).total_seconds() // 60)
        changes.append(dict(voyage=v, before=a[v], after=b[v], close_shift_min=mins))
earlier = [c for c in changes if c['close_shift_min'] < 0]
later = [c for c in changes if c['close_shift_min'] > 0]
# 규칙: 앞당김 중 시연(-150분)과 가장 가까운 크기, 같으면 항차 번호순
pick = sorted(earlier, key=lambda c: (abs(c['close_shift_min'] + 150), c['voyage']))[0]
out['hjnc_observation'] = dict(
    received_at=[A['received_at'], B['received_at']], rows=[len(a), len(b)], common=len(common),
    close_changed=len(changes), earlier=len(earlier), later=len(later),
    earlier_minutes=sorted(c['close_shift_min'] for c in earlier), later_minutes=sorted(c['close_shift_min'] for c in later),
    close_equals_etb_minus_10h=all(hjnc_local(c['after']['ETB']) - hjnc_local(c['after']['YARD_CLOSE']) == timedelta(hours=10) for c in changes),
    picked=pick, common_rows=[dict(voyage=v, before=a[v], after=b[v]) for v in common])

demo = json.loads((ROOT / 'frontend/src/fixtures/demo-02-evening.synthetic.json').read_text(encoding='utf-8'))
old_close, new_close = hjnc_local(pick['before']['YARD_CLOSE']), hjnc_local(pick['after']['YARD_CLOSE'])
opens = hjnc_local(pick['after']['YARD_OPEN'])
delta = old_close - utc(demo['change']['previous_closes_at'])  # 시연의 '이전 마감'을 실제 이전 마감에 맞춘다
s = shift_all(demo, delta)
OLD_V, NEW_V = demo['change']['voyage_id'], pick['voyage']
for j in s['jobs']:
    if j['voyage_id'] == OLD_V:
        j['voyage_id'] = NEW_V
ref = dict(kind='observed', source_ref='https://www.hjnc.co.kr/esvc/vessel/berthScheduleT', observed_at=None,
           received_at=B['received_at'][:17] + '00Z')  # 엔진 입력은 분 단위만 받으므로 수신 시각의 초를 버림(원래 값은 hjnc_observation에 보존)
for w in s['windows']:
    if w['voyage_id'] == OLD_V:
        w.update(voyage_id=NEW_V, window_id='W-' + NEW_V, opens_at=z(opens), closes_at=z(new_close), evidence=ref)
s['change'].update(voyage_id=NEW_V, new_window_id='W-' + NEW_V, previous_opens_at=z(hjnc_local(pick['before']['YARD_OPEN'])),
                   previous_closes_at=z(old_close), evidence=ref)
s['scenario_id'] = 'S-REAL-' + NEW_V
rep = validate_snapshot(s)
case = dict(voyage=NEW_V, as_of=s['as_of'], as_of_kst=utc(s['as_of']).astimezone(KST).strftime('%m-%d %H:%M'),
            previous_close_kst=old_close.strftime('%m-%d %H:%M'), new_close_kst=new_close.strftime('%m-%d %H:%M'),
            jobs_on_voyage=sum(j['voyage_id'] == NEW_V for j in s['jobs']), jobs=len(s['jobs']), vehicles=len(s['vehicles']),
            frozen=sum(j['frozen'] for j in s['jobs']), input_ok=bool(getattr(rep, 'ok', True)), methods={})
for m in ('B0', 'B1', 'B2', 'B3'):
    case['methods'][m] = summarize(s, solve(s, m, dict(seed=0, time_limit_seconds=10)))
out['real_voyage_case'] = case
print('HJNC 관측:', {k: v for k, v in out['hjnc_observation'].items() if k != 'picked'})
print('선택 항차:', NEW_V, pick['before']['YARD_CLOSE'], '→', pick['after']['YARD_CLOSE'])
for m, r in case['methods'].items():
    print(' ', m, {k: r[k] for k in ('status', 'proven', 'late_or_unassigned', 'changed', 'drivers', 'travel_min', 'ms')}, '위반', len(r['rule_violations']))

# ---------- 2) 50건 분할 계산 ----------
big = json.loads((ROOT / 'docs/experiments/engine-evaluation-2026-11-08/inputs/eval_cutoff_50_404.json').read_text(encoding='utf-8'))
changed_v = big['change']['voyage_id']
base_assigned = {x['job_id'] for x in big['baseline_assignments']}
split = copy.deepcopy(big)
locked = 0
for j in split['jobs']:
    if j['voyage_id'] != changed_v and j['job_id'] in base_assigned and not j['frozen']:
        j['frozen'], j['freeze_reason'] = True, 'UNAFFECTED_VOYAGE_KEPT'
        locked += 1
runs = {}
for label, snap, limit in (('전체 10초', big, 10), ('전체 60초', big, 60), ('분할 10초', split, 10)):
    for m in ('B2', 'B3'):
        runs[f'{label} {m}'] = summarize(snap, solve(snap, m, dict(seed=0, time_limit_seconds=limit)))
runs['원래 배차 B0'] = summarize(big, solve(big, 'B0', dict(seed=0, time_limit_seconds=10)))
out['split_50'] = dict(changed_voyage=changed_v, jobs=len(big['jobs']), vehicles=len(big['vehicles']),
                       jobs_by_voyage={v: sum(j['voyage_id'] == v for j in big['jobs']) for v in sorted({j['voyage_id'] for j in big['jobs']})},
                       locked_jobs=locked, runs=runs)
for k, r in runs.items():
    print(' ', k, {x: r[x] for x in ('status', 'proven', 'late_or_unassigned', 'unassigned', 'changed', 'drivers', 'travel_min', 'ms')}, r['stages'], '위반', len(r['rule_violations']))

dest = Path(__file__).with_name('result.json')
dest.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
print('저장:', dest.relative_to(ROOT))
