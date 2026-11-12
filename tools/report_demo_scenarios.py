"""시연 공지 5종을 B0~B3로 계산해 보고서 표의 원자료를 남긴다.
사용: python tools/report_demo_scenarios.py [출력 JSON]
화면은 이 입력을 '지금' 시각으로 옮겨 쓰므로 시각은 다르지만 작업·차량·간격 구조는 같다."""
import json, sys
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.engine.solver import solve  # noqa: E402
from backend.data.validation import validate_snapshot  # noqa: E402

CASES = [
    ('BHMN 마감 2시간 30분 앞당김(확정)', 'demo-02-evening'),
    ('BE221E 마감 1시간 30분 앞당김(확정)', 'demo-02-minor-earlier'),
    ('BPNR 마감 1시간 늦춰짐(확정)', 'demo-02-later'),
    ('BORT 마감 앞당김 예정(확정 전)', 'demo-02-unconfirmed'),
    ('상차 준비 시각 미입력', 'demo-02-missing-ready'),
]
rows = []
for label, name in CASES:
    snap = json.loads((ROOT / 'frontend/src/fixtures' / f'{name}.synthetic.json').read_text(encoding='utf-8'))
    report = validate_snapshot(snap)
    issues = [i.code if hasattr(i, 'code') else i.get('code') for i in getattr(report, 'issues', [])] if not getattr(report, 'ok', True) else []
    row = {'case': label, 'fixture': name, 'jobs': len(snap['jobs']), 'vehicles': len(snap['vehicles']),
           'frozen': sum(j['frozen'] for j in snap['jobs']), 'blocked': bool(issues), 'block_codes': sorted(set(issues)), 'methods': {}}
    if not issues:
        for m in ('B0', 'B1', 'B2', 'B3'):
            try:
                r = solve(snap, m, dict(seed=0, time_limit_seconds=10))
            except Exception as e:  # 입력 보류 등
                row['methods'][m] = {'error': type(e).__name__}
                continue
            late = {i['job_id'] for i in r['issues'] if i.get('job_id') and i['code'] in ('CUTOFF_EXCEEDED', 'READY_TOO_LATE')}
            row['methods'][m] = {'status': r['solution_status'], 'unassigned': len(r['unassigned_job_ids']),
                                 'late_or_unassigned': len(late | set(r['unassigned_job_ids'])),
                                 'changed': len(r['metrics']['changed_job_ids']), 'travel_min': r['metrics']['movable_travel_minutes'],
                                 'fixed_risk': r['metrics']['fixed_risk_count'], 'ms': r['metrics'].get('solve_time_ms')}
    rows.append(row)
    print(label, row['jobs'], row['vehicles'], 'blocked' if issues else '', {k: (v.get('late_or_unassigned'), v.get('changed'), v.get('travel_min'), v.get('status')) for k, v in row['methods'].items()})
# 조건 보완 사례: BHMN에서 남은 1건(J08)의 상차 준비를 40분 앞당기고, 녹산 차고지 차량 1대를 추가해 같은 기준 시각으로 B3 재계산.
import copy  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
base = json.loads((ROOT / 'frontend/src/fixtures/demo-02-evening.synthetic.json').read_text(encoding='utf-8'))
def _shift(v, m): return (datetime.fromisoformat(v.replace('Z', '+00:00')) + timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%M:%SZ')
revision = {}
for label, add_vehicle in (('준비 40분 앞당김', False), ('준비 40분 앞당김 + 차량 1대 추가', True)):
    s = copy.deepcopy(base)
    job = next(j for j in s['jobs'] if j['job_id'] == 'J08'); job['ready_at'] = _shift(job['ready_at'], -40)
    if add_vehicle:
        extra = copy.deepcopy(next(v for v in s['vehicles'] if v['vehicle_id'] == 'T3')); extra['vehicle_id'] = 'T9'; extra['available_at'] = job['ready_at']
        s['vehicles'].append(extra)
    r = solve(s, 'B3', dict(seed=0, time_limit_seconds=10))
    revision[label] = {'status': r['solution_status'], 'unassigned': r['unassigned_job_ids'], 'changed': len(r['metrics']['changed_job_ids'])}
    print('조건 보완', label, revision[label])
rows.append({'case': 'BHMN 조건 보완(B3, 같은 기준 시각)', 'fixture': 'demo-02-evening', 'revision': revision})
out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'docs/experiments/demo-scenarios-2026-11-13/result.json'
out.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
