# 담당자 대응 API v0.2 · #54/#55 연결안

v0.1 원본을 보존한 추가 계약임. 서버 구현과 로컬 검사를 제공하며 길웅의 관련자1회 검토는 PR61의 `558c782`에서 완료했다. 공개 배포/휴대폰 실수신 완료를 뜻하지 않음. 공통 Snapshot/RunRequest/ApprovalRequest/Results는 v0.1을 재사용함. [OpenAPI](openapi.json)·[합성 예제](examples.json)·[추가 DB](schema.sql)·[세션 레지스트리](registry.sql)·[서버 실행/운영 인계](../../../backend/workflow/README.md).

## 인증·수명

- `/v2/session`의 POST로 익명 모의 담당자 세션 생성, GET으로 복구. HttpOnly·SameSite=Strict 쿠키, 공개 모드에서 Secure. JSON에는 session_id/expires_at/csrf_token/limits/push_test_authorized와 plans의 최신 입력·실행·수정ID 반환. POST/DELETE에는 `X-CSRF-Token`과 명시한 `Origin` 필요(세션 생성은 Origin만). 모든 변경 요청은 `Idempotency-Key` 사용(세션 생성 제외).
- 방문자마다 독립 SQLite를 사용해 원본/결과/멱등 범위를 분리함. 같은 ID도 다른 세션의 자료에 접근하지 못함. TTL24시간, 만료7일 후 계산 종료를 확인하고 해당 세션 DB/인증 자료 삭제. 기존 v0.1 로컬 DB/토큰과 분리.
- 공개 방문자는 임의 푸시 대상/수신자를 만들 수 없음. 운영자가 동의한 팀원 시험 세션을 CLI로 허용한 경우에만 초대/전달 가능. 관리자 비밀은 프론트에 주지 않음.
- 수신자는 `/v2/recipient/session` POST에 초대 토큰을 **본문**으로 교환. 별도 HttpOnly 쿠키와 CSRF, 차량ID/수신자ID 분리. 초대30분·1회 사용, 수신자 권한은 담당자 세션 만료 이내. 토큰은 URL query/로그/분석에 넣지 않고 프론트 최초 링크의 fragment에서 읽고 지움.

## 담당자 경로

### 수신자 화면 연결 시 주의

- iPhone의 Safari와 홈화면 웹앱은 쿠키가 공유된다고 가정하지 않는다. 먼저 홈화면 설치를 안내하고 **홈화면에서 실행한 웹앱 안에서** 초대 토큰을 입력/수락하도록 한다. Safari에서 먼저 수락한 뒤 다른 멱등키로 다시 수락하면 `INVITATION_USED`다. 같은 초대 재시도에는 동일한 `Idempotency-Key`를 사용하며, 초대 토큰의 해시에서 키를 만들 수 있다. 원문 토큰을 로그/분석/URL query에 남기지 않는다.
- 프론트 개발 서버는 `/v2`를 같은 출처의 API로 연결한다. 실제 배포에서는 `/v2/*`를 백엔드에 전달하고 `/recipient`의 직접 방문·알림 클릭·새로고침은 프론트 `index.html`로 연결해야 한다. 임의 API 오류를 SPA HTML 성공 응답으로 바꾸지 않는다.
- 수신자 상세의 `is_current=false`, `payload=null`은 이전 계획이다. 새 운송 지시나 응답 가능한 화면으로 보여주지 않는다. 실제 Android/iPhone 검수는 위 연결 구현과 별도다.

| 경로 | 본문/응답 |
|---|---|
| GET `/v2/examples/default` | 시연 시각으로 이동한 명시적 모의 Snapshot |
| POST `/v2/scenarios` | Snapshot → 기존 RegisteredScenario. 최초 등록 이후 일반 조건 변경 금지. 승인 후에는 next-input의 동일 원안 재등록만 허용 |
| GET `/v2/scenarios/{id}` | 저장한 불변 Snapshot |
| POST `/v2/scenarios/{id}/revisions` | `{snapshot, reason, confirmation:"confirmed_simulation"|"assumed"}` → `{scenario_id, plan_id, base_plan_version, input_sha256, revision_id, confirmation}`. 서버가 새 scenario_id 부여. 원본 보존. 추가 차량/시각 수정은 엔진의 조건 검증 재사용 |
| GET `/v2/revisions/{id}` | 수정 이유·확인 구분·이전/새 입력 참조·검사 근거 |
| POST `/v2/runs` | 기존 RunRequest → 202 Run. 서버 예산/큐 검사 후 실제 계산 |
| GET `/v2/runs/{id}` / `/results` | 기존 Run/Results. 입력 부족·실행 실패 구분 |
| GET `/v2/revisions/{id}/comparison?before_run_id=…&after_run_id=…&method=B1` | 기존 대겸의 조건 보완 비교. 입력 부족의 이전 실행은 생략 가능 |
| GET `/v2/plans/{id}` | 현재 Plan |
| GET `/v2/plans/{id}/next-input` | 현재 승인 배정/미처리·버전을 보존한 다음 등록 원안. 추가 조건 수정은 이 원안 등록 후 revisions 사용 |
| POST `/v2/plans/{id}/approvals` | 기존 ApprovalRequest → 내부 Approval. 준비/가용 조건의 가정 또는 assumed 수정은 확정 불가. 외부 발송 완료로 바꾸지 않음 |
| GET `/v2/plans/{id}/dispatch-preview` | 현재 승인·독립검사·버전 재검사 후 차량별 changes/followups와 대상 연결 상태. 전달 이력과 분리 |
| POST `/v2/invitations` | `{plan_id,vehicle_ids:["T1"],consent_acknowledged:true}` → `{invitation_id,invitation_token,expires_at}`. 초대 생성만으로 알림 허용/실수신 완료가 아님 |
| GET `/v2/recipients` | 본인 세션의 수신자·차량 연결/구독 상태. endpoint/구독키 비노출 |
| POST `/v2/recipients/{id}/revoke` | `{}` → 해제 상태. 초대/구독·이후 응답 차단 |
| POST `/v2/plans/{id}/dispatches` | `{approval_id,expected_version,confirm_test_send:true}` → 202 `{dispatch_id,…}`. 같은 승인 중복 전송 방지. 변경 없는/위험 없는 차량은 임의 대상화하지 않음 |
| GET `/v2/dispatches/{id}` | 최신성·대상별 전달/사람 응답 상태·후속 확인 목록 |
| POST `/v2/notifications/{id}/retry` | `{confirm_test_send:true,recipient_id?:"…"}`. 확실한 실패/구독 해제 후 재연결만 명시적으로 재시도. unlinked는 현재 연결의 recipient_id를 명시. accepted/unknown은 재전송 차단. Retry-After 전에는429 |
| DELETE `/v2/session` | 자기 세션/수신자 접근 만료. 새 세션은 새 자료 범위 |

