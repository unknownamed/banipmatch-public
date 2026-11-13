# 반입맞춤 코드·데이터

반입맞춤은 부산항 신항 컨테이너 운송사를 위한 배차 조정 서비스입니다. 터미널이 수출 컨테이너의 반입 마감을 바꾸면 남은 배차를 가장 적게 고쳐 다시 맞추고, 일정이 바뀐 기사에게만 변경 내용을 알려 줍니다.

이 묶음에는 서비스의 소스 코드, 계산에 쓴 데이터, 실험 기록, 보고서 원고가 모두 들어 있습니다. 보고서와 같은 시점의 코드이고, 운영 중인 서비스도 이 코드로 돌아갑니다.

- 서비스 주소: https://banipmatch.duckdns.org (가입 없이 바로 쓸 수 있습니다)
- 체험 순서와 심사용 코드: 아래 「운영 주소에서 바로 써 보기」(보고서 4.1절과 같음)
- 사용 장면: 별도로 보낸 시연 영상
- 개발 과정(커밋과 PR 기록): https://github.com/unknownamed/banipmatch-public

## 운영 주소에서 바로 써 보기

설치 없이 약 5분이면 처음부터 끝까지 해 볼 수 있습니다.

1. https://banipmatch.duckdns.org 에 접속합니다. 가입은 필요 없고, 방문자마다 따로 작업공간이 열립니다(24시간).
2. **받은 변경**에서 'HJNC BHMN … 반입 마감 2시간 30분 앞당김'을 고르고 **영향 확인하고 조정안 보기**를 누릅니다. 10초쯤 뒤 점검 결과가 나옵니다.
3. **점검 결과**에서 요약, 조정안 비교(시간 막대), 차량 지도를 차례로 봅니다.
4. **조건 보완**에서 확인이 필요한 컨테이너(BNJU 100208 3)의 상차 준비 시각을 40분 앞당기고, 녹산 차고지 차량 1대를 추가한 뒤 **다시 계산**을 누릅니다. 남아 있던 1건까지 배정되고 전후 비교가 나옵니다.
5. **확정**에서 남는 위험을 확인하고 확정하면 **기사 전달**에 차량별 변경 내용과 기사 안내문이 나옵니다.
6. **기사 전달**의 '알림 사용 코드'에 심사용 코드(제출한 보고서 4.1절)를 넣고 **알림 기능 켜기**를 누릅니다. 여러 분이 같은 코드를 써도 됩니다.
7. 차량 하나의 **안내문·연결 링크 복사**로 받은 링크를 휴대폰에서 열고 **연결하고 알림 받기**를 누릅니다. 카카오톡 안에서 열렸다면 다른 브라우저로 여세요. 아이폰은 공유 버튼에서 '홈 화면에 추가'한 뒤 엽니다.
8. PC에서 **연결된 기사에게 보내기**를 누르면 휴대폰에 알림이 옵니다. 휴대폰에서 '수행 가능' 또는 '수행 곤란'으로 답하면 PC 화면에 바로 표시됩니다.

왼쪽 메뉴의 **입항 선박**과 **터미널 일정**에서는 서버가 수집한 HJNC 일정과 기상청 관측을 볼 수 있습니다.

## 서비스가 하는 일

1. **영향 점검.** 바뀐 마감을 받으면 원래 배차대로 갈 때 마감을 넘기는 컨테이너가 몇 건인지, 왜 늦는지부터 계산합니다.
2. **최소 변경 재배차.** 이미 출발한 차량은 그대로 두고, 늦는 컨테이너를 최대한 줄인 다음 바뀌는 작업이 가장 적은 배차를 찾습니다. 계산에는 Google OR-Tools의 CP-SAT를 씁니다.
3. **조건 보완.** 화주가 상차 준비를 앞당길 수 있거나 차량을 더 구했다면 그 조건을 넣어 다시 계산하고 전후를 비교합니다.
4. **확정과 기사 전달.** 담당자가 확정하면 일정이 바뀐 차량의 기사에게만 변경 내용과 알림을 보냅니다. 기사는 링크 하나로 연결해 '수행 가능' 또는 '수행 곤란'으로 답합니다.

## 들어 있는 것

| 위치 | 내용 |
|---|---|
| `report/` | 문제해결 보고서 PDF와 생성 기록 |
| `backend/engine/` | 배차 엔진. 모형 설명은 `OPTIMIZATION.md` |
| `backend/workflow/` | 운영 서버 API(작업공간, 계산 대기열, 확정, 기사 전달과 응답) |
| `backend/api/`, `backend/data/` | 입력 검증과 실제 자료 변환 |
| `frontend/` | 담당자 화면과 기사 화면(React, TypeScript) |
| `tools/` | 실제 자료 수집, 실험과 보고서 재현, 제출 묶음 생성과 검사 |
| `tests/` | 서버, 엔진, 계약 시험 |
| `docs/report/final/` | 보고서 원고(HTML)와 그림 |
| `docs/experiments/` | 실험 입력과 결과(80회 평가, 무작위 입력 검사, 시연 사례) |
| `docs/data/` | 실제 자료(HJNC, 기상청, 도로공사, AIS, ORS) 응답 검증 기록 |
| `docs/development/` | 입력 규격(OpenAPI, JSON Schema, SQL)과 예제 |
| `docs/deployment/`, `deployment/` | 운영 서버 구성과 설정 예시 |
| `docs/team/` | 팀 역할, 개발 규칙, 작업 인계 기록 |
| `submission-evidence/` | 80회 평가를 실행한 시점의 엔진 소스(결과 무결성 확인용) |
| `submission-manifest.json` | 묶음 안 모든 파일의 크기와 해시 |

