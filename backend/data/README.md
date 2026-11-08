# 데이터 입력·준비 모듈

담당: 심민준. 계약: `docs/development/v0.1/`의 `0.1.0`.

CSV·JSON 입력을 검사하고, 통과한 스냅샷 사본 또는 오류 목록을 반환합니다.
DB 저장·배차 계산·결과 일정 검사·승인·외부 API 호출은 수행하지 않습니다.
공통 계약·배포 PDF·기존 예제는 변경하지 않았습니다.

## 설치·검사

저장소 루트에서 개인 가상환경을 활성화한 뒤 실행합니다. CI는 Python 3.12입니다.

```sh
python -m pip install -r backend/data/requirements.txt
python -m unittest discover -s tests/data -v
```

전체 계약·DB 검사는 `CONTRIBUTING.md`의 기존 검수 의존성 설치 후
`python tools/check_development.py`로 별도 실행합니다.

## API·엔진 담당이 연결할 함수

```python
from dataclasses import asdict
from pathlib import Path
from backend.data import load_jobs_csv, load_snapshot_json, validate_snapshot

examples = Path("docs/development/v0.1/예제 데이터")
report = load_snapshot_json(examples / "01_snapshot.json")
if not report.valid:
    raise ValueError([asdict(issue) for issue in report.issues])
snapshot = report.snapshot
# API 담당이 저장·버전 처리를 연결하고, 엔진 담당이 계산한다.

# 이미 파싱한 JSON 객체도 검사할 수 있다.
report = validate_snapshot(snapshot, source="demo-input")

# CSV에는 jobs만 있다. 차량·위치·시간창·이동·원안 등은 문맥으로 제공한다.
# evidence는 실제 입력의 출처에 맞춰 호출자가 명시하며, 기존 작업에서 복사하지 않는다.
report = load_jobs_csv(
    examples / "jobs_template.csv",
    context=snapshot,
    evidence={
        "kind": "simulated",
        "source_ref": "fixture:scenario_001",
        "observed_at": None,
        "received_at": "2026-11-07T00:00:00Z",
    },
)
```

- `InputReport.valid`: 이 첫 구현의 검사 통과 여부.
- `InputReport.snapshot`: 통과하면 독립 사본, 하나라도 오류가 있으면 `None`.
- `InputReport.issues`: `InputIssue`의 튜플. `code`, JSON Pointer `path`, `message`, `source`, `row`.
- CSV의 `row`는 헤더를 포함한 물리적 시작 행 번호다. 작업 오류는 CSV 파일명·행에 연결하며 문맥 오류에는 CSV 행을 붙이지 않는다.
- JSON 문법 오류에는 행 번호가 있다. JSON 스키마·의미 오류는 필드 경로로 식별하며 행 번호는 없다.
- 이 객체는 내부 Python 인터페이스다. 새 HTTP 응답 계약이 아니며, API 담당이 기존 `Error.details` 등으로 변환한다.
- 입력 dict·파일을 수정하지 않는다. 사본의 영구 불변 저장·해시 생성·버전 등록은 API·DB 담당이 연결한다. 반환 dict 자체가 수정 불가능한 객체인 것은 아니다.

## 지원하는 입력과 검사

