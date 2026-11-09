# API·DB 로컬 구현

공통 입력 등록·조회 → 실행 전 입력 검사 → 결과 조회를 연결한 로컬 시제품임.
기본 모드는 설명용 B0/B3 재생이며 `BANIPMATCH_RUN_MODE=engine` 설정 시 B0~B3을 실계산함. 조정 결과는 독립 일정 검사 후 단일 로컬 모의 주체가 내부 승인할 수 있음. 실제 운영 인증은 미구현임.
설명용 결과 승인 요청은 `422 RESULT_NOT_COMPUTED`로 차단.

## 실행

저장소 루트에서 Python 3.12 이상 사용. 이미 `.venv`가 있으면 환경 생성 생략.
Windows PowerShell 기준이며 활성화 스크립트를 실행할 필요 없음.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:BANIPMATCH_DEMO = '1'
$env:BANIPMATCH_DEMO_TOKEN = .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
.\.venv\Scripts\python.exe -m backend
```

서버는 `http://127.0.0.1:8000`, API 확인 화면은 `http://127.0.0.1:8000/docs`임.
실계산을 원하면 서버 실행 전에 `$env:BANIPMATCH_RUN_MODE = 'engine'` 설정. B0~B3을 한 방법씩 자식 프로세스에서 실행하고 방법별 요청 제한시간에 5초의 프로세스 시작 여유를 더한 시각에 강제 종료함. B2/B3에는 `backend/engine/requirements.txt`의 OR-Tools가 필요하며 위 개발 의존성 설치에 포함됨. 기본 fixture 모드의 기존 API 동작은 유지함.
Swagger의 Authorize에 실행 터미널의 `BANIPMATCH_DEMO_TOKEN` 값을 넣어 요청.
모든 POST에는 별도의 `Idempotency-Key` 필요. 같은 키·같은 요청은 최초 응답 재전달, 다른 본문은 409.
토큰은 로컬 모의 접속 확인용이며 사용자·운송사 역할 인증을 구현한 것이 아님.
기본 DB는 `local/banipmatch-demo.sqlite3`이며 최초 기동에서 자동 생성.

설정 예시는 루트 `.env.example`에 있음. 환경변수로 직접 지정하며 `.env`를 자동으로 읽지 않음.
DB 경로는 `BANIPMATCH_DB_PATH`, 프론트 허용 출처는 `BANIPMATCH_CORS_ORIGINS`로 지정.
기본 프론트 출처는 `http://localhost:5173`, `http://127.0.0.1:5173`임.
Swagger 등 API 서버 자체와 동일한 출처의 요청도 허용. 다른 출처는 위 설정으로 명시해야 함.
모의 모드 명시·24자 이상 ASCII 토큰이 없으면 기동 실패. loopback 연결만 허용.
같은 DB에 서버를 중복 실행하지 못하도록 프로세스 잠금 사용.

## 연결된 API

| 호출 | 동작 |
|---|---|
| `POST /v1/scenarios` | Snapshot 구조·저장 무결성 검사, 원본·해시·검색 행·기준 계획 원자 저장, 201 |
| `GET /v1/scenarios/{scenario_id}` | 불변 입력 조회 |
| `POST /v1/runs` | 최신 입력·계획 확인 후 실행 등록, queued 상태와 202 |
| `GET /v1/runs/{run_id}` | queued/running/completed/failed 상태 조회 |
| `GET /v1/runs/{run_id}/results` | 진행 중 202와 Retry-After, 완료 후 200, 실패 시 503 |
| `GET /v1/plans/{plan_id}` | 현재 기준 계획 조회. 설명용 결과가 기준 계획을 변경하지 않음 |
| `POST /v1/plans/{plan_id}/approvals` | 독립 검증·위험 확인·현재 입력 및 버전 확인 후 내부 계획을 새 버전으로 원자적 저장. 이전 입력·계획은 409, 설명용 결과는 422 |

런타임 `/openapi.json`은 배포 계약의 객체·경로를 사용하며 로컬 모의 구현 상태를 설명에 표시.
런타임 복사본의 서버 주소는 `/`로 설정해 Swagger를 연 현재 호스트·포트로 요청함.
`docs/development/v0.1/` 원본은 수정하지 않음.
입력 스키마 통과, 최소 저장 무결성, 데이터 의미, 일정 타당성, 승인 적격성은 별개임.
현재의 스키마·DB 검사 성공을 전체 의미 검증·일정 검증 성공으로 표현하지 않음.