비밀번호, API 키, 로컬 DB, 설치 파일(`.venv`, `node_modules`), Git 기록은 넣지 않았습니다. `.env.example`과 `deployment/cloud/*.example`에는 빈 값과 예시만 있습니다.

## 데이터

실제로 받을 수 있는 공개 자료는 실제 자료를 썼습니다. 운송사의 배차표와 차량 정보는 공개 자료가 없어서 팀이 모의 자료를 만들었고, 거리와 시간은 실제 도로를 기준으로 계산했습니다.

| 자료 | 출처 | 구분 | 위치 |
|---|---|---|---|
| 선석 배정, 반입 시작과 마감 | HJNC 공개 조회(운영 서버가 1시간마다 수집) | 실제 | 수집 코드 `tools/collect_live_reference.py`, 검증 기록 `docs/data/` |
| 해상 관측과 특보 | 기상청 API허브(30분마다 수집) | 실제 | 같은 곳 |
| 도로 경로 | OpenStreetMap, OSRM | 실제 | `frontend/src/fixtures/road-routes.osm.json` |
| 배차표, 차량, 컨테이너 | 팀이 만든 모의 자료 | 모의 | `frontend/src/fixtures/demo-02-*.synthetic.json` |
| 실험 입력과 결과 | 엔진 실행 기록 | 실험 | `docs/experiments/` |

배차 시연에 나오는 선박명, 회사명, 배차 자료는 모두 가상입니다. 수집 주기와 호출 한도, 품질 규칙은 보고서 2장에 정리했습니다.

## 확인하는 방법

명령은 모두 이 폴더(`banipmatch`)에서 실행합니다. Windows PowerShell 기준이며, Python 3.12와 Node.js 24가 필요합니다.

### 1. 파일이 그대로인지 확인

설치 전에 먼저 실행합니다. 추가 패키지가 필요 없습니다.

```powershell
python tools/check_submission.py --files-only
```

모든 파일의 크기와 해시, 보고서와 소스의 일치를 대조해 `"verified": true`를 출력합니다.

### 2. 시험 실행

Python 환경은 이 폴더 **밖**에 만듭니다. 폴더 안에 만들면 파일이 늘어나 1번 검사가 실패합니다.

```powershell
python -m venv ../banipmatch-env
..\banipmatch-env\Scripts\python.exe -m pip install -r requirements-dev.txt -r backend/data/requirements.txt -r requirements-workflow.txt
..\banipmatch-env\Scripts\python.exe -m pytest -q --ignore=tests/engine/test_showcase_evidence.py --ignore=tests/engine/test_evaluation.py
..\banipmatch-env\Scripts\python.exe tools/report_demo_scenarios.py
..\banipmatch-env\Scripts\python.exe tools/check_engine_robustness.py .
```

- 첫 번째 명령은 서버와 엔진 시험입니다. 빼 둔 두 모듈은 Git 기록을 읽는 시험이라 이 묶음에서는 실행되지 않고, 대신 `tools/check_submission.py`가 같은 내용을 확인합니다.
- `report_demo_scenarios.py`는 보고서 5.1절의 시연 사례를, `check_engine_robustness.py`는 5.2절의 무작위 입력 검사를 다시 계산합니다.

화면 시험은 다음과 같습니다.

```powershell
cd frontend
npm ci --ignore-scripts
npm test
```

### 3. 내 컴퓨터에서 서비스 띄우기

```powershell
$env:BANIPMATCH_DEMO='1'; $env:BANIPMATCH_WORKFLOW='1'; $env:BANIPMATCH_RUN_MODE='engine'
$env:BANIPMATCH_CORS_ORIGINS='http://localhost:5173'
..\banipmatch-env\Scripts\python.exe -m uvicorn backend.webapp:create --factory --port 8000
```

다른 터미널에서 화면을 띄운 뒤 브라우저로 http://localhost:5173 을 엽니다.

```powershell
cd frontend
$env:VITE_API_MODE='v2'; npm run dev
```

지도를 보려면 카카오 JavaScript 키가, 기사 알림을 보내려면 VAPID 키가 필요합니다(`.env.example` 참고). 키가 없어도 배차 계산, 조건 보완, 확정은 그대로 동작합니다. 키가 설정된 상태는 운영 주소에서 볼 수 있습니다.

## 팀

| 이름 | 맡은 일 |
|---|---|
| 황대겸 | 팀장, 최적화 엔진, 통합, 운영 배포, 보고서 |
| 안선효 | 서버 API, DB, 알림 |
| 최길웅 | 담당자 화면과 기사 화면 |
| 심민준 | 실제 자료 검증, 모의 데이터 |

2026 국립창원대학교 스마트물류 문제해결 경진대회, 팀 반입맞춤
