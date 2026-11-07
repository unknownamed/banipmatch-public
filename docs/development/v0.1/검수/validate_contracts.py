"""공유 명세/예제 검증. 실제 웹서버·최적화 엔진·승인 로직 구현이 아니다."""
from pathlib import Path
from datetime import datetime,timedelta
import json,copy,hashlib
from jsonschema import Draft202012Validator,FormatChecker
from openapi_spec_validator import validate
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
SCHEMA=read('공통 규격/contracts.schema.json');OAS=read('공통 규격/openapi.json')
checks=[]
def check(name,ok,details=''):
    checks.append({'name':name,'passed':bool(ok),'details':details})
    if not ok:raise AssertionError((name,details))
def validator(name):return Draft202012Validator({'$schema':SCHEMA['$schema'],'$defs':SCHEMA['$defs'],'$ref':'#/$defs/'+name},format_checker=FormatChecker())
Draft202012Validator.check_schema(SCHEMA);check('JSON Schema 구문',True)
validate(OAS);check('OpenAPI 3.1 문서 검증',True)
def norm(x):
    if isinstance(x,dict):return {k:(v.replace('#/components/schemas/','#/$defs/') if k=='$ref' else norm(v)) for k,v in x.items()}
    if isinstance(x,list):return [norm(v) for v in x]
    return x
check('OpenAPI/공통 객체 동일',norm(OAS['components']['schemas'])==SCHEMA['$defs'])
cases={'01_snapshot.json':'Snapshot','02_run_request.json':'RunRequest','03_run_status.json':'Run','04_results_설명용.json':'Results','05_approval_request.json':'ApprovalRequest','06_error_version_conflict.json':'Error','07_snapshot_입력누락.json':'Snapshot','08_snapshot_미확인변경.json':'Snapshot'}
for f,name in cases.items():
    errors=list(validator(name).iter_errors(read('예제 데이터/'+f)))
    check('예제 구조 '+f,not errors,'; '.join(e.message for e in errors))