## 첫 연결에 사용할 자료

- 입력: `docs/development/v0.1/예제 데이터/01_snapshot.json`
- 실행 요청: 같은 폴더의 `02_run_request.json`
- 결과: 같은 폴더의 `04_results_설명용.json` 중 요청한 B0/B3
- 결과에서 J0 원안 유지, J1/J2 조정, J3 미처리 이유 확인 가능
- 입력의 `scenario_id`, `plan_id`만 바꿀 수 있음. 다른 업무 값이 바뀌면 설명용 결과 재사용 차단
- 07 입력 누락은 저장 가능하지만 실행은 422, 08 미확인 변경은 저장 가능하지만 실행은 503
- B1/B2는 아직 설명용 결과가 없어 요청 시 422

프론트는 실제 `run_id`로 조회하고 `result_origin=illustrative_fixture`,
`validation_status=not_run`, `approval_eligible=false`를 그대로 표시해야 함.
예제 날짜가 지나도 설명용 재생만 허용하는 구조임. 승인 시각 검사를 우회한 실계산 기능이 아님.
seed·시간 예산은 요청 이력으로 저장하지만 설명용 응답에서는 계산에 사용하지 않음.

별도 터미널에 서버와 같은 모의 토큰을 설정한 뒤 실행 흐름 확인 가능.

```powershell
$env:BANIPMATCH_DEMO_TOKEN = '<서버 실행 터미널과 같은 값>'
.\.venv\Scripts\python.exe tools/demo_api.py
```

매 실행마다 새 모의 입력·계획 ID를 만들고 등록→조회→결과→승인 차단을 확인.
계산 요청 재시도에는 같은 멱등키를 사용해야 하며 새 키는 별도 run을 생성.

## 대표 모의 사례의 실계산·승인 재현

서버는 위 실행법대로 `BANIPMATCH_RUN_MODE=engine`으로 시작함. 다른 터미널에는 서버와 같은 모의 토큰을 설정하고 저장소 루트에서 실행.

```powershell
.\.venv\Scripts\python.exe -m tools.demo_engine_api
```

- 공통 예제 01의 작업·차량·이동 가정을 사용하고 모든 업무·출처 시각을 현재 UTC 분 경계로 같은 간격만큼 이동함. 배포 원본과 서버 시계를 변경하지 않음. 실제 자료로 바꾸는 작업이 아님.
- 새 입력·계획 ID로 등록하고 같은 입력·시드·방법별 예산(기본 10초)으로 B0~B3을 실행. B3 독립 검사 통과 후 미처리·고정 위험을 확인해 내부 승인하고, 같은 키 재시도와 다른 키의 이전 버전 409를 확인함. 확인 목록은 사람이 실제 작업을 확인했다는 증거가 아니라 자동화된 모의 시연임.
- `local/demo-evidence/<새 ID>/`에 `snapshot.json`, 원본·시각 이동·로컬 소스 해시와 환경의 `manifest.json`, 단계별 요청/응답 `http_steps.jsonl`, 전체 결과·지표·승인·계획의 `evidence.json`을 남김. 인증 헤더와 토큰은 기록하지 않음. 기존 출력 폴더는 덮어쓰지 않으며 실패 시 `failed.json`과 수신한 단계 기록을 확인.
- `--base-url http://127.0.0.1:8123`으로 서버 포트, `--time-limit 10`으로 방법별 예산, `--output local/demo-evidence/my-case`로 새 출력 디렉터리를 지정 가능. 로컬 HTTP 주소만 허용. 입력 유효기간이 지나면 새 모의 사례로 재실행.
- 통신 실패는 승인 미저장을 뜻하지 않음. 실패한 사례의 `snapshot.json`에 있는 계획 ID로 현재 계획을 먼저 조회해 승인 여부를 확인함.
- 소스·환경 해시는 도구 실행 측 기준이므로 같은 체크아웃·환경에서 서버를 실행해야 함. 서버 응답의 엔진·솔버 버전도 함께 확인.
- 결과는 1초 간격으로 조회함. 기본 3초 설정은 1초 조회에서도 일부 Windows 실행에서 B2 프로세스 시간 초과가 재현돼 시연 기본값을 10초로 정함. `--time-limit 3`은 명시적으로 요청할 수 있으나 성공을 보장하지 않음. 서버의 방법별 예산+시작 여유 5초 제한은 유지하며 실패를 자동으로 재계산해 감추지 않음.