- JSON: 전체 Snapshot, UTF-8/BOM 지원. 문법 오류·중복 객체 키·읽기 실패를 구분.
- CSV: 기존 `jobs_template.csv`와 같은 열 집합. 열 순서는 달라도 되지만 중복·누락·추가 열은 거절. UTF-8/BOM·인용부호 처리.
- CSV 정수와 `True/False`를 실제 타입으로 변환. nullable 열의 빈칸만 `None`으로 변환하고 빈 값에 임의 기본값을 넣지 않음.
- 모든 입력에 기존 JSON Schema 적용. 구조 오류가 있으면 의미 검사를 시작하지 않음.
- ID 중복·참조·터미널 종류·항차 시간창·변경 대상·확인자/확인시각 검사.
- 변경·시간창의 `confirmed_at > as_of`는 `CONFIRMATION_AFTER_SNAPSHOT`, `input_valid_until < as_of`는 `INPUT_EXPIRED_AT_SNAPSHOT`. 같으면 허용하며 서버 현재시각과 비교하지 않음.
- 모든 사실 묶음의 `evidence.received_at > as_of`는 `EVIDENCE_AFTER_SNAPSHOT`, `observed_at > received_at`는 `EVIDENCE_TIME_ORDER`. 당시 아직 받지 않은 자료나 역전된 관측·수신 시각을 계산에 넣지 않음. 관측시각 `null`과 미래의 계획 시각(`ready_at` 등)은 이 이유로 거절하지 않음.
- 원안 배정/미처리의 전체 작업 분할, 차량 내 순서 중복, 출발 작업 고정·이유·원안·복귀/가용 모순 검사.
- v0.1 공통 의미 규칙에 따라 관측·수신·확인 시각을 포함한 모든 입력 시각은 UTC `Z`와 분 경계를 요구. 원문의 초·소수초를 임의로 반올림하거나 시간대 없는 값·KST 문자열을 추정 변환하지 않음. 원본 시각의 정규화 근거는 수집·변환 단계에서 확보해야 함.
- 차량별 마지막 출발 작업의 복귀 위치와 확정 시작 위치가 다르면, 복귀 후 방향별 이동시간과 가용시각을 비교. 이동시간이 확보된 재이동은 허용하고, 복귀 전 위치 불일치·시간 부족·경로 누락은 차단.
- 준비·중량·처리·가용 미확인, 방향별 이동경로 누락을 검출. 출처와 자료 유형은 그대로 보존.
- 이동경로는 각 작업의 적재·복귀와 조정 작업의 후보 접근 구간을 보수적으로 요구. 차량 시작위치·모든 작업 복귀지에서 조정 작업의 상차지로 가는 구간이 없으면 입력을 보류. 같은 지점도 명시한 0분 경로가 필요.

## 예제로 확인할 동작

| 입력 | 이 모듈의 판정 |
|---|---|
| `01_snapshot.json` | 통과. J3 준비 지연·원안 마감 위반을 입력 오류로 오인하지 않음 |
| `jobs_template.csv` + 정상 문맥·출처 | 정상 Snapshot과 동일한 작업·타입·출처로 변환 |
| `07_snapshot_입력누락.json` | J1의 `ready_at`에 `INPUT_MISSING`, snapshot 없음 |
| `08_snapshot_미확인변경.json` | `WINDOW_UNCONFIRMED`, snapshot 없음 |

## 이번 PR의 한계와 다음 연결

검사 통과는 배차 실행 가능·최적성·승인 가능·실제 자료의 진실성을 보장하지 않습니다.
차량 중량/장비에 맞는 배정, 고정/미래 예약의 전체 일정 충돌, B0~B3 비교는 엔진과 독립 결과 검사기가 확인해야 합니다.
실제 서버 현재시각 기준 유효기간·입력/계획 최신성·승인 권한도 이 모듈의 판정이 아닙니다.

첫 구현은 오류 하나라도 있으면 전체 스냅샷을 보류합니다. 일부 작업만 계산하는 정책·정규화 해시·출처의 외부 진위 확인·실제 TMS 필드 대응·외부 수집기는 후속 작업입니다.
후보 접근 구간을 보수적으로 요구하므로 실제 자료의 희소 이동행렬은 엔진 담당과 적용 범위를 검토해야 합니다.

선효: PR #3은 누락/미확인 입력도 보관한 뒤 실행을 차단한다. 이 모듈을 등록 때 무조건 적용해 저장 정책을 바꾸지 말고, 실행 전 점검에 연결할 위치를 검토한다. `INPUT_MISSING`의 422, 미확인 근거의 503 등 기존 HTTP 구분은 API 담당이 유지한다. `valid`를 독립 일정 검사·승인 성공으로 사용하지 않는다.
대겸: 공통 예제 판정·필요 이동구간을 확인하고, 엔진 내부의 별도 입력 방어와 연결할 위치 검토.
길웅: 전달받은 오류의 파일명·행·필드·사유 표시.

