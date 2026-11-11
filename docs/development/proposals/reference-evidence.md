# #31 읽기 모델과 후속 계약 검토안

상태: 내부 읽기 모델 구현, 공통 계약 변경은 미적용. v0.1 원본·API·DB를 수정하지 않음.

## 확인한 v0.1 표현 범위

`contracts.schema.json`의 Evidence는 `kind/source_ref/observed_at/received_at`이고 추가 속성을 허용하지 않음. Window/TravelTime/Vehicle/Job/Location/Change별 Evidence와 Snapshot.data_mode의 simulated/observed/mixed로 **객체별** 출처를 나눌 수 있음. reference를 새 kind로 기존 Evidence에 추가하면 계약 위반임.

한 Job의 실제 중량과 모의 ready_at, 한 Location의 실제 좌표와 가정 이름처럼 **한 객체 안의 필드별** 근거는 단일 Evidence만으로 분리할 수 없음. 수집 시도의 실패/이전 성공/보존 기간도 불변 입력의 근거와 의미가 다름. 현재 수신 자료의 시간대·단위가 미확인이라 Window/TravelTime으로 즉시 정규화할 수도 없음.

## 이번 구현 선택

공통 객체에 임의 필드를 붙이지 않고 `backend.references`에 별도 내부 미리보기 모델을 둠. `reference-read-preview-1`은 배포 API/schema_version이 아님. `current.items[].provenance.kind=reference/simulated`도 기존 Evidence.kind가 아니며 Snapshot에 그대로 복사할 수 없음. 원본 응답의 허용 필드만 투영하고 API·DB·엔진으로 전달하지 않음.

예시(합성):

```json
{
  "values": {"VOY_NO": "SYNTHETIC-VOYAGE", "YARD_OPEN": "2026-11-10 00:00", "YARD_CLOSE": "2026-11-13 01:00", "ETB": "2026-11-13 11:00"},
  "provenance": {"kind": "simulated", "source_ref": "https://www.hjnc.co.kr/esvc/vessel/berthScheduleT", "observed_at": null, "received_at": "2026-11-10T01:00:00Z"}
}
```

이 모델의 provenance는 보존한 필드 전체가 같은 표본/수신시각에서 왔다는 뜻임. reference는 자료 활용 수준이며 진위·현행성·현장 사용 가능 판정이 아님. 모의 전환은 객체 생성 시 명시 선택하고 실패 경로에는 없음. 서비스 시험에서 이 예시의 필드 대응·근거/캐시 분리·계산 차단을 검사함.

## 관련자 검토가 필요한 후속 규격 제안

필드가 섞인 입력을 실제로 만들 때 새 버전에서 다음을 함께 검토해야 함. 아직 합의·구현된 계약이 아님.

- 불변 입력의 필드 JSON Pointer별 근거 목록을 별도 sidecar로 연결하는 방식. 기존 객체별 Evidence는 기본 근거로 유지하고 특정 필드만 override하는지 합의 필요.
- 근거의 사실성(observed/assumed/simulated 등)과 제품 사용 수준(reference/calculation)을 별개로 표현하는 방식. reference를 observed의 동의어로 취급하지 않음.
- source별 수신/마지막 성공/실패/캐시 신선도를 입력의 Evidence가 아닌 별도 조회 상태로 노출하는 방식. 실패 응답과 캐시 자료가 함께 있을 때 화면 표시 규칙 포함.
- observed_at 불명확, 부분 범위, 미확인 시간대/단위, 구식 자료의 실행·승인 적격성. mixed 저장을 허용하기 전에 저장·입력 의미·독립 일정 검사·버전 검사·내부 승인까지 함께 검증.

민준(표본·시간/단위·필드별 근거)과 먼저 매핑을 검토하고, 화면/API 계약으로 연결할 때 영향받는 담당자에게1회 검토 요청. 미확정 계약을 이번 코드에 먼저 적용하지 않음.