길웅의 화면에서 직접 승인할 때는 **새 사례**를 아래처럼 준비함. 도구가 계산·독립 검사까지만 수행하고 승인 전 계획을 유지함.

```powershell
.\.venv\Scripts\python.exe -m tools.demo_engine_api --review-only
```

프론트를 HTTP 모드로 실행하고 출력된 ID를 `http://localhost:5173/?scenario=<scenario_id>&run=<run_id>`에 넣어 결과 비교·위험 확인·내부 승인을 진행. 이미 기본 모드로 승인한 사례를 재사용하면 다른 키 승인은 409로 거절됨.

공통 예제는 연결 확인용임. 이번 검수에서 B1~B3의 미처리·변경·이동은 같았으며 B3의 우위를 보여주는 성능 사례가 아님. 위반 배정도 보존하는 B0와 조정안의 처리 수준을 단순 효율 개선률로 비교하지 않음. 이 도구의 HTTP 검수를 브라우저 전체 검수·현장 효과 검증으로 설명하지 않음.

## DB와 후속 연결

스키마 버전 1의 배포 SQL을 사용하며 기존 DB를 자동 덮어쓰지 않음.
각 연결에서 `foreign_keys`, `recursive_triggers` 활성화. 입력 원본·계획 이력은 불변.
SQLite INTEGER 컬럼에 저장하는 값은 signed 64-bit 범위로 검사함. 범위 초과는
`422 INTEGER_OUT_OF_RANGE`와 `/seed`, `/vehicles/1/capacity_kg` 같은 원본 필드 경로로 반환.
정수형 실수 표현은 정확한 정수 값으로 바인딩하며 원본 JSON·입력 해시는 변경하지 않음.
저장 중 거절되면 앞서 삽입한 행과 멱등 기록도 같은 트랜잭션에서 롤백.
새 입력 등록은 현재 계획 버전·배정·미처리와 기준 일치를 검사하고 활성 입력만 변경.
이전 입력·실행·설명용 결과는 이력으로 남김.
재시작 시 이전 queued/running은 `RUN_INTERRUPTED` 실패로 기록하며 자동 재실행하지 않음.
테스트 DB는 `BANIPMATCH_DB_PATH`로 별도 파일을 지정해 생성. 운영 DB 이전 절차는 후속 작업임.

- `backend/api/`: HTTP·오류·실행 상태와 설명용 어댑터
- `backend/db/`: 기존 SQL 초기화·트랜잭션·멱등 응답·버전 저장
- 데이터 담당 연결: 등록은 최소 저장 검사만 수행하고, 실행 요청 시 데이터 모듈의 `validate_snapshot`으로 입력 관계·누락·출처 시각을 검사함. 입력 부족은 422, 미확인 반입시간은 503으로 반환하고 필드별 이유를 전달함. CSV 업로드는 미구현.
- 엔진 담당 연결: 선택 모드의 B0~B3을 별도 자식 프로세스에서 호출함. 한 방법이라도 실패·시간 초과하면 전체 실행을 failed로 기록하며 부분 결과를 저장하지 않음. 작업 분할·고정 보존·차량 경로·시간·장비·중량·잔여 위험·지표를 엔진과 별도로 재계산함. 검증 통과한 B1~B3 조정안만 승인 대상이며 B0·설명용 결과·검사 실패 결과는 차단함. 엔진의 최적성 증명을 다시 증명하지 않으며 단계 기록과 반환 지표의 일관성만 검사함.
- 현재 시간 제한은 방법별 예산에 시작 여유 5초를 더한 자식 프로세스 제한임. 공개 서비스의 동시 사용자 격리·입력 크기 제한은 후속 작업임.
- 모의 승인: 서버 시각 기준 입력 유효기간·현재 입력과 계획 버전·미처리 및 고정 위험 확인을 승인 트랜잭션에서 재검사함. 계획·배정·승인·멱등 응답과 조건부 버전 갱신은 함께 저장하거나 모두 롤백함. 외부 예약 변경·기사 통보는 하지 않음. 로컬 공통 토큰은 실제 사용자·운송사 권한 인증이 아니며 공개 서비스에서는 사용할 수 없음.

