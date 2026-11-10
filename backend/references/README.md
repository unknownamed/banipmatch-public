# 실제 자료 읽기 준비 · #31

허용된 로컬 HJNC/도로공사 표본을 읽는 내부 Python 모듈임. 외부 API 호출·수집 예약·DB 저장·Snapshot 생성은 없음. 실제 자료를 계산 입력으로 채택하는 기능과 구분함.

## 실행

프로젝트 루트에서 실행. 예시의 파일·수신시각·권한 근거는 인계받은 값으로 지정해야 함. 수신시각은 가져오기 실행 시각으로 새로 만들지 않음.

```powershell
python -m backend.references --source hjnc --kind reference --input local/hjnc-authorized.json --received-at 2026-11-09T12:51:14Z --sample-permission-ref local/hjnc-read-permission.md
python -m backend.references --source road --kind reference --input local/road-authorized.json --received-at 2026-11-09T12:00:00Z --sample-permission-ref local/road-read-permission.md --start 101 --end 102
```

위 파일은 제공된 예제가 아니라 사용자가 준비할 경로임. 키 인수나 환경변수는 사용하지 않음. `--kind simulated`는 합성 응답을 직접 선택할 때만 사용. CLI는 최대1MB를 읽고 원본을 덮어쓰지 않으며 식별자·행 값 없이 메타데이터만 출력함. 종료코드0은 읽기/검사 수행,2는 인수·파일·응답 실패임. 코드0이어도 partial/stale/계산 차단일 수 있음.

## 내부 사용 예

아래는 실제 응답이 아닌 합성 사례임. 네트워크나 서버 없이 캐시 실패 전이를 재현함.

```python
from datetime import datetime, timezone
import json
from backend.references import CachePolicy, ReferenceReader, SampleResponse

now = datetime(2026, 11, 10, 1, 0, 10, tzinfo=timezone.utc)
reader = ReferenceReader(
    "hjnc", kind="simulated", sample_permission_ref="synthetic-example",
    policy=CachePolicy(300, 600, "synthetic-example-only"), clock=lambda: now,
)
raw = json.dumps({"stringContent": json.dumps([{
    "VOY_NO": "SYNTHETIC-VOYAGE", "YARD_OPEN": "2026-11-10 00:00",
    "YARD_CLOSE": "2026-11-13 01:00", "ETB": "2026-11-13 11:00",
}]), "totalElements": 1, "hasNext": False}).encode()
received = reader.ingest(SampleResponse(raw, "2026-11-10T01:00:00Z"))
failed = reader.refresh(lambda: SampleResponse(b"", "2026-11-10T01:00:01Z", 503))
assert failed["last_attempt"]["status"] == "failed"
assert failed["cached"]["received_at"] == "2026-11-10T01:00:00Z"
assert failed["approval_eligible"] is False
```

`current.items`는 해당 ingest 호출에서 읽은 정제 표본, `cached`는 별도 허용된 이전 표본임. 실패 시 current를 채우지 않음. 최신 실패 표시를 캐시의 정상 표시로 덮지 않아야 함. 재호출한 `view()`는 새 표본이 아니므로 current가 null임.

## 상태와 보존

| 값 | 의미 |
|---|---|
| `received` | 구조상 읽을 수 있는 행. 실제 전체 범위·업무 의미가 검증됐다는 뜻은 아님 |
| `empty` | 정상 응답의0행. 이전 행을 현재 결과로 재사용하지 않음 |
| `partial` | 필수 필드/방향/품질 누락 또는 수신 행과 총건수/페이지 불일치. 유효한 행만 참고로 반환 |
| `failed` | HTTP·공급자 오류·파싱/수신시각 오류·통신 실패. 정상 빈 결과와 구분 |
| `fresh/stale` | 원래 수신시각 기준 표시용 나이. 업무 사건 발생시각/공급자 갱신 주기가 아님 |