`confirmed_simulation`은 모의 배차에서 담당자가 확인한 조건이며 실제 현장 확인이 아님. 준비/가용 조건의 `assumed` 또는 가정 수정은 계산/비교만 하고 승인/전달은 차단. 기존 v0.1 모의 이동행렬의 가정 표시는 유지하며 이 자체로 모든 승인을 막지는 않음. 실제/혼합 계산 제한은 계속 유지함.

## 수신자 경로

| 경로 | 본문/응답 |
|---|---|
| POST `/v2/recipient/session` | `{invitation_token,accept_test_invitation:true}` → `{recipient_id,vehicle_ids,expires_at,csrf_token,subscription_status,data_mode}` 및 별도 쿠키 |
| GET/DELETE `/v2/recipient/session` | 권한 복구/해제 |
| GET `/v2/recipient/push-config` | `{configured,application_server_key}`. VAPID 공개키만 반환 |
| POST `/v2/recipient/subscription` | `{subscription:{endpoint,keys:{p256dh,auth},expirationTime:null},notification_permission:"granted",consent:true}` → 구독 상태만. 전화번호/기사명 불필요 |
| DELETE `/v2/recipient/subscription` | 구독 해제/민감값 제거 |
| GET `/v2/recipient/notifications` / `/{id}` | 내 대상/최신성·내 차량 변경/관련 미해결만. 재배정 상대의 상세 일정은 가림 |
| POST `/v2/recipient/notifications/{id}/opened` | `{}` → opened_at. 확인/수행 가능으로 자동 해석하지 않음 |
| POST `/v2/recipient/notifications/{id}/responses` | `{response:"acknowledged"|"can_perform"|"cannot_perform",note:""}` → 명시 응답. 최신 알림/계획만 허용, 응답 이력 보존 |

푸시 본문은 일반 문구+비밀이 아닌 알림ID·`/recipient` 경로만. 잠금 화면에 일정/차량/기사/항차를 넣지 않음. 상세 내용은 쿠키 권한 확인 후 조회. Service Worker/manifest/클릭/알림 권한·iPhone 홈화면 안내는 #55 담당.

## 상태·오류

전달: pending / sending / accepted(중계망 접수) / failed / unknown / expired / unsubscribed / unlinked / superseded. accepted_at·시도 이력·retry_not_before를 보존. 사람 상태는 별도 opened_at·response(none/acknowledged/can_perform/cannot_perform)·responded_at·response_history. 접수≠읽음≠확인≠수행 가능≠운송 완료. cannot_perform은 담당자 후속 확인이며 자동 재배차하지 않음. 이전 계획의 상세 payload는 null로 가리고 응답을 거절함.

기존 ApiError `{request_id,code,message,details}` 유지. 주요 코드: 401 SESSION_REQUIRED/RECIPIENT_REQUIRED,403 CSRF_FAILED/PUSH_TEST_NOT_AUTHORIZED,404 NOT_FOUND,409 PLAN_VERSION_CONFLICT/NOTIFICATION_SUPERSEDED/DELIVERY_UNCERTAIN/IDEMPOTENCY_CONFLICT,410 INVITATION_EXPIRED/SESSION_EXPIRED,422 CONDITION_REVISION_INVALID/ASSUMPTION_NOT_APPROVABLE/SUBSCRIPTION_INVALID,429 RATE_LIMITED/QUEUE_FULL,503 PUSH_NOT_CONFIGURED/INPUT_EXPIRED. 설정/권한 오류를 모의 성공으로 바꾸지 않음.

구현 상한: 본문256KiB·수신10초·HTTP동시16, 보관 세션100개·TTL24h, 작업20/차량10/위치32/경로1024, 방법4개·각10초, 대기 포함4실행·세션당1실행·시작 전 대기120초, 입력20/실행20/멱등 변경300회, 수신자3/초대10/전달10회, 알림별 응답20회·전송 시도3회, 네트워크 자식당12초. 성능/SLA 근거가 아닌 운영 보호용 보수적 선택이며 배포본에서 다시 검수.

## 길웅 연결 순서

세션/CSRF → 모의 입력 조회/등록 → 조건 편집·새 입력 → 실행/비교 → 기존 승인 → 대상 초대/연결 → 명시 전달 → 수신자 상세/응답 → 담당자 상태. 프론트는 토큰/초대/구독 비밀을 storage·로그에 넣지 않음. 구독은 지원/허용 여부를 직접 확인하고, 실제 기기 실수신·왕복은 대겸 HTTPS 배포 이후 별도로 기록해야 함.