snap=read('예제 데이터/01_snapshot.json');results=read('예제 데이터/04_results_설명용.json');run=read('예제 데이터/03_run_status.json');req=read('예제 데이터/02_run_request.json')
sha=hashlib.sha256(json.dumps(snap,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
check('입력 해시 일치',results['input_sha256']==sha)
check('요청/실행/결과 방법 일치',req['methods']==run['methods']==[r['method'] for r in results['results']])
check('실행 설정 보존',run['config']=={k:req[k] for k in ['seed','time_limit_seconds']})
def dt(t):return datetime.fromisoformat(t.replace('Z','+00:00'))
def minutes(t,n):return dt(t)+timedelta(minutes=n)
def input_issues(s):
    issues=[]
    def issue(code):issues.append(code)
    if s['change']['verification']!='confirmed':issue('WINDOW_UNCONFIRMED')
    for label,key in [('locations','location_id'),('vehicles','vehicle_id'),('jobs','job_id'),('windows','window_id')]:
        ids=[x[key] for x in s[label]]
        if len(ids)!=len(set(ids)):issue('DUPLICATE_ID')
    locs={x['location_id'] for x in s['locations']};vehicles={x['vehicle_id'] for x in s['vehicles']};jobs={x['job_id'] for x in s['jobs']}
    for j in s['jobs']:
        if any(j[k] not in locs for k in ['origin_id','terminal_id','return_location_id']):issue('UNKNOWN_LOCATION')
        if any(j[k] is None for k in ['ready_at','gross_weight_kg','service_minutes']):issue('INPUT_MISSING')
        if j['state']=='departed' and not j['frozen']:issue('DEPARTED_MUST_FREEZE')
    for a in s['baseline_assignments']:
        if a['job_id'] not in jobs or a['vehicle_id'] not in vehicles:issue('UNKNOWN_ASSIGNMENT_ID')
    baseids=[a['job_id'] for a in s['baseline_assignments']]
    unassigned=set(s['baseline_unassigned_job_ids'])
    if len(baseids)!=len(set(baseids)) or set(baseids)|unassigned!=jobs or set(baseids)&unassigned:issue('BASELINE_COVERAGE')
    if any((j['frozen'] or j['state']=='departed') and j['job_id'] in unassigned for j in s['jobs']):issue('FROZEN_UNASSIGNED')
    window_keys=[(x['voyage_id'],x['terminal_id']) for x in s['windows']]
    if len(window_keys)!=len(set(window_keys)):issue('DUPLICATE_WINDOW')
    for w in s['windows']:
        if dt(w['opens_at'])>dt(w['closes_at']):issue('WINDOW_ORDER')
    ch=s['change'];target=next((x for x in s['windows'] if x['window_id']==ch['new_window_id']),None)
    if target is None or (target['voyage_id'],target['terminal_id'])!=(ch['voyage_id'],ch['terminal_id']):issue('CHANGE_TARGET')
    return issues
check('기준 입력 관계 검증',not input_issues(snap))
check('준비 미확인 검출','INPUT_MISSING' in input_issues(read('예제 데이터/07_snapshot_입력누락.json')))
check('미확인 변경 검출','WINDOW_UNCONFIRMED' in input_issues(read('예제 데이터/08_snapshot_미확인변경.json')))
jobs={x['job_id']:x for x in snap['jobs']};vehicles={x['vehicle_id']:x for x in snap['vehicles']};windows={(x['voyage_id'],x['terminal_id']):x for x in snap['windows']};matrix={(x['from_location_id'],x['to_location_id']):x['minutes'] for x in snap['travel_times']};baseline={a['job_id']:a for a in snap['baseline_assignments']}
buffer=snap['policy']['buffer_minutes']
def timing_errors(a):
    j=jobs[a['job_id']];v=vehicles[a['vehicle_id']];w=windows[(j['voyage_id'],j['terminal_id'])];e=[]
    if minutes(a['pickup_departure_at'],matrix[(j['origin_id'],j['terminal_id'])])!=dt(a['gate_arrival_at']):e.append('ARRIVAL')
    if minutes(a['gate_arrival_at'],buffer+j['service_minutes']+matrix[(j['terminal_id'],j['return_location_id'])])!=dt(a['return_at']):e.append('RETURN')
    if dt(a['pickup_departure_at'])<dt(j['ready_at']):e.append('READY')
    if dt(a['gate_arrival_at'])<dt(w['opens_at']):e.append('EARLY')
    if minutes(a['gate_arrival_at'],buffer)>dt(w['closes_at']):e.append('CUTOFF')
    if dt(a['return_at'])>dt(v['shift_end_at']):e.append('SHIFT')
    if j['gross_weight_kg']>v['capacity_kg']:e.append('WEIGHT')
    if j['equipment_type'] not in v['equipment_types']:e.append('TYPE')
    return e
b0,b3=results['results']
check('B0 위반 작업 정확히 J1/J3',{a['job_id'] for a in b0['assignments'] if timing_errors(a)}=={'J1','J3'})
check('B3 배정 시간·호환·중량·근무 준수',all(not timing_errors(a) for a in b3['assignments']))
check('고정 작업 그대로 유지',next(a for a in b3['assignments'] if a['job_id']=='J0')==baseline['J0'])
check('입력 작업 보존',set(a['job_id'] for a in b3['assignments']).isdisjoint(b3['unassigned_job_ids']) and set(a['job_id'] for a in b3['assignments'])|set(b3['unassigned_job_ids'])==set(jobs))
for vid,v in vehicles.items():
    movable=sorted([a for a in b3['assignments'] if a['vehicle_id']==vid and not jobs[a['job_id']]['frozen']],key=lambda a:a['sequence'])
    available=max(dt(snap['as_of']),dt(v['available_at']));loc=v['start_location_id']
    for a in movable:
        j=jobs[a['job_id']]
        check('가용·공차접근 '+a['job_id'],dt(a['pickup_departure_at'])>=available+timedelta(minutes=matrix[(loc,j['origin_id'])]))
        available=dt(a['return_at']);loc=j['return_location_id']
changed={a['job_id'] for a in b3['assignments'] if a['vehicle_id']!=baseline[a['job_id']]['vehicle_id'] or abs((dt(a['pickup_departure_at'])-dt(baseline[a['job_id']]['pickup_departure_at'])).total_seconds())>snap['policy']['time_change_tolerance_minutes']*60}
check('변경 합집합 정확히 J1/J2',changed==set(b3['metrics']['changed_job_ids'])=={'J1','J2'})
check('J3 단독 최초도착으로도 불가',minutes(jobs['J3']['ready_at'],matrix[('O','HJNC')]+buffer)>dt(windows[('V1','HJNC')]['closes_at']))
check('fixture 실계산·최적성 오인 차단',all(r['result_origin']=='illustrative_fixture' and not r['objective_proven'] and not r['approval_eligible'] and r['solver_version'] is None for r in results['results']))
bad=copy.deepcopy(req);bad['time_limit_seconds']=-1
check('음수 시간 예산 거절',bool(list(validator('RunRequest').iter_errors(bad))))
bad=copy.deepcopy(snap);bad['jobs'][0]['surprise']='x'
check('정의 밖 필드 거절',bool(list(validator('Snapshot').iter_errors(bad))))
bad=copy.deepcopy(snap);bad['jobs'][0]['frozen']=False
check('출발 작업 잠금 모순 검출','DEPARTED_MUST_FREEZE' in input_issues(bad))
report={'scope':'명세/예제 검사. API서버·실제최적화·실제승인 실행시험 아님.','checks':checks,'passed':all(c['passed'] for c in checks)}
(ROOT/'검수/계약_예제_검증.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('passed',len(checks))