## 로컬 명령으로 입력 준비

Python 코드를 별도로 쓰지 않고 정상 스냅샷·오류 보고서를 준비할 수 있습니다.
아래 명령은 저장소 루트에서 실행합니다. 출력 경로는 매번 새 이름을 지정합니다.

```sh
python -m backend.data validate-json "docs/development/v0.1/예제 데이터/01_snapshot.json" --output local/prepared-01.json --report local/report-01.json
python -m backend.data validate-json "docs/development/v0.1/예제 데이터/07_snapshot_입력누락.json" --report local/report-missing.json
python -m backend.data import-jobs "docs/development/v0.1/예제 데이터/jobs_template.csv" --context "docs/development/v0.1/예제 데이터/01_snapshot.json" --evidence local/jobs-evidence.json --output local/prepared-csv.json --report local/report-csv.json
```

`--evidence`는 API 키가 아니라 아래 형식의 **CSV 전체 자료 출처** JSON입니다.
이 예시는 기존 모의 CSV용이며 실제 자료에 그대로 복사하지 않습니다. 기존 입력의 시각을 CLI가 오늘 날짜로 바꾸지 않습니다.

```json
{
  "kind": "simulated",
  "source_ref": "fixture:scenario_001",
  "observed_at": null,
  "received_at": "2026-11-07T00:00:00Z"
}
```

- 출력은 입력 사본이며 실제 API 등록·계산·승인이나 외부 수집을 실행하지 않습니다.
- 표준 출력에는 항상 JSON 검사 보고서가 나옵니다. `--report`로 같은 내용을 파일에 저장할 수 있습니다. 원본 배차 내용은 보고서에 넣지 않습니다.
- `valid`, `input_sha256`, `issues`를 제공합니다. 해시는 UTF-8·키 정렬·공백 제거·`ensure_ascii=False` JSON 기준이므로 서버의 같은 직렬화 해시와 대조할 수 있습니다. 서버 등록이나 API의 해시 검증을 대신하지 않습니다.
- 종료코드 `0`은 입력 검사·요청한 저장 성공, `2`는 잘못된/미확인/읽기 불가 입력, `1`은 출력 경로·저장 실패입니다. 잘못된 명령 인자는 argparse가 별도 사용법과 코드 `2`를 반환합니다.
- 오류 입력이면 `--output`의 스냅샷을 만들지 않고 보고서만 저장합니다. 기존 파일·디렉터리·심볼릭 링크는 덮어쓰지 않습니다. `--output`과 `--report`는 입력 또는 서로 같은 경로를 쓸 수 없습니다.
- 스냅샷과 보고서 두 파일 저장은 하나의 트랜잭션이 아닙니다. 저장 도중 오류가 나면 코드 `1`과 표준 출력 오류를 확인하고, 남은 출력 파일을 정상 결과로 자동 채택하지 않습니다. 종료코드 `0`과 `valid=true`를 함께 확인해야 합니다.
- CSV 문맥 파일은 `jobs`가 교체되기 전 의미 검사를 하지 않습니다. 새 CSV로 기존 잘못된 작업을 고칠 수 있으며, 최종 결합 결과 전체는 검사합니다.
- CSV 작업 오류는 CSV 파일·행, 문맥 오류는 문맥 JSON 파일, 명시한 공통 출처 오류는 출처 JSON 파일에 연결합니다. `load_jobs_csv()`를 직접 호출할 때도 선택 인자 `context_source`, `evidence_source`로 파일명을 제공할 수 있습니다. 기존 호출 방식은 유지됩니다.
- 자료의 미래 수신·시간 역전은 입력 오류입니다. HTTP 코드는 데이터 모듈이 정하지 않으며, API 담당의 기존 실행 전 점검에서 처리합니다.
