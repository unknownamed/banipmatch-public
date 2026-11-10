"""Render the evidence-based Korean review report; never rerun experiments."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
GREEN = colors.HexColor("#285448")
INK = colors.HexColor("#252923")
MUTED = colors.HexColor("#60655f")
PALE = colors.HexColor("#f0f3ef")
LINE = colors.HexColor("#ced5cc")
W = 174 * mm


class ComparisonChart(Flowable):
    """Vector bars: representative seed 0; no field-effect extrapolation."""
    def __init__(self, cases):
        Flowable.__init__(self)
        self.cases = cases
        self.width, self.height = W, 244

    def draw(self):
        c = self.canv
        c.setFillColor(INK)
        c.setFont("KRB", 10)
        c.drawString(122, 231, "변경 작업 수")
        c.drawString(301, 231, "이동시간(분)")
        c.setFont("KR", 8)
        for x, label, color in [(122, "B2 이동 부담 우선", MUTED), (296, "B3 변경 부담 우선", GREEN)]:
            c.setFillColor(color); c.rect(x, 213, 8, 6, fill=1, stroke=0)
            c.setFillColor(INK); c.drawString(x + 12, 212, label)
        for i, case in enumerate(self.cases):
            y = 186 - i * 32
            label = case["label"].split(" · 생성")[0]
            c.setFont("KR", 8); c.setFillColor(INK); c.drawString(0, y - 1, label)
            for j, (x, field, maximum) in enumerate([(122, "changed", 45), (301, "travel", 2000)]):
                for k, method in enumerate(["B2", "B3"]):
                    metric = case["methods"][method]["result"]["metrics"]
                    value = len(metric["changed_job_ids"]) if field == "changed" else metric["movable_travel_minutes"]
                    yy = y + 3 - k * 11
                    c.setFillColor(MUTED if k == 0 else GREEN)
                    if value:
                        c.rect(x, yy, value / maximum * 135, 7, fill=1, stroke=0)
                    c.setFillColor(INK); c.setFont("KR", 7.5)
                    c.drawString(x + value / maximum * 135 + 4, yy - .3, f"{value:g}")


def render(output: Path, font: Path, bold: Path) -> dict:
    if output.exists() or output.with_suffix(".build.json").exists():
        raise FileExistsError(output)
    pdfmetrics.registerFont(TTFont("KR", str(font)))
    pdfmetrics.registerFont(TTFont("KRB", str(bold)))
    pdfmetrics.registerFontFamily("KR", normal="KR", bold="KRB", italic="KR", boldItalic="KRB")
    styles = {
        "body": ParagraphStyle("body", fontName="KR", fontSize=10.2, leading=17, textColor=INK, wordWrap="CJK", spaceAfter=9),
        "small": ParagraphStyle("small", fontName="KR", fontSize=8.2, leading=13, textColor=MUTED, wordWrap="CJK", spaceAfter=6),
        "h1": ParagraphStyle("h1", fontName="KRB", fontSize=20, leading=28, textColor=GREEN, spaceAfter=18),
        "h2": ParagraphStyle("h2", fontName="KRB", fontSize=12.5, leading=19, textColor=INK, spaceBefore=9, spaceAfter=8),
        "title": ParagraphStyle("title", fontName="KRB", fontSize=32, leading=43, textColor=INK, spaceAfter=14),
        "cell": ParagraphStyle("cell", fontName="KR", fontSize=9, leading=14, textColor=INK, wordWrap="CJK"),
        "cellhead": ParagraphStyle("cellhead", fontName="KRB", fontSize=9, leading=14, textColor=INK, wordWrap="CJK"),
    }
    def P(text, style="body"):
        return Paragraph(text, styles[style])
    def table(rows, widths, header=True):
        data = [[P(escape(str(cell)).replace("\n", "<br/>"), "cellhead" if header and i == 0 else "cell") for cell in row] for i, row in enumerate(rows)]
        item = Table(data, colWidths=[W*x for x in widths], repeatRows=1 if header else 0, hAlign="LEFT")
        rules = [("VALIGN", (0,0), (-1,-1), "TOP"), ("LEFTPADDING", (0,0), (-1,-1), 8),
                 ("RIGHTPADDING", (0,0), (-1,-1), 8), ("TOPPADDING", (0,0), (-1,-1), 8),
                 ("BOTTOMPADDING", (0,0), (-1,-1), 8), ("LINEBELOW", (0,0), (-1,-1), .45, LINE)]
        if header: rules.extend([("BACKGROUND", (0,0),(-1,0),PALE), ("LINEABOVE",(0,0),(-1,0),1,GREEN)])
        item.setStyle(TableStyle(rules)); return item
    source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    bundle_path = ROOT / "docs/experiments/engine-evaluation-2026-11-08/showcase.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    summary = bundle["context"]["summary"]
    assert summary["runs"] == 80 and summary["identical_workload_comparable"] == 14
    wanted = ["eval_cutoff_8_101", "eval_opening_8_101", "eval_readiness_8_101", "eval_fixed_8_101", "eval_cutoff_20_303", "eval_cutoff_50_404"]
    cases = [next(c for c in bundle["cases"] if c["case_id"] == name) for name in wanted]
    story = []
    def section(number, title):
        if story: story.append(PageBreak())
        story.extend([P(f"{number:02d}  {title}", "h1")])
    def para(text): story.append(P(text))
    def sub(title, text): story.extend([P(title,"h2"),P(text)])
    def source(text): story.append(P(text,"small"))

    story.extend([Spacer(1, 18*mm), P("2026 국립창원대학교 스마트물류 경진대회", "small"),
                  P("반입맞춤", "title"), P("부산항 신항(진해) 수출 컨테이너<br/>반입시간 변경 대응 배차 점검·조정", "h1"), Spacer(1,7*mm)])
    para("반입 시작이나 마감이 바뀌었을 때, 이미 출발한 작업을 지키면서 남은 배차를 어떻게 조정할지 돕는 서비스다. 운송사 배차 담당자가 변경의 영향과 대안의 부담을 비교하고, 해결되지 않은 조건을 확인해 다음 대응으로 이어가도록 설계했다.")
    story.append(table([["검토 대상", "HJNC 일반 수출 Dry 컨테이너"], ["주사용자", "운송사 배차 담당자"],
                        ["현재 검증", "모의 입력의 B0~B3 계산·독립 일정 검사·비교·로컬 내부 승인, 변경 명세 로직"],
                        ["아직 남은 검증", "실제 자료의 제품 화면 연결, 조건 편집·전달/응답 통합, 공개 배포와 휴대폰 검수"]],[.22,.78],False))
    story.append(Spacer(1,10*mm))
    para("<b>핵심 결과</b>  동결 모의 평가 80회 중 B2/B3 비교는 20쌍이다. 같은 작업을 처리한 작은 사례 12쌍에서는 변경 작업이 4~7건 줄면서 이동이 12~82분 늘었다. 변경 감소와 이동 증가를 함께 보여주는 것이 본 시제품의 평가 초점이다.")
    source("모의 결과이며 현장 운송비·업무시간 절감 또는 상용 제품 대비 우위를 입증한 수치는 아니다. [4][5]")
    story.append(Spacer(1,8*mm))
    para("국립창원대학교 컴퓨터공학과 · 팀 반입맞춤<br/>황대겸 · 안선효 · 심민준 · 최길웅")
    source(f"검토본 · 2026.11.10 · 소스 {source_commit[:12]}<br/>최종 제출 승인본이 아니다. 구현 중인 범위와 검증된 결과를 구분했다.")

    section(2,"문제와 기존 서비스")
    sub("반입 허용시간이 바뀌면 기존 배차도 다시 봐야 한다", "예정대로 출발해도 반입 시작 전 또는 마감 후에 도착할 수 있다. 담당자는 화물 준비, 이동, 차량별 작업과 복귀 조건을 함께 확인해야 한다. 이미 출발했거나 고정된 작업은 자동 조정에서 보존한다.")
    story.append(table([["공개 근거", "확인한 내용", "이 자료로 알 수 없는 것"],
        ["HJNC 지연 반입 공지 [1]", "마감 준수와 재조작·운영 차질의 업무상 이유", "현재 변경 빈도·실제 부과 사례·운송사 손실"],
        ["반입 제한 일자 변경 [2]", "운영 상황에 따라 시작 측 기준이 바뀐 과거 사례", "2026년 기본 일수·개별 항차의 변경 전후"],
        ["선반입 서비스 [3]", "시작시간 이전 반입의 별도 예외 절차", "우리 시스템의 예외 허가·예약 변경 권한"]],[.25,.36,.39]))
    sub("비교의 기준", "배차·지도·추적·알림 자체를 새로운 기능이라고 주장하지 않는다. 공개 소개에서 확인된 기능과 우리 프로젝트의 검증 초점을 구분한다. 로그인 후 기능, 고객별 운영과 알고리즘 성능은 확인하지 않았다.")
    story.append(table([["서비스", "공개 소개의 중심", "이번 프로젝트와의 관계"],
        ["TIGER FACE / CONTAINUS TMS", "운송·배차·협력사 업무 관리", "배차 업무와 겹친다. 변경 이후 제약 보호·절충 설명을 집중 검증"],
        ["PortWise", "선박·선석 운영 지원", "터미널/선석 운영과 운송사 내부 배차의 결정 권한을 구분"],
        ["PortQM", "검역·서류 업무", "우리의 배차 조정과 다른 업무 범위"]],[.26,.32,.42]))
    source("출처 [6]의 원출처 링크와 확인 범위. 기존 제품에 공개되지 않은 기능을 미지원으로 단정하지 않는다.")

    section(3,"담당자가 대응하는 흐름")
    para("완성 목표는 조정안 제시 후 담당자가 다시 해야 하는 조건 확인·전달·응답까지 이어지는 것이다. 아래 흐름은 최신 확정 범위이며, 현재 구현 여부는 8쪽에서 구분한다.")
    story.append(table([["단계", "담당자가 하는 일", "서비스의 직접 지원"],
        ["1. 변경 확인", "적용 항차와 반입 시작/마감·출처 확인", "너무 이른/늦은 작업, 누락 자료와 고정 위험 표시"],
        ["2. 대안 비교", "원안과 조정안의 부담 비교", "같은 입력으로 미처리·변경·이동·위험을 함께 제시"],
        ["3. 조건 보완", "화주/상차지 등의 확인된 조건 입력", "준비시각·차량 가용/근무 조건을 새 입력으로 보존하고 재계산"],
        ["4. 확정", "실행 가능성과 남은 위험을 검토", "최신 입력·계획 검사, 이전/신규 차량의 정확한 변경 명세"],
        ["5. 전달·응답", "대상자에게 알리고 수행 가능 여부 확인", "동의한 수신자 웹 푸시, 명시 확인/수행 곤란과 담당자 상태 연결"]],[.17,.36,.47]))
    sub("자동으로 바꾸면 안 되는 것", "기존 출발·고정 작업, 확인되지 않은 마감, 준비시각과 누락 이동시간을 임의로 바꾸지 않는다. 차량 추가도 장비·용량·위치·가용 시간·필요 경로가 갖춰져야 한다. 곤란 응답이 왔다고 새 운송 지시를 자동 확정하지 않는다.")
    sub("연락 상태의 의미", "푸시 중계망 접수, 화면 열람, 명시적인 확인, 수행 가능 응답, 실제 운송 완료는 서로 다른 사건이다. 전달 실패·미연결·결과 불명을 성공으로 표시하지 않는다. 처음 검수할 대상은 기사 역할에 동의한 팀원이며 실제 운행 실증이 아니다.")
    source("설계 근거 [7][8]. 전화·채팅 서비스, 실제 차량 모집/계약, 터미널 예약·마감 변경 대행은 제외한다.")

    section(4,"자료 확보와 사용 경계")
    para("실제 제공기관의 응답 형식과 품질을 확인하되, 참고 표시와 계산 채택을 구분한다. 실제 배차와 GPS가 없다는 이유로 값을 만들어 실자료로 표시하지 않는다.")
    story.append(table([["자료", "확보·검토한 범위", "용도와 남은 조건"],
        ["HJNC", "항차·반입 시작/마감·접안 예정 표본. 부분 응답과 수신시각 대조", "반입시간 참고. 시간대·전체 범위·변경쌍·반복/공개 조건 확인 필요"],
        ["기상청", "CP949 해양관측·특보. 단위·KST·결측/예비 시간코드 검증", "인근 기상 참고. HJNC 실측/지연 원인·지연분으로 확정하지 않음"],
        ["도로공사", "소량 통행시간 응답의 집계 누락·품질 불일치", "계산 채택 보류. 원인·단위/집계·필요 구간 확인 필요"],
        ["AIS", "제한 시험의 부산 무수신, 다른 지역 대조·합성 재생은 별도 PR", "선박 참고 후보. 부산 데이터 부재/영구 미지원으로 일반화하지 않음"],
        ["ORS", "개인 신청·방향별 경로 수치 검증을 담당 작업으로 배정", "표본·이용조건 확인 전 미채택. 실시간 교통/화물차 통행 인증 아님"],
        ["배차·GPS·입출차", "기업 협조 표본과 접근 권한 미확보", "명시적 모의 입력. 차량 공차·공컨테이너·적컨테이너를 혼동하지 않음"]],[.17,.40,.43]))
    sub("누락을 다루는 원칙", "실패하면 마지막 성공 자료의 시각·실패 상태를 보여주고, 모의 시연은 별도 선택으로 둔다. 단일 관측은 변경 이력이 아니다. 선박 ETA를 반입마감으로 바꾸지 않고, 시간대·단위·권한·필수 필드를 확인한 경우에만 혼합 계산을 별도 검토한다.")
    source("자료 검증 본문·제공기관 출처 [9]. 공급자 형식 합성 예제 21종은 파서/실패 검수 자료이며 실제 응답 21건이나 현장 운송 사례가 아니다.")

    section(5,"조정 방법과 보호 조건")
    story.append(table([["방법", "역할", "해석"],
        ["B0", "원안 유지·위험 진단", "변경하지 않았을 때의 위험을 보여주는 기준"],
        ["B1", "마감순 삽입", "설명 가능한 조정 기준선"],
        ["B2", "제약 최적화·이동 부담 우선", "처리 수준을 먼저 맞춘 뒤 이동 부담을 비교"],
        ["B3", "제약 최적화·변경 부담 우선", "처리 수준을 먼저 맞춘 뒤 원안 변경을 줄이는 대안"]],[.13,.35,.52]))
    sub("실행 가능성을 지키는 제약", "작업의 화물 준비시각, 반입 시작/마감, 방향별 이동시간, 서비스·여유시간, 차량 장비·용량, 가용·근무·복귀 조건을 함께 확인한다. 출발·고정 작업의 차량·순서·시각은 유지하고 위험을 별도로 남긴다. 누락 이동시간을 0분으로, 미확인 복귀를 즉시 가용으로 처리하지 않는다.")
    sub("무엇을 변경 한 건으로 세는가", "차량 변경, 허용폭을 넘은 출발시각 변경, 순서 역전, 신규 배정의 합집합을 작업 단위로 센다. 미처리가 된 작업은 변경 수에서 빠질 수 있어 미처리 수를 먼저 본다. 전달 명세에서는 KPI의 허용오차와 별개로 작은 시각 변경도 정확히 표시한다.")
    sub("세 가지 판단을 분리한다", "① 입력이 충분하고 의미가 맞는지, ② 결과 일정이 제약을 지키는지, ③ 제한시간 내 목적값의 최적성이 증명됐는지는 다르다. 솔버 성공 표시만으로 승인하지 않고 별도 일정 검사와 현재 입력·계획 버전 검사를 거친다.")
    para("입력 부족, 시간 내 해 미발견, 증명된 불가능을 같은 ‘실패’로 묶지 않는다. SEARCH_LIMIT는 불가능의 증명이 아니며, 사람이 확인할 조건과 근거를 남긴다.")
    source("구현·목적 단계·의미검증: backend/engine/OPTIMIZATION.md 및 [4][10]. 현재 로컬 내부 승인은 외부 터미널 예약 변경이나 실제 운송 승인 권한이 아니다.")

    section(6,"모의 평가 설계와 전체 결과")
    para("실험 전에 입력·소스·시드·예산을 고정한 10개 합성 입력으로 B0~B3를 비교했다. 작은 8건 사례는 마감 단축·시작 지연·준비 지연·고정 위험을 두 생성 시드로 만들고, 20건·50건 규모 사례를 추가했다. 솔버 시드는 0과 17이며 작은 사례 3초, 규모 사례 10초다.")
    story.append(table([["항목", "동결 기록에서 확인한 값"],["계산 수", "10입력 × 2시드 × 4방법 = 80회"],
        ["독립 감사", "조정 결과 60개 일정 검사 · B0 원안 20개 무결성 검사"],
        ["B2/B3 비교", "20쌍 모두 미처리 수·고정 위험 동일, 처리 작업 집합까지 동일한 것은 14쌍"],
        ["최적성", "B2/B3 40회 중 전체 목적 최적성 증명 35회. 미증명 결과도 보존"],
        ["실험의 의미", "팀이 제약을 알고 만든 합성 입력. 현장 80건이나 독립된 80개 문제 아님"]],[.24,.76]))
    story.append(P("대표 결과 · 솔버 시드 0", "h2"))
    rows=[["사례", "미처리\nB2/B3", "변경\nB2→B3", "이동(분)\nB2→B3", "처리 작업"]]
    for case in cases:
        b2=case["methods"]["B2"]["result"]["metrics"];b3=case["methods"]["B3"]["result"]["metrics"]
        rows.append([case["label"].split(" · 생성")[0],f'{b2["unassigned_count"]}/{b3["unassigned_count"]}',
            f'{len(b2["changed_job_ids"])} → {len(b3["changed_job_ids"])}',f'{b2["movable_travel_minutes"]:g} → {b3["movable_travel_minutes"]:g}',
            "동일" if case["comparison"]["same_served_job_set"] else "다름"])
    story.append(table(rows,[.28,.14,.18,.23,.17]))
    source("원시 결과·시드 전체·입력·소스 해시 [4][5]. 과거 source 0d2640b의 실행이며 현 소스에서 새로 80회를 실행했다고 표시하지 않는다. 평가 원본의 승인 불가 플래그는 그대로 보존했다.")

    section(7,"변경 감소와 이동 증가의 절충")
    story.append(ComparisonChart(cases))
    source("그림 1. 6쪽의 대표 6사례를 같은 척도로 표시했다. 솔버 시드 0이며 전체 결과는 20쌍이다. 고정 위험 8건·마감 단축 20건은 처리 작업이 달라 직접 개선율을 계산하지 않는다. [5]")
    sub("같은 일을 했을 때 비교한다", "동일 작업 집합 14쌍 중 작은 사례 12쌍은 변경 작업 4~7건 감소와 이동 12~82분 증가가 함께 나타났다. 나머지 2쌍은 50건 사례로 변경·이동 차이가 없었다. 다른 작업 집합 6쌍은 별도로 해석한다.")
    sub("50건 결과도 함께 남긴다", "50건 B3 결과는 10초 예산에서 전체 최적성을 증명하지 못했다. 이 사례에서 B3의 개선을 확인하지 못했으므로 규모가 커져도 항상 변경을 더 줄인다고 설명하지 않는다.")
    sub("효과의 범위를 넘겨 말하지 않는다", "변경 최소화를 목적에 넣은 방법에서 변경 수가 작아졌다는 사실만으로 상용 TMS보다 우수하다고 볼 수 없다. 실제 배차 담당자의 확인 시간·운송비·탄소 계수가 없어 금전/시간/탄소 절감률로 환산하지 않았다.")

    section(8,"현재 구현과 실패 대응")
    story.append(table([["검증한 부분", "증거", "해석 한계"],
        ["입력→계산→비교→내부 승인", "기존 동일 입력/실행/계획 버전 통합 검수", "로컬 모의 계획. 공개 사용자 인증/현장 승인 아님"],
        ["자료 공백 9사례", "완전 4입력×4방법 16계산, 조정 12검사. 차단 5사례 솔버 0회", "모의 수용검사이며 실제 API/DB/웹 전체 검수 아님"],
        ["변경 명세·확인 안내", "B1 결과의 J0 고정 보존, J1/J2 양쪽 차량 명세, J3 준비 지연 안내", "오프라인 로직 인계. 저장 자료 대조는 현재 발송 권한 아님"]],[.26,.39,.35]))
    sub("담당자에게 남기는 정보", "J3가 미처리가 되면 ‘운송 취소’로 처리하지 않고 준비 완료 시각을 화주/상차지 담당자에게 확인할 대상으로 표시한다. 확인된 조건으로 새 입력을 만들되 원본과 이전 결과를 보존한다. 조건을 보완해도 해결되지 않을 수 있다.")
    story.append(P("전체 완료까지 남은 연결", "h2"))
    story.append(table([["아직 미완료", "확인할 결과"],
        ["실제 자료→서버→화면", "자료별 성공/실패·시각·단위·권한, 실제와 모의 구분"],
        ["조건 편집→재계산→전달/응답", "버전/대상자 권한·중복·오래된 계획 차단과 명시 응답"],
        ["공개 시연·HTTPS·휴대폰", "두 방문자 격리·계산 제한·실제 Android/iPhone 왕복 검수"]],[.40,.60]))
    source("로직 근거 [10], 공백 검수 [11]. 코드·검사 존재와 공개 배포/실휴대폰 수신의 완료는 구분한다. 미병합 PR은 이 보고서 소스의 구현으로 합산하지 않았다.")

    section(9,"도입 조건과 검증 계획")
    sub("실제 적용에 먼저 필요한 것", "허용된 비식별 배차표와 반입시간 변경 근거, 담당자가 실제로 바꿀 수 있는 조건을 받아 입력 필드에 대응시켜야 한다. 기존 TMS의 내보내기 형식·사용 허가와 입력 준비 부담, 예외 대응 절차를 확인한다. 현재 운송사 협조 표본·사용 의향은 확보하지 못했다.")
    sub("완성 검수의 순서", "① 담당 파트의 자료/화면/API 자체검사 인계 ② 같은 입력·실행·계획 버전으로 최종 통합 ③ 두 방문자 분리·자원/요청 제한·오류 복구 ④ 본인 서버와 HTTPS 주소에 배포 ⑤ 지정 팀원 휴대폰의 실제 알림·열람·명시 응답·담당자 상태 검수 ⑥ 최종 보고서·코드 버전 고정 순으로 진행한다.")
    story.append(table([["검증 질문", "완료로 인정할 증거"],
        ["누락/오래된 값으로 계산·승인하지 않는가", "차단 사유, 현재 입력·계획 버전, 실패 후 화면 상태"],
        ["남의 계획·알림에 접근할 수 없는가", "두 세션/수신자 교차 요청의 거절과 회귀 결과"],
        ["확정한 변경이 실제 대상자에게 이어지는가", "동일 계획 버전의 전송 상태·실기기 표시·명시 응답·담당자 상태"],
        ["제출 자료를 다시 확인할 수 있는가", "소스 커밋·파일 해시·동결 원본·새 폴더 검사·보고서 수치 대조"]],[.42,.58]))
    sub("운영 비용과 한계", "웹 푸시는 자체 VAPID 방식으로 별도 문자업체 가입 없이 구현할 수 있지만 HTTPS·수신자의 최초 접속/허용이 필요하고 서버 운영비는 별도다. 사업자·기관 자격이 필요한 계약이나 허가 없는 데이터 공유를 기본 전제로 삼지 않는다. 기상·AIS를 추가해도 지연 원인을 자동 입증하는 것은 아니다.")
    source("사용자 요구에 따라 실제 서버/주소/배포는 황대겸이 수행한다. 이 검토본은 배포나 외부 전송을 실행한 증거가 아니다. 최신 완료 기준 [7].")

    section(10,"출처와 재현 안내")
    para("보고서 수치와 파일은 함께 제공하는 코드·데이터 ZIP에 연결된다. ZIP은 Git·API 키·로컬 DB·설치 의존성을 포함하지 않는다. 과거 평가 소스는 해시를 검증할 수 있도록 별도 보존하며, 새 계산과 과거 기록의 감사를 구분한다.")
    refs=[
        ("1", "HJNC 지연 반입 청구 제도 공지", "https://www.hjnc.co.kr/board/notice/detail?no=1381", "게시 2026.07.09. 기존 프로젝트 검증 기록의 업무 근거."),
        ("2", "HJNC 반입 제한 일자 변경", "https://e-service.hjnc.co.kr/board/notice/detail?no=521", "게시 2022.12.09. 역사적 변경 사례."),
        ("3", "HJNC 선반입 서비스", "https://www.hjnc.co.kr/esvc/m/notice/detail?no=101", "게시 2023.09.11 및 후속 변경 표기. 개별 이용 권한 별도."),
        ("4", "동결 평가 설계·원시 결과", "https://github.com/unknownamed/banipmatch/tree/"+source_commit+"/docs/experiments/engine-evaluation-2026-11-08", "코드 ZIP 동일 경로. 실행 소스 0d2640b, 80회·20쌍."),
        ("5", "대표 사례와 전체 비교", "https://github.com/unknownamed/banipmatch/blob/"+source_commit+"/docs/experiments/engine-evaluation-2026-11-08/showcase.md", "showcase.json / results/pairs.csv에서 표·그림 생성."),
        ("6", "기존 서비스 공개 비교·원출처 목록", "https://github.com/unknownamed/banipmatch/blob/"+source_commit+"/docs/team/service-comparison.md", "TIGER FACE·PortQM·PortWise·CONTAINUS 등. 미확인 기능 구분."),
        ("7", "담당자 대응 완성 범위 R1~R8", "https://github.com/unknownamed/banipmatch/blob/"+source_commit+"/docs/team/dispatcher-response-scope.md", "조건 재계산·전달·응답과 완료 증거. 계획과 구현을 구분."),
        ("8", "표준 Web Push / iOS 홈화면 조건", "https://webkit.org/blog/13878/web-push-for-web-apps-on-ios-and-ipados/", "기술 가능성의 근거. 우리 단말의 성공 증거는 아님."),
        ("9", "자료 파트·제공기관별 검증", "https://github.com/unknownamed/banipmatch/blob/"+source_commit+"/docs/report/data-part.md", "HJNC·기상청·도로 원출처/표본·공백·합성 21종 연결."),
        ("10", "변경 명세 로직 인계", "https://github.com/unknownamed/banipmatch/tree/"+source_commit+"/docs/experiments/dispatch-response-2026-11-10", "모의 B1 결과·명세·해시. 실제 발송 아님."),
        ("11", "자료 공백 9사례", "https://github.com/unknownamed/banipmatch/tree/"+source_commit+"/docs/experiments/data-demo-2026-11-10", "입력·가정·차단·원시 결과. 동결80회와 별도."),
    ]
    for n,title,url,note in refs:
        story.append(P(f'[{n}] <link href="{escape(url)}" color="#285448">{escape(title)}</link> - {escape(note)}',"small"))
    story.append(Spacer(1,4*mm))
    para("<b>재현 순서</b>  ZIP을 새 폴더에 푼 뒤 docs/submission/README.md에 따라 파일 해시 검사, 의존성 설치, 동결 80회 감사, 계약/DB 및 주요 회귀를 실행한다. 원본 Git 이력 전용 검사는 따로 명시했다. 최종 제출 전 실제 연결·배포 결과를 반영하고 보고서 전체 20쪽 이내, 코드/데이터 버전 일치를 다시 확인한다.")
    source(f"검토 기준 2026.11.10 · 소스 {source_commit}<br/>저장소가 비공개이면 GitHub 링크 접근 권한이 필요하다. 같은 경로의 파일은 코드 ZIP에서도 확인할 수 있다. 외부 공지의 변경 여부와 제출 요건은 최종 제출 전 재확인한다.")

    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(output), pagesize=(210*mm,297*mm), leftMargin=18*mm, rightMargin=18*mm,
                            topMargin=18*mm, bottomMargin=18*mm, title="반입맞춤 문제해결 보고서 - 검토본", author="반입맞춤 팀")
    def footer(canvas, document):
        canvas.saveState(); canvas.setStrokeColor(LINE);canvas.line(18*mm,15*mm,192*mm,15*mm)
        canvas.setFillColor(MUTED);canvas.setFont("KR",7.5)
        canvas.drawString(18*mm,10*mm,"반입맞춤 | 검토본 · 2026.11.10")
        canvas.drawRightString(192*mm,10*mm,str(document.page));canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    pages=len(PdfReader(output).pages)
    if pages != 10:
        raise ValueError(f"Expected 10 carefully composed pages, got {pages}; inspect overflow")
    inputs=[Path(__file__).resolve(), ROOT/"requirements-report.txt",bundle_path,ROOT/"docs/report/report-draft.md",ROOT/"docs/report/data-part.md",
            ROOT/"docs/report/evidence-index.md",ROOT/"docs/team/dispatcher-response-scope.md",
            ROOT/"docs/experiments/engine-evaluation-2026-11-08/results/pairs.csv"]
    metadata={"stage":"review_draft","source_commit":source_commit,"page_count":pages,
              "recorded_at_utc":datetime.now(timezone.utc).isoformat(),"client_date":"2026-11-10",
              "pdf_sha256":hashlib.sha256(output.read_bytes()).hexdigest(),
              "input_hash_convention":"UTF-8 text bytes with CRLF normalized to LF only",
              "inputs":{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes().replace(b"\r\n",b"\n")).hexdigest() for p in inputs},
              "historical_run_commit":bundle["provenance"]["source_commit"],"solver_rerun":False,
              "fonts":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [font,bold]},
              "deployment_or_delivery_performed":False}
    output.with_suffix(".build.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    return metadata


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--font",type=Path,default=Path("C:/Windows/Fonts/malgun.ttf"))
    parser.add_argument("--bold-font",type=Path,default=Path("C:/Windows/Fonts/malgunbd.ttf"))
    args=parser.parse_args()
    print(json.dumps(render(args.output,args.font,args.bold_font),ensure_ascii=False,indent=2))
