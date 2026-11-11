# 담당자 대응 검수 자료 · 민준 #56

기준 main `e18b77f`, 2026-11-11. 모든 입력·수신자·상황은 **명시적 합성/모의**다. 실제 항차·기상 조회는 기존 검증 문서대로 별도 유지한다. 실제 배차표·기사·차량 확보·터미널 예약 변경·휴대폰 수신의 증거가 아니다.

## 실행

```powershell
python -m tools.response_acceptance --check
python -m pytest tests/data/test_response_acceptance.py -q
python -m tools.response_acceptance --directory local/response-acceptance-new
```

기존 개발 가상환경에서 실행한다. 생성은 새 폴더만 허용한다. 실패하면 일부 파일이 남을 수 있으므로 성공 종료와 valid를 확인한다. `manifest.json`은 입력·기록 결과·전달 기대 자료의 SHA-256을 고정한다. `--check`는 해시를 검사하고 현재 B1·입력검사·독립 일정검사·변경 명세·조건 비교를 다시 실행한다. 계산시간은 매 실행 달라질 수 있어 결과의 바이트 동일이나 성능 향상을 요구하지 않는다. 원본 v0.1·동결 80회·공백 9사례·공급자 21종은 덮어쓰지 않았다.

## 계산/설명 9사례

| 파일 (`cases/`) | 입력과 기대 결과 |
|---|---|
| sequence-resolves | 기존 예제에서 늦은 J3를 제외한 별도 합성 입력. 순서/시각 조정 후 미처리·가동 작업 위반 0. 전체 현장 문제 해결 주장이 아님 |
| ready-too-late | J3 준비 06:00Z, READY_TOO_LATE와 담당자 확인 안내. 준비를 임의로 당기거나 예외 반입을 가정하지 않음 |
| equipment-shortage | 모의 차량의 DRY40 장비 없음. 적합 차량 부족, 출발 J0 보존. 한계는 입력 조건의 장비 검사 |
| fixed-risk | 기존 출발 위험 예제의 별도 복사. FIXED_RESIDUAL_RISK와 고정 배정 유지 |
| missing-ready / unconfirmed-window | INPUT_INCOMPLETE / WINDOW_UNCONFIRMED. 계산 성공·미처리 0건을 만들지 않음 |
| search-limit | **모의 monotonic 시계 주입**으로 10초 예산 만료를 강제한 오류 검수. 실제 경과시간/서버 성능 시험 아님. SEARCH_LIMIT·not_proven, 고정 보존, 불가능 단정 금지 |
| unchanged-vehicles | 계산 일정과 같은 합성 원안을 구성한 무변경 사례. 전달 대상 없음 |
| reassigned-both-vehicles | J1의 모의 원안 차량을 다르게 구성. 이전/새 차량 모두 명세 포함 |

`results/`에는 실행한 결과와 preview를 보존했다. `proof_level`·`evidence_refs`가 확인 안내에서 유지되는지 검사한다. 독립 일정검사 후 결과의 `approval_eligible=true`는 **로컬 계산 적격 표시**이며 서버의 가정 조건 승인·대상자 권한을 대신하지 않는다. 모든 preview/comparison의 `delivery_authorized=false`와 `external_actions_performed=false`를 유지한다. 원안 배정→미처리는 실제 운송 취소가 아니다.

## 조건 보완 4쌍

`pairs/`의 before/after 입력과 `results/`의 전후 실행·비교를 따로 보존한다. 같은 계획/반입시간/정책/고정 배정을 유지하고, 변경 사유·근거와 입력 해시를 남긴다. **전부 confirmation=assumed, actual_condition_confirmed=false**다. 모의 준비시각/차량 확보를 현장 사실로 쓰지 않는다. 서버 계약의 `confirmed_simulation`도 실제 현장 확인과는 다르다.