## 최신 main 기준의 안선효 추가 담당

[서비스 비교](../docs/team/service-comparison.md)의 내부 배차·반입시간·방문예약·접안 상태 구분을 유지함.
현재 입력·DB 계약을 바꿀 필요는 없으며, 외부 예약 변경·기사 통보를 수행하는 API를 추가하지 않음.
B0~B3 엔진을 선택형 실계산 모드로 연결함. 설명용 결과와 구분함. 실행 방법은 [엔진 안내](engine/README.md) 참조.

[외부 API 준비 안내](../docs/team/api-onboarding.md)와 [진행표](../docs/team/api-access-status.md) 기준으로 다음 준비가 추가됨.

| 항목 | 안선효가 준비할 일 | 현재 API 구현과의 관계 |
|---|---|---|
| AP-06 AISstream | 기존 계정·키 보유 여부 확인, 서버용 키·수신 범위·표시/저장 조건 준비 | 별도 서버 수집 후보. 현재 Snapshot에 AIS·ETA 필드를 추가하지 않음 |
| AP-08 자동차 길찾기 | 최길웅과 팀 앱·서버 권한·경로 저장/재사용 조건 확인 | 실제 경로를 확보하기 전 모의 이동행렬 유지 |
| AP-10 SOLAPI | 발신번호·명의확인 절차와 시험·비용 조건 확인 | 외부 발송 미구현·비활성 유지 |
| 공통 연동 설계 | 비밀값의 보관·접근 주체, 서비스별 호출량·캐시·오류·최신성 처리 정리 | 본인 전용 키를 전달받거나 조회 때마다 외부 호출하는 구조로 연결하지 않음 |

이번 main 동기화·코드 검토에서는 가입·키 발급·실제 수집·문자 발송을 실행하지 않았음.
계정·승인·실응답은 여전히 미확인이며, 위 준비 목록을 구현 완료·이용 승인으로 표시하지 않음.

FastAPI 선택 이유는 기존 Python 단일 백엔드 방향과 OpenAPI 요청·오류 경계를 연결하기 쉬워서임.
객체 정의는 기존 JSON Schema를 직접 사용해 별도 모델 복제에 따른 불일치를 줄임.
SQLite는 기존 16개 테이블 규격을 그대로 실행하기 위해 사용.
참고: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
[작업 실행 범위](https://fastapi.tiangolo.com/tutorial/background-tasks/).

## 검증

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools/check_development.py
```

API 검사는 등록·불변 저장·해시·멱등성·동시 요청·입력 변경·승인 차단·작업 중 조회·실패·재시작·로컬 접속 제한을 확인.
기존 검수는 원본의 임시 복사본에서 계약·예제 29건과 DB 32건을 확인.
현장 성과·운영 인증·실자료 타당성은 검증 범위에 포함하지 않음. 로컬 모의 내부 승인 검수는 위 실계산 시연 및 최신 통합 인계 참조.

2026-11-07 Windows의 Python 3.12.10·3.13.3에서 각각 API 27건과 기존 61건 통과.
실제 로컬 서버의 HTTP 예제 흐름도 확인했으며 검사 서버는 종료함.
이 작업 폴더의 기본 `.venv`는 Python 3.13.3, 별도 3.12 환경은 `local/venv312`임.
같은 날 최신 main 동기화 후 Swagger의 동일 출처 POST 차단을 재현·수정했고,
Python 3.12.10에서 회귀 검사 2건을 포함한 API 29건 통과. 배포 계약 원본은 변경하지 않음.
PR #3 코멘트 반영 후 같은 환경에서 API 45건 통과. 정수 저장 경계·전체 롤백·정수형 실수,
실제 런타임 명세의 서버 주소를 해석하는 Swagger 호스트·포트 검사를 포함함.
