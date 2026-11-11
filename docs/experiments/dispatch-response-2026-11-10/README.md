# 대응 안내 로직 실행 예제

공통 예제의 **모의 자료를 B1 코드로 실제 계산하고 독립 일정을 검사**한 결과다. 과거 예제 시각을 유지했으며 현재 운영 계획이나 사람의 승인·외부 발송을 실행한 자료가 아니다. `manifest.json`에 입력/도구/산출물 SHA-256과 실행 조건을 남겼다. 기존 동결80회와 별도다.

| 작업 | 계산 결과에서 확인한 것 | 담당자에게 보여줄 대응 |
|---|---|---|
| J0 | 고정 배정 유지 | 변경 지시 목록에서 제외. 위험이 생기면 원래 issue를 별도로 표시 |
| J1, J2 | 원안과 다른 차량으로 재배정 | 이전/신규 차량 양쪽에 이전·신규 일정과 바뀐 필드 표시. 실제 기사 매핑은 별도 |
| J3 | `READY_TOO_LATE`로 미처리 | 준비 완료 시각을 화주/상차지 담당자에게 확인. 확인된 조건으로 새 입력 재계산. 실제 운송 취소나 준비 앞당김 가능을 단정하지 않음 |

`computed-result.json`은 실계산 단일 MethodResult이고 `response-preview.json`은 화면/API 인계용 대응 명세다. 외부 전송 권한은 항상 false다. 실제 통보 완료로 집계하지 않는다.

저장소 루트에서 기존 의존성 환경으로 재생:

```powershell
python -m tools.dispatch_response --snapshot "docs/development/v0.1/예제 데이터/01_snapshot.json" --result docs/experiments/dispatch-response-2026-11-10/computed-result.json --output local/response-check.json
```

`local` 디렉터리가 먼저 있어야 하며 출력 파일을 덮어쓰지 않는다. 생산 화면·API 연결·실휴대폰 수신/응답은 #54~#57에 남아 있다.