- `last_attempt`는 최근 시도 상태/시각/횟수, `last_success`는 최근 해석 성공의 수신시각/상태/행 수만 보존함. 부분 응답도 해석 성공이며 완전한 자료 확보와 다름.
- 메모리 캐시는 기본 비활성. 별도 `permission_ref`와 양수 `retain_for_seconds`를 지정한 경우만 정제 표본을 보관함. 권한 근거 문자열을 넘겼다는 이유만으로 이용 허가를 검증했다고 주장하지 않음. 현재 실제 제공사 캐시를 활성화한 설정은 없음.
- 표시 신선도 기본300초는 구현 선택임. 공급자 갱신 주기를 추정한 값이 아님. 신선도/보존 기간은0~31일로 제한하며 실제 허용 기간이 더 짧으면 그 조건을 적용해야 함.
- 정상 빈 응답은 이전 캐시를 비움. 부분 응답·실패는 기존 캐시를 교체하지 않음. 원래 수신시각+보존 기간에 도달하면 읽기/갱신 때 제거함. 백그라운드 삭제 스레드는 없으므로 실제 이용 조건이 벽시계 기준 강제 삭제를 요구하면 캐시를 켜지 않음.
- 기본1회, 설정 시 최대3회. timeout/connection/429/500/502/503/504만 제한 재시도하며 간격은 최대1초. HTTP401/403, 본문ERROR, 잘못된/빈/부분 응답은 재시도하지 않음. 실제 네트워크 loader는 제공하지 않으며 향후 연결 시 요청별 timeout/쿼터/Retry-After 정책을 따로 적용해야 함.
- 원문·공급자 오류 메시지·요청 URL은 보존/출력하지 않음. 같은/이전 수신시각의 재적재, 미래 수신시각, 역행하는 검사 시계를 거부함. 반환값을 수정해도 내부 캐시는 바뀌지 않음.
- 동기 단일 소유 객체임. 여러 요청이 공유하는 서버 저장소로 사용하지 않음. 공개 REST 경로·웹 화면 연결은 이번 범위에 없음.

## 매핑 경계

HJNC는 기존 `audit_hjnc`, 도로공사는 `audit_response`를 재사용함. 허용 목록의 값만 반환하며 필드별 source/kind/received_at을 각 항목에 붙임. 실제 관측시각이 불명확하므로 observed_at은 null임. 외부 자료는 `reference`, 직접 만든 표본은 `simulated`로 구분함.

- HJNC `VOY_NO/YARD_OPEN/YARD_CLOSE/ETB`의 문자열을 보존. 시간대를 추정해 UTC로 바꾸지 않음. hasNext=false와 행 수 일치도 전체 범위 검증으로 승격하지 않음. 단일 표본·ETB 변동을 확정 반입 변경으로 만들지 않음. 전후 비교는 기존 `tools/compare_hjnc_observations.py`를 사용.
- 도로공사는 명시한 영업소 방향과 필수 필드·숫자·최소≤평균≤최대·날짜·분 단위 시간 표기를 검사. 집계 코드가 비거나 시간 표기가 불명확하면 제외. `timeAvg`의 단위를 추정하거나 영업소 구간을 전체 화물차 이동시간으로 바꾸지 않음.
- 카카오 길찾기·ORS·AIS·기상은 어댑터 미제공. 카카오 응답을 저장하는 경로를 만들지 않음. ORS 수치/경로선, AIS 위치, 기상 값은 각 이용 조건·표본·업무 의미 확인 뒤 별도 검토.

모든 결과는 `engine_conversion=blocked`, `approval_eligible=false`임. `storage_checks`의 `422 DEMO_DATA_ONLY`, 실행 전 입력 검사, 독립 일정 검증, 입력/계획 버전 재확인은 그대로 유지함.

```powershell
python -m pytest tests/test_reference_reads.py tests/data/test_hjnc_observations.py tests/data/test_road_response.py -q
```
