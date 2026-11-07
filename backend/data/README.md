# 데이터 입력 모듈 · 첫 구현

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
- 원안 배정/미처리의 전체 작업 분할, 차량 내 순서 중복, 출발 작업 고정·이유·원안·복귀/가용 모순 검사.
- 계산 시각은 UTC `Z`와 분 경계를 요구. 시간대 없는 값·KST 문자열을 추정 변환하거나 초를 반올림하지 않음. 출처 관측·수신·확인 메타데이터 시각에는 분 경계를 강제하지 않음.
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