| 쌍 | 기대 결과 |
|---|---|
| ready-only | J3 준비만 앞당겨도 J3 미처리가 남음. 보완=해결 보장 아님 |
| extra-vehicle | 준비 보완+완비된 합성 T3 추가 시 J3 배정. 처리 작업 집합이 달라 효율 개선율 보류. 실제 추가 차량 모집 아님 |
| missing-repaired | 이전 ready_at 누락으로 계산 차단. 보완 후 계산하되 이전 결과·차이 수치를 0으로 꾸미지 않음 |
| later-ready | J2 준비 지연을 함께 반영해 새 미처리 J2가 생김. 기존 미처리와 새 미처리 구분 |

## 전달/응답 15사례와 연결

[delivery-cases.json](delivery-cases.json)은 **API 응답 캡처가 아닌 입력 상황·기대 상태의 합성 검수표**다. 생성 원본은 `tools/fixtures/response-delivery-cases.json`. PR61 head `558c7828ce8596c0cea640e10a2faee59b549920`의 계약안을 참고했으며 아직 main 구현/길웅과 합의 완료로 취급하지 않는다.

권한 거절·초대 만료·미연결·이전 계획·중복·실패·불명·접수 후 미열람·열기만 함·확인·곤란·가능·구독 만료·다른 수신자·가정 조건 승인 차단을 포함한다. 각 expected는 검사할 **일부 필드/상황 조건**이며 그대로 HTTP 응답 전체로 반환할 계약이 아니다. 예를 들어 이전 계획의 상세 GET과 응답 POST는 서로 다른 요청이다. 화면 상태와 서버 오류 코드를 합쳐 가짜 API로 구현하지 않는다.

선효는 API/DB·권한/중복/만료/오류를, 길웅은 해당 입력 순서의 표시와 명시 응답을 대조한다. 푸시 접수≠휴대폰 도착≠열람≠확인≠수행 가능≠운송 완료다. 거절·불명·무응답·곤란은 후속 확인 대상이며 자동 재배차/재전송을 만들지 않는다. 차량 ID와 수신자 ID는 별개다. 초대 토큰·구독 endpoint/키·개인 연락처를 예제나 보고서에 넣지 않는다.

최종 HTTPS/휴대폰 검수는 대겸 배포 후 동의한 팀원 기기로 수행한다. 단말·OS/브라우저·배포 SHA/URL·계획/입력 버전·동의·휴대폰 표시·명시 응답·담당자 반영을 같은 왕복으로 기록한다. Android Chrome/iPhone 홈화면·미지원/거절은 각각 검사하고 미실행은 미검증으로 남긴다. 현재 이 묶음은 네트워크 0회이며 실제 푸시 성공 기록이 아니다.

## PR61의 로컬 대조와 재현

[workflow-check.json](workflow-check.json)은 PR61 head `558c7828ce8596c0cea640e10a2faee59b549920`의 68개 기존 API/푸시/계약 검사와 별도로, 이 검수표 중 9종을 주입 전송 API에 넣어 비교한 기록이다. accepted-unread·duplicate-send·opened-only·acknowledged·can-perform·cannot-perform·failed·unknown·unlinked를 확인했다. 나머지 예제는 기존 회귀 또는 화면/수동 수용검수로 구분하며 15종 전체를 실제 기기로 시험했다고 주장하지 않는다.

재현할 때 변경을 보존한 별도 검토 브랜치에서 PR61 소스와 `requirements-workflow.txt` 의존성을 준비한다. 이 문서 폴더를 먼저 Git 제외된 `local/response-workflow-repro`에 복사해 보존한 다음, 저장소 루트에서 `python local/response-workflow-repro/workflow-check.py`를 실행한다. 스크립트는 PR61의 테스트 helper와 일회성 임시 DB/TestClient·가짜 전송기를 사용하며 JSON 요약만 출력한다. 서버 프로세스·휴대폰 전송·공개 게시를 실행하지 않는다. PR61의 helper가 바뀌면 현재 head에서 다시 대조해야 하며 다른 head의 성공을 재사용하지 않는다.
