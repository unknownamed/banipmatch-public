"""Summarize the preserved 156 runs; never invoke the engine or alter originals."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/experiments/engine-sensitivity-2026-11-08'
OUT = ROOT / 'docs/experiments/engine-report-2026-11-08'
sys.path.insert(0, str(OUT / '_runtime'))
GREEN = '#244f3e'


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load_and_verify(source=SOURCE, spec=(('scale',72),('mixed',48),('buffer',36)), version='0.2.1-b0-b3'):
    rows, manifest = [], {}
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    for folder_name, count in spec:
        bundle = folder_name.removeprefix('after-')
        folder = source / folder_name
        meta = json.loads((folder / 'metadata.json').read_text(encoding='utf-8'))
        raw = [json.loads(s) for s in (folder / 'results.jsonl').read_text(encoding='utf-8').splitlines()]
        flat = list(csv.DictReader((folder / 'runs.csv').open(encoding='utf-8-sig', newline='')))
        assert meta['completed'] and meta['completed_runs'] == count == len(raw) == len(flat)
        originals = {}
        for item in meta['inputs']:
            input_path = (ROOT / 'docs/experiments/engine-b0-b3/inputs' if bundle == 'scale' else SOURCE / 'inputs') / item['file']
            originals[item['file']] = json.loads(input_path.read_text(encoding='utf-8-sig'))
            assert digest(originals[item['file']]) == item['sha256']
            manifest[str(input_path.relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(input_path.read_bytes()).hexdigest()
        for r, c in zip(raw, flat):
            result, m = r['result'], r['result']['metrics']
            assert result['engine_version'] == version
            assert result['validation_status'] == 'not_run' and not result['approval_eligible']
            variant = json.loads(json.dumps(originals[r['input']]))
            variant['policy']['buffer_minutes'] = r['buffer']
            assert r['input_sha256'] == digest(variant)
            values = dict(unassigned=m['unassigned_count'], changed=len(m['changed_job_ids']),
                          travel_minutes=m['movable_travel_minutes'],
                          movable_violations=m['movable_violation_count'], fixed_risks=m['fixed_risk_count'],
                          elapsed_ms=m['elapsed_ms'], wall_ms=r['wall_ms'])
            for key, val in values.items():
                assert float(c[key]) == val, (bundle, key, val, c[key])
            for key in ('input', 'method', 'buffer', 'budget', 'seed', 'repetition'):
                assert str(r[key]) == c[key]
            assert c['objective_proven'] == str(result['objective_proven'])
            assert c['status'] == result['solution_status']
            assert c['stages'] == '/'.join(s['status'] for s in result['objective_stages'])
            row = dict(bundle=bundle, **{k: r[k] for k in ('input', 'method', 'buffer', 'budget', 'seed', 'repetition')},
                       **values, objective_proven=result['objective_proven'], status=result['solution_status'],
                       stages='/'.join(s['status'] for s in result['objective_stages']))
            if r['method'] != 'B0':
                assert values['movable_violations'] == 0
            rows.append(row)
        for filename in ('results.jsonl', 'runs.csv', 'metadata.json'):
            p = folder / filename
            manifest[str(p.relative_to(ROOT)).replace('\\', '/')] = hashlib.sha256(p.read_bytes()).hexdigest()
    pairs = defaultdict(set)
    for r in rows:
        pairs[tuple(r[k] for k in ('bundle','input','buffer','budget','seed','repetition'))].add(r['method'])
    assert len(rows) == sum(n for _,n in spec) and len(pairs)*4 == len(rows) and all(v == {'B0','B1','B2','B3'} for v in pairs.values())
    return rows, manifest


def summarize(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in ('bundle','input','buffer','budget','method'))].append(r)
    summary = []
    for key, group in groups.items():
        d = dict(zip(('bundle','input','buffer','budget','method'), key))
        d['runs'] = len(group)
        for metric in ('unassigned','changed','travel_minutes','fixed_risks','movable_violations','wall_ms'):
            values = [r[metric] for r in group]
            for label, value in [('min', min(values)), ('median', statistics.median(values)), ('max', max(values))]:
                d[f'{metric}_{label}'] = value
        d['proven_runs'] = sum(r['objective_proven'] for r in group)
        d['stage_patterns'] = ';'.join(sorted(set(r['stages'] for r in group)))
        summary.append(d)
    return summary


def verify_report_claims(summary):
    """Check every numeric result displayed in the report against all matching runs."""
    for r in summary:
        if r['method'] == 'B0':
            continue
        if r['bundle'] == 'scale':
            if r['input'].startswith('20_'):
                changed = {1:12,3:10,10:2}[r['budget']] if r['method']=='B3' else 12
                expected = (8,changed,720)
            else:
                expected = (26,24,1440)
        elif r['bundle'] == 'mixed':
            fixed = r['input'] == 'mixed_fixed_12.json'
            expected = (3,5 if r['method']=='B3' else (7 if fixed else 8),420 if fixed else 540)
            assert r['fixed_risks_min'] == r['fixed_risks_max'] == int(fixed)
        else:
            expected = {0:(2,6 if r['method']=='B3' else 9,600),
                        10:(3,5 if r['method']=='B3' else 8,540),
                        20:(3,5 if r['method']=='B3' else 6,540)}[r['buffer']]
        for metric,value in zip(('unassigned','changed','travel_minutes'),expected):
            assert r[f'{metric}_min'] == r[f'{metric}_max'] == value, (r,metric,value)
        if r['method'] in ('B2','B3'):
            proof = r['bundle'] != 'scale' or (r['input'].startswith('20_') and
                     (r['budget']==10 or (r['budget']==3 and r['method']=='B2')))
            assert r['proven_runs'] == (r['runs'] if proof else 0)
            if r['input'].startswith('50_'):
                assert r['stage_patterns'].startswith('UNKNOWN/')


def export_tables(rows, summary, manifest):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / '.gitignore').write_text('_runtime/\n__pycache__/\n', encoding='utf-8')
    for name, data in [('verified_runs.csv', rows), ('summary.csv', summary)]:
        with (OUT / name).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader(); writer.writerows(data)
    write_json(OUT / 'summary.json', summary)
    write_json(OUT / 'source_manifest.json', manifest)
    write_json(OUT / 'checks.json', dict(runs=156, paired_conditions=39, csv_json_metric_crosscheck='passed',
        input_hash_metadata_match='passed', source_files_sha256=manifest, adjusted_movable_violations=0,
        scope='Existing engine 0.2.1 artifacts only; not independent API validation; no new solver runs.'))


def lookup(summary, bundle, input_name, buffer, budget, method):
    return next(r for r in summary if (r['bundle'],r['input'],r['buffer'],r['budget'],r['method']) ==
                (bundle,input_name,buffer,budget,method))


def make_charts(summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont('C:/Windows/Fonts/malgun.ttf')
    plt.rcParams.update({'font.family':'Malgun Gothic','font.size':10,'axes.spines.top':False,
                         'axes.spines.right':False,'axes.unicode_minus':False,'svg.fonttype':'none'})
    def save(fig, name):
        fig.savefig(OUT / f'{name}.png', dpi=200, bbox_inches='tight', facecolor='white')
        fig.savefig(OUT / f'{name}.svg', bbox_inches='tight', facecolor='white')
        plt.close(fig)
    fig, axes = plt.subplots(1,2,figsize=(9,3.2), gridspec_kw={'width_ratios':[1.1,1]})
    for method,color,style in [('B1','#777777','--'),('B2','#222222',':'),('B3',GREEN,'-')]:
        data=[lookup(summary,'scale','20_jobs_4_vehicles.json',0,b,method) for b in (1,3,10)]
        axes[0].plot(range(3),[r['changed_median'] for r in data],marker='o',color=color,linestyle=style,label=method)
    axes[0].set(xticks=range(3),xticklabels=['1초','3초','10초'],ylabel='변경 작업 수 (건)',ylim=(0,14),title='20건 / 4차량 · 변경 부담')
    axes[0].legend(frameon=False,ncol=3,loc='lower left')
    for j,method in enumerate(('B2','B3')):
        data=[lookup(summary,'scale','20_jobs_4_vehicles.json',0,b,method) for b in (1,3,10)]
        axes[1].bar([i+(j-.5)*.32 for i in range(3)],[r['wall_ms_median']/1000 for r in data],width=.32,color=['#777777',GREEN][j],label=method)
    axes[1].set(xticks=range(3),xticklabels=['1초','3초','10초'],ylabel='전체 호출 시간 중앙값 (초)',title='같은 입력의 실측 호출 시간')
    axes[1].legend(frameon=False)
    fig.tight_layout(w_pad=3); save(fig,'01_scale')
    fig, ax=plt.subplots(figsize=(9,3.0))
    for j,method in enumerate(('B1','B2','B3')):
        data=[lookup(summary,'mixed',f,10,3,method) for f in ('mixed_12.json','mixed_fixed_12.json')]
        bars=ax.bar([i+(j-1)*.24 for i in range(2)],[r['changed_median'] for r in data],width=.24,color=['#aaa','#555',GREEN][j],label=method)
        ax.bar_label(bars,padding=3)
    ax.set(xticks=[0,1],xticklabels=['혼합12건 · 미처리3 / 이동540분','고정 포함12건 · 미처리3 / 이동420분'],ylabel='변경 작업 수 (건)',ylim=(0,10))
    ax.legend(frameon=False,ncol=3); fig.tight_layout(); save(fig,'02_mixed')
    fig, axes=plt.subplots(1,2,figsize=(9,3.0))
    for method,color,style in [('B1','#777','--'),('B3',GREEN,'-')]:
        data=[lookup(summary,'buffer','mixed_12.json',b,3,method) for b in (0,10,20)]
        axes[0].plot([0,10,20],[r['changed_median'] for r in data],color=color,marker='o',linestyle=style,label=method)
    axes[0].set(xlabel='여유시간 (분)',ylabel='변경 작업 수 (건)',xticks=[0,10,20],ylim=(0,11));axes[0].legend(frameon=False)
    counts=[lookup(summary,'buffer','mixed_12.json',b,3,'B3')['unassigned_median'] for b in (0,10,20)]
    bars=axes[1].bar(['0분','10분','20분'],counts,color=['#777',GREEN,GREEN],width=.5)
    axes[1].bar_label(bars,padding=3);axes[1].set(ylabel='미처리 작업 수 (건)',ylim=(0,4),xlabel='여유시간 · B1/B2/B3 공통')
    fig.tight_layout(w_pad=3); save(fig,'03_buffer')


def build_pdf(summary):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
    pdfmetrics.registerFont(TTFont('Malgun','C:/Windows/Fonts/malgun.ttf'))
    pdfmetrics.registerFont(TTFont('MalgunBold','C:/Windows/Fonts/malgunbd.ttf'))
    styles={k:ParagraphStyle(k,fontName=f,fontSize=s,leading=l,textColor=colors.HexColor(c),spaceAfter=a,wordWrap='CJK')
        for k,f,s,l,c,a in [('title','MalgunBold',24,33,GREEN,18),('h','MalgunBold',17,25,GREEN,12),
        ('body','Malgun',10,17,'#222222',10),('small','Malgun',8.2,13,'#555555',8),('cell','Malgun',9,14,'#222222',0)]}
    story=[]
    def p(text,kind='body'): story.append(Paragraph(text,styles[kind]))
    def table(data,widths):
        t=Table([[Paragraph(str(x),styles['cell']) for x in row] for row in data],colWidths=widths,hAlign='LEFT')
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7eee9')),('LINEBELOW',(0,0),(-1,0),.8,colors.HexColor(GREEN)),
            ('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#dddddd')),('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9)]))
        story.extend([t,Spacer(1,12)])
    def figure(name,height): story.extend([Image(str(OUT/f'{name}.png'),width=495,height=height,kind='proportional'),Spacer(1,8)])
    def page(): story.append(PageBreak())
    p('반입맞춤 엔진<br/>모의실험 요약','title')
    p('황대겸 · 최적화 엔진 파트 | 2026.11.08 | 엔진 0.2.1-b0-b3','small')
    p('동일한 처리 수준에서<br/>배차 변경 부담을 줄일 수 있는가?','h')
    p('기존 156회 실행 결과를 보고서 삽입용 표와 그림으로 정리했다. 20건·10초 사례에서 B3는 B1 대비 변경 작업을 12건에서 2건으로 줄였고, 미처리8건과 조정 작업 이동720분을 유지했다. 혼합12건에서도 변경8건을 5건으로 줄였다.')
    p('다만 50건은 10초에서도 솔버 첫 단계가 UNKNOWN이며 초기 유효안을 유지했다. 이 결과는 대량 입력의 최적화 성능 해결이나 현장 효과의 증거가 아니다.')
    table([['실험 묶음','조건 구성','실행 수'],['규모','20건/4차량, 50건/8차량 × 1/3/10초 × 3회','72'],['혼합','12건 2종 × 3/10초 × 시드0/17/41','48'],['여유시간','혼합12건 × 0/10/20분 × 3회','36'],['합계','39개 짝지은 조건 × B0~B3','156']], [78,350,67])
    p('비교 방법과 공정성','h')
    p('B0는 원안의 위험 진단, B1은 마감순 삽입이다. B2는 미처리 → 이동, B3는 미처리 → 변경 → 이동 순으로 최적화한다. 같은 조건의 방법에는 동일 입력·원안·시드·총 시간 예산을 제공했다. Python3.12, OR-Tools9.15.6755, 로컬 단일 worker 환경이며 순차 실행했다.')
    p('모든 입력은 인위적으로 구성한 모의 자료다. 동일 시드 반복은 시간 변동 확인용이며 모집단 표본이 아니다. 신뢰구간·상용 TMS 대비 우위·실제 비용 절감률을 산출하지 않았다.','small')
    page()
    p('01 · 규모와 계산 예산','title')
    p('20건에서는 예산 증가에 따라 변경 부담 감소','h')
    figure('01_scale',190)
    p('그림1. 20건/4차량. 각 점·막대는 동일 시드3회 중앙값이다. 전 조건에서 B1/B2/B3의 미처리8건, 이동720분을 유지했다. B2와 B1의 변경 수가 겹친다.','small')
    table([['입력·예산','B2 변경','B3 변경','B2/B3 전체 최적성'],['20건 · 1초','12','12','0/3회, 0/3회'],['20건 · 3초','12','10','3/3회, 0/3회'],['20건 · 10초','12','2','3/3회, 3/3회'],['50건 · 1/3/10초','24','24','모두 0/3회']], [122,80,80,213])
    a=lookup(summary,'scale','20_jobs_4_vehicles.json',0,10,'B3'); b=lookup(summary,'scale','20_jobs_4_vehicles.json',0,10,'B2')
    p(f"20건·10초의 B3 호출 시간 중앙값은 {a['wall_ms_median']/1000:.2f}초(최소 {a['wall_ms_min']/1000:.2f}, 최대 {a['wall_ms_max']/1000:.2f})이며 B2는 {b['wall_ms_median']/1000:.2f}초다. 3초 B3의 변경10건은 유효한 결과지만 그 값이 최선이라고 증명하지 못했다.")
    p('50건은 초기안 유지 사례','h')
    p('50건/8차량은 모든 예산에서 미처리26건·변경24건·이동1,440분으로 같았다. B2/B3는 B1의 초기 유효안을 반환했고 솔버 첫 목적 단계는 UNKNOWN이었다. 유효 결과의 존재와 솔버의 최적성 증명을 분리해 표시해야 한다.')
    p('단순 시간 구조에서는 차량당 최대3건이므로 미처리8/26건은 수작업 하한과 일치한다. 이 설명은 솔버의 증명 상태를 대신하지 않는다. 시간 예산은 입력·모형·목적 단계의 총 예산이며 강제 프로세스 종료 보장은 아니다.','small')
    page()
    p('02 · 업무 조건이 섞인 입력','title')
    p('처리 건수와 이동량을 지킨 변경 감소','h')
    p('혼합12건은 DRY20/DRY40, 허용중량, 3개 항차·시간창, 준비 지연·처리시간을 포함한다. 고정 포함 입력에는 출발1건과 미래 고정 예약1건을 추가했다. 여유시간은 10분이다.')
    figure('02_mixed',190)
    p('그림2. 3초의 시드0/17/41 결과가 동일하며, 10초에서도 같은 목적값을 얻었다. B2/B3는 두 예산·세 시드의 모든 실행에서 전체 최적성을 증명했다. 동률 해의 구체적 배정이 모두 같다는 뜻은 아니다.','small')
    table([['입력','방법','미처리 / 변경 / 이동분','보존·위험'],['혼합12건','B1 / B2','3 / 8 / 540','조정 위반0'],['혼합12건','B3','3 / 5 / 540','조정 위반0'],['고정 포함12건','B1 / B2','3 / 7 / 420','고정2건 유지'],['고정 포함12건','B3','3 / 5 / 420','고정2건·잔여 위험1건 유지']], [110,78,151,156])
    p('고정 기록과 남아 있는 위험을 함께 보존','h')
    p('고정 출발 기록의 이른 반입 위험1건을 의도적으로 남겼다. 위험한 고정 작업을 삭제하거나 미처리로 돌려 지표를 좋게 만들지 않았다. 이 사례는 고정 작업을 지키면서 조정 가능한 작업의 변경 부담을 비교하기 위한 것이다.')
    p('이동 합계는 조정 작업만 포함한다. 고정 포함 입력의420분을 고정 없는 입력의540분보다 효율적이라고 해석하지 않는다. 같은 입력·같은 처리 수준 안에서 비교한다.','small')
    page()
    p('03 · 여유시간과 해석의 한계','title')
    p('여유시간 증가는 처리 가능량과 함께 판단','h')
    figure('03_buffer',180)
    p('그림3. 고정 없는 혼합12건, 3초, 시드0, 각3회. B2의 변경 수는 B1과 같아 생략했다. B2/B3는 전 실행에서 전체 최적성을 증명했다.','small')
    table([['여유시간','B1/B2 미처리·변경·이동분','B3 미처리·변경·이동분'],['0분','2 / 9 / 600','2 / 6 / 600'],['10분','3 / 8 / 540','3 / 5 / 540'],['20분','3 / 6 / 540','3 / 5 / 540']], [80,207,208])
    p('여유0→10분에서 미처리는2→3건으로 늘었다. 이동600→540분은 처리 작업 감소를 포함하므로 효율 개선률로 쓰지 않는다. 원안 기록 시각은 변형마다 그대로 보존했다. B0의 전체 위반 수는 준비·복귀 등 진단을 포함할 수 있어 마감 위반 수로 부르지 않는다.')
    p('확인 범위와 다음 검증','h')
    p('원본156행의 주요 지표를 CSV와 JSONL 간 대조하고 입력 해시·완료 수를 확인했다. 기존 결과 검수는 작업 분할과 고정 보존을 확인했으며 B1/B2/B3의 조정 위반은 모두0이다. API 담당 독립 일정 검사 완료를 뜻하지 않는다. 모든 결과는 validation_status=not_run, approval_eligible=false다.')
    p('12~20건은 내부 시연 후보이며 50건은 초기 유효안·시간 제한 상태 표시 사례다. 실제 자료의 분포, 외부 반입시간 근거, API 연결·독립 일정 검사·현장 평가, 배포 환경의 강제 시간 제한은 후속 검증 대상이다.')
    p('출처: docs/experiments/engine-sensitivity-2026-11-08/의 scale·mixed·buffer 각 results.jsonl, runs.csv, metadata.json 및 checks.json. 재현용 집계와 원본 SHA-256은 이 보고서와 같은 폴더의 summary.csv 및 source_manifest.json에 보존했다. 별도 후속 성능 실험은 이156회에 포함하지 않았다.','small')
    def footer(canvas,doc):
        canvas.setStrokeColor(colors.HexColor('#bbbbbb'));canvas.line(50,43,545,43)
        canvas.setFont('Malgun',8);canvas.setFillColor(colors.HexColor('#666666'))
        canvas.drawString(50,29,'반입맞춤 | 엔진 0.2.1 | 인위적 모의자료 156회')
        canvas.drawRightString(545,29,f'{doc.page} / 4')
    SimpleDocTemplate(str(OUT/'engine-experiment-summary.pdf'),pagesize=A4,rightMargin=50,leftMargin=50,
        topMargin=45,bottomMargin=56,title='반입맞춤 엔진 모의실험 요약',author='반입맞춤').build(story,onFirstPage=footer,onLaterPages=footer)


def build_followup():
    """Separate 72-run comparison; leave all original report outputs untouched."""
    profile = ROOT / 'docs/experiments/engine-profile-2026-11-08'
    before, old_manifest = load_and_verify()
    after, manifest = load_and_verify(profile,(('after-scale',48),('after-mixed',24)),'0.2.2-b0-b3')
    diagnostics = {}
    for name in ('before-default','probing-zero','complete-hint-default','complete-hint-probing-zero'):
        path=profile/name/'profile.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        assert data['completed']
        diagnostics[name]=hashlib.sha256(path.read_bytes()).hexdigest()
        if name=='before-default':
            phases={p['name']:p['seconds'] for p in data['phases']}
            assert round(phases['warm_start'],3)==0.063 and round(phases['model_build'],3)==0.468
            assert round(data['stages'][0]['seconds'],3)==8.012
            assert data['stages'][0]['branches']==0 and data['stages'][0]['stopped_after_presolve']
    old, new = summarize(before), summarize(after)
    # All after-scale runs use the same seed/repetitions as their old counterpart.
    old_by_key = {tuple(r[k] for k in ('bundle','input','buffer','budget','seed','repetition','method')): r for r in before}
    for r in after:
        k=tuple(r[f] for f in ('bundle','input','buffer','budget','seed','repetition','method'))
        assert k in old_by_key
        if r['method'] in ('B2','B3'):
            assert r['movable_violations'] == 0
    for r in new:
        if r['bundle']=='mixed':
            prev=lookup(old,'mixed',r['input'],r['buffer'],r['budget'],r['method'])
            for metric in ('unassigned','changed','travel_minutes','fixed_risks'):
                assert r[f'{metric}_min']==r[f'{metric}_max']==prev[f'{metric}_median']
        if r['bundle']=='scale' and r['method'] in ('B2','B3'):
            is20=r['input'].startswith('20_')
            expected=(8,2 if r['method']=='B3' else 12,720) if is20 else (26,23 if r['method']=='B3' and r['budget']==10 else 24,1440)
            for metric,value in zip(('unassigned','changed','travel_minutes'),expected):
                assert r[f'{metric}_min']==r[f'{metric}_max']==value
            assert r['proven_runs']==(3 if is20 or (r['budget']==10 and r['method']=='B2') else 0)
            if not is20:
                expected_stage='OPTIMAL/OPTIMAL' if r['method']=='B2' and r['budget']==10 else ('OPTIMAL/FEASIBLE/NOT_RUN' if r['budget']==10 else ('FEASIBLE/NOT_RUN' if r['method']=='B2' else 'FEASIBLE/NOT_RUN/NOT_RUN'))
                assert r['stage_patterns']==expected_stage
    for name,data in [('followup_verified_runs.csv',after),('followup_summary.csv',new)]:
        with (OUT/name).open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    write_json(OUT/'followup_summary.json',new)
    write_json(OUT/'followup_source_manifest.json',dict(before=old_manifest,after=manifest,diagnostics=diagnostics))
    write_json(OUT/'followup_checks.json',dict(runs=72,paired_conditions=18,diagnostic_runs_excluded=4,
        csv_json_metric_status_checks='passed',paired_old_condition_checks='passed',displayed_claims='passed',
        engine_version='0.2.2-b0-b3',validation_status='not_run',approval_eligible=False,
        source_hashes=manifest,diagnostic_hashes=diagnostics,scope='Artifact comparison only; no solver run or independent API validation.'))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    font_manager.fontManager.addfont('C:/Windows/Fonts/malgun.ttf')
    plt.rcParams.update({'font.family':'Malgun Gothic','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none'})
    fig,ax=plt.subplots(figsize=(8.5,2.4))
    for j,(label,data,color) in enumerate([('0.2.1',old,'#888888'),('0.2.2',new,GREEN)]):
        values=[lookup(data,'scale','20_jobs_4_vehicles.json',0,b,'B3')['wall_ms_median']/1000 for b in (3,10)]
        bars=ax.bar([i+(j-.5)*.3 for i in range(2)],values,width=.3,color=color,label=label)
        ax.bar_label(bars,fmt='%.2f',padding=3)
    ax.set(xticks=[0,1],xticklabels=['3초 예산','10초 예산'],ylim=(0,6),ylabel='전체 호출 시간 중앙값 (초)')
    ax.legend(frameon=False);fig.tight_layout()
    for ext in ('png','svg'):fig.savefig(OUT/f'04_followup_20jobs.{ext}',dpi=200,bbox_inches='tight')
    plt.close(fig)
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,Image,PageBreak
    pdfmetrics.registerFont(TTFont('Malgun','C:/Windows/Fonts/malgun.ttf'));pdfmetrics.registerFont(TTFont('MalgunBold','C:/Windows/Fonts/malgunbd.ttf'))
    styles={k:ParagraphStyle(k,fontName=f,fontSize=s,leading=l,textColor=colors.HexColor(c),spaceAfter=a,wordWrap='CJK') for k,f,s,l,c,a in [
        ('title','MalgunBold',23,31,GREEN,16),('h','MalgunBold',16,23,GREEN,10),('body','Malgun',10,17,'#222222',10),('small','Malgun',8.1,12,'#555555',8),('cell','Malgun',8.5,13,'#222222',0)]}
    story=[]
    def p(text,kind='body'):story.append(Paragraph(text,styles[kind]))
    def table(data,widths):
        t=Table([[Paragraph(str(v),styles['cell']) for v in row] for row in data],colWidths=widths)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e7eee9')),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor(GREEN)),
            ('LINEBELOW',(0,1),(-1,-1),.3,colors.HexColor('#dddddd')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]))
        story.extend([t,Spacer(1,12)])
    p('엔진 성능 후속 보완','title')
    p('0.2.1 → 0.2.2 | 기존156회와 분리한 후속72회 | 2026.11.08','small')
    p('초기안 힌트와 솔버 탐색 설정 보완','h')
    p('초기 유효안의 모든 보조변수까지 힌트를 계산하고 cp_model_probing_level=0을 적용했다. 전처리는 유지하며 제약과 목적 우선순위는 바꾸지 않았다. 같은 로컬 단일 worker 환경에서 B0~B3를 다시 비교했다.')
    table([['후속 묶음','조건','실행 수'],['규모','20/50건 × 3/10초 × 시드0 × 각3회 × B0~B3','48'],['혼합','12건2종 × 3초 × 시드0/17/41 × B0~B3','24']], [66,375,54])
    p('20건 · 3초에서도 변경2건의 최적성 증명','h')
    story.extend([Image(str(OUT/'04_followup_20jobs.png'),width=495,height=148,kind='proportional'),Spacer(1,8)])
    p('그림4. 20건/4차량 B3, 시드0·각3회. 진단 실행의 로그 시간이 아닌 정식 벤치마크 전체 호출 시간이다.','small')
    table([['20건 B3','0.2.1','0.2.2'],['3초 · 변경 수 / 전체 최적성','10건 / 미증명','2건 / 3회 모두 증명'],['10초 · 변경 수 / 전체 최적성','2건 / 3회 모두 증명','2건 / 3회 모두 증명']], [156,169,170])
    t_old=lookup(old,'scale','20_jobs_4_vehicles.json',0,10,'B3')['wall_ms_median']/1000
    t_new=lookup(new,'scale','20_jobs_4_vehicles.json',0,10,'B3')['wall_ms_median']/1000
    p(f'20건 B3의 10초 예산 호출 시간 중앙값은 {t_old:.2f}초에서 {t_new:.2f}초로 줄었다. 미처리8건·이동720분은 유지했다. 같은 장비의 소수 반복 결과이며 일반 규모의 속도 향상률로 확대하지 않는다.')
    p('모든 실행은 인위적 모의자료다. 기존156회 요약은 보존하며 후속72회를 기존 표본 수에 합치지 않는다. 혼합 후속은3초만 재실행했으므로10초까지 재검증했다고 표현하지 않는다.','small')
    story.append(PageBreak())
    p('50건의 진전과 남은 한계','title')
    p('첫 목적 단계의 탐색은 진전, B3 전체 최적성은 미증명','h')
    table([['조건·방법','0.2.1 단계 상태','0.2.2 단계 상태','0.2.2 미처리/변경/이동분'],
        ['3초 · B2','UNKNOWN / NOT_RUN','FEASIBLE / NOT_RUN','26 / 24 / 1,440'],
        ['3초 · B3','UNKNOWN / NOT_RUN / NOT_RUN','FEASIBLE / NOT_RUN / NOT_RUN','26 / 24 / 1,440'],
        ['10초 · B2','UNKNOWN / NOT_RUN','OPTIMAL / OPTIMAL','26 / 24 / 1,440'],
        ['10초 · B3','UNKNOWN / NOT_RUN / NOT_RUN','OPTIMAL / FEASIBLE / NOT_RUN','26 / 23 / 1,440']], [65,132,151,147])
    p('표의 상태·목적값은 각3회 모두 같았다. B2의 단계 순서는 미처리→이동, B3는 미처리→변경→이동이다. FEASIBLE은 유효한 해를 찾았으나 최선임을 증명하지 못한 상태다.','small')
    p('50건·10초 B2는3회 모두 전체 최적성을 증명했다. B3는 미처리 목적을 증명하고 변경24→23건의 해를 찾았지만 변경 단계는 FEASIBLE이며 이동 단계는 실행하지 못했다. 전체 최적해로 표시하지 않는다. 3초에서는 B2/B3 모두 첫 목적 단계가 FEASIBLE에 머물렀다.')
    p('혼합 입력의 보존 조건도 다시 확인','h')
    p('혼합12건의 B3는 미처리3건·변경5건·이동540분, 고정 포함12건은3건·5건·420분으로 기존 목적값을 유지했다. 후속3초·시드0/17/41에서 B2/B3 모두 전체 최적성을 증명했다. 고정 포함 입력의 잔여 위험1건도 유지했다.')
    p('진단4회는 병목 설명용이며 속도 비교 표본에서 제외','h')
    p('초기 진단은 초기안0.063초·모형 구성0.468초·솔버8.012초였고 분기0, 전처리 후 중단을 기록했다. 초기안·모형 구성보다 솔버 단계에 시간이 집중된 관측이다. 이후 설정 조합을 비교한 진단 로그와 정식72회 벤치마크의 시간을 섞지 않는다.')
    p('검증 경계','h')
    p('최종 Python 단위검사171개/하위156개, 계약29개·DB32개 통과 결과와 별개로, 이번 자료는72행 CSV/JSONL·입력 해시·표시 지표를 대조했다. API 독립 일정 검사·승인 연결은 미구현이다. 모든 결과는 not_run / approval_eligible=false이며 현장 효과·상용 서비스 우위를 입증하지 않는다.')
    p('출처: engine-profile-2026-11-08/after-scale·after-mixed의 results.jsonl / runs.csv / metadata.json. 진단 경로: before-default, probing-zero, complete-hint-default, complete-hint-probing-zero의 profile.json. 이전 비교: engine-sensitivity-2026-11-08/scale. 원본 해시는 followup_source_manifest.json에 보존.','small')
    def footer(canvas,doc):
        canvas.setStrokeColor(colors.HexColor('#bbbbbb'));canvas.line(50,43,545,43);canvas.setFont('Malgun',8);canvas.setFillColor(colors.HexColor('#666666'))
        canvas.drawString(50,29,'반입맞춤 | 엔진 0.2.2 | 후속 모의실험72회');canvas.drawRightString(545,29,f'{doc.page} / 2')
    SimpleDocTemplate(str(OUT/'engine-performance-followup.pdf'),pagesize=A4,leftMargin=50,rightMargin=50,topMargin=43,bottomMargin=55,
        title='반입맞춤 엔진 성능 후속 보완',author='반입맞춤').build(story,onFirstPage=footer,onLaterPages=footer)
    print(json.dumps({'followup_verified_runs':72,'pdf':'engine-performance-followup.pdf'}))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pdf',action='store_true');parser.add_argument('--followup',action='store_true');args=parser.parse_args()
    if args.followup:
        build_followup();return
    rows,manifest=load_and_verify();summary=summarize(rows);verify_report_claims(summary)
    export_tables(rows,summary,manifest);make_charts(summary)
    if args.pdf: build_pdf(summary)
    print(json.dumps({'verified_runs':len(rows),'summary_groups':len(summary),'pdf_created':args.pdf}))


if __name__=='__main__': main()
