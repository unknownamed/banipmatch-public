# v0.2 담당자 대응 서버 · #54

새 조건→실계산/비교→내부 확정→시험 수신자 연결→별도 Web Push→명시 응답의 서버 구현임. 기존 v0.1 데이터/엔진·일정 독립검사·승인 저장을 재사용함. **#55 화면/SW 연결·관련자 검토·대겸 HTTPS 배포·실휴대폰 왕복은 미완료**이므로 #54 전체를 완료 처리하지 않음. 직접 계산 공개 보호 F08도 이 세션 경계에 포함함.

## 로컬 준비

기존 개발 환경은 `requirements-dev.txt`, 운영 의존성은 `requirements.txt`+`backend/engine/requirements.txt`+`requirements-workflow.txt`임. Python3.12 이상. 기존 로컬 API를 쓰는 경우 새 설정을 켜지 않아도 됨.

```powershell
python -m pip install -r requirements-dev.txt
$env:BANIPMATCH_DEMO = '1'
$env:BANIPMATCH_DEMO_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:BANIPMATCH_RUN_MODE = 'engine'
$env:BANIPMATCH_WORKFLOW = '1'
python -m backend
```

위는 재현용 실행법이며 실제 서버 실행/배포는 대겸 담당. API 문서는 loopback `/docs`, 계약은 [v0.2 OpenAPI](../../docs/development/v0.2/openapi.json), [합성 예제](../../docs/development/v0.2/examples.json), [연결 순서](../../docs/development/v0.2/README.md)에 있음. 이 작업에서는 공개 주소를 만들거나 실제 푸시를 보내지 않았음.

기본 푸시는 비활성임. UI는 세션 쿠키와 CSRF를 사용하고 서버의 DEMO_TOKEN을 받지 않음. `/v2/examples/default`는 명시적인 모의 예제만 현재 시연 기준으로 이동하며 실제 자료 시각을 바꾸지 않음. 실제/혼합 입력과 준비·가용 조건의 가정 확정은 계속 차단함. v0.1의 공개된 모의 이동행렬 가정 자체는 보존함.

## 대겸이 HTTPS 환경에서 준비할 것

1. `BANIPMATCH_PUBLIC=1`, `BANIPMATCH_WORKFLOW=1`, `BANIPMATCH_RUN_MODE=engine`, `BANIPMATCH_DEMO=1`과 실제 `PUBLIC_HOSTS`/HTTPS `CORS_ORIGINS` 설정. PUBLIC_HOSTS는 호스트명만, wildcard 금지. 동일 출처의 프론트와 `/v2` reverse proxy 구성을 권장함. 공개 모드는 v0.1 경로를 닫고 기존 로컬 DB도 열지 않음.
2. 서버는 단일 프로세스/worker1, workflow 디렉터리는 영속 저장. 프록시의 HTTPS/client 전달은 실제 신뢰하는 프록시 IP만 허용. 신뢰 헤더를 모든 주소에 열지 않음. 실행 진입점은 access log를 끄며 별도 실행/프록시에서도 body·cookie·구독·초대 query를 기록하지 않도록 설정해야 함.
3. 다음 명령으로 **새 파일**에 VAPID 생성. 출력은 공개키뿐이며 기존 파일을 덮지 않음. 키 파일은 서버 사용자만 읽게 보관. `VAPID_PRIVATE_KEY_FILE`은 경로, `VAPID_SUBJECT`는 본인 연락 mailto 또는 경로/포트 없는 HTTPS origin, `PUSH_ENABLED=1` 설정. 생성·설정만으로 휴대폰 수신 완료가 아님.

```powershell
python -m tools.workflow_admin generate-vapid --output local/workflow-vapid.pem
```

4. 동의한 팀원이 담당자 시연 세션을 만든 뒤, 운영자가 그 **session_id만** 확인해 허용함. 관리자 인증 자료를 브라우저로 넘기는 경로는 없음. 다음 명령은 전송하지 않으며, 공개 방문자는 API로 이 권한을 얻을 수 없음.

```powershell
python -m tools.workflow_admin authorize-test-session --workflow-dir local/workflow --session-id <시연세션ID> --consent-note "팀원 모의 배차·기기 시험 동의 확인" --consent-confirmed
```

5. 담당자는 차량 범위를 지정해 초대, 수신자는 초대 수락과 브라우저 알림 허용/구독을 별도로 수행. 초대 비밀은 URL fragment에서 읽어 즉시 지우고 본문으로 교환. 수신자 이름/전화번호는 수집하지 않음. 기존 차량 연결을 다른 수신자로 자동 넘기지 않으며 해제 후 새 초대를 사용함.
6. 최신 독립 검사·내부 확정 명세를 보고 명시적으로 전달. HTTPS 배포본에서 Android Chrome, iPhone 지원 OS/홈화면 PWA의 실제 알림→상세→확인/가능/곤란→담당자 화면을 검수. UI/SW/manifest·기기별 조건은 길웅 #55와 연결. 미지원/거절·만료·오프라인/실패를 성공으로 쓰지 않음.

연결된 시험은 세션에서만 가능하며 일반 공개 사용자가 타인의 대상/번호로 보내는 기능이 아님. 전화·채팅·SMS업체·Firebase 계정·유료 계약을 추가하지 않음.

## 보호와 실패 처리

- 담당자/수신자 쿠키는 별도 HttpOnly·SameSite Strict, 공개 모드 Secure. Origin·CSRF·역할/객체 범위 검사를 수행. 차량ID와 수신자ID는 별개이며 재배정 상대의 상세 일정은 수신자 응답에서 가림.
- 최초 입력 이후 조건은 수정 이유·전후 근거·새 입력을 같은 트랜잭션으로 저장. 확정 후 `/plans/{id}/next-input`을 받아 등록하면 현재 승인 배정/미처리를 새 원안으로 보존. 일반 등록으로 고정·마감·정책을 바꿀 수 없음. 가정 조건은 승인/전달 차단. 전달 후 입력/계획이 바뀌면 이전 상세는 가리고 응답을 거부함.
- 수신 endpoint는 지원 HTTPS 중계망(Google/Mozilla/Apple)만 허용. 구독키 형식/P-256 검사. 전송 자식에서 DNS의 공인주소만 선택하고 연결 IP를 고정하되 원래 hostname으로 TLS 인증. redirect/proxy/임의 URL 호출 없음. 자식 전체12초, 연결5초, 응답 원문/URL/키/예외 문자열은 반환하지 않음. 429 Retry-After는 재시도 허용 시각으로 보존.
- 전송 시도 전에 sending을 기록. accepted는 중계망 접수만, opened/acknowledged/can_perform/cannot_perform은 별도. 타임아웃/5xx/중단의 불명은 자동 재전송하지 않음. 확실한 실패·재연결만 명시적 재시도, 총3시도 제한. 만료 구독은 민감값 제거. 교체 중 옛 구독의 늦은410이 새 구독을 지우지 않음.
- 구독은 서버 보호키로 암호화, 인증 자료는 서버 파일과 HttpOnly 쿠키에만 보존. 초대 비밀은 HMAC으로 재구성하고 DB에는 원문을 남기지 않음. endpoint 소유 예약은 실제 현재 구독만 유지. 보호키 없는 기존 세션은 새 키로 덮어 복구한 척하지 않고 기동을 차단함.
- 미처리·고정 위험은 관리자 후속 안내와 대상 차량 명세에 유지. 곤란 응답은 후속 확인이며 자동 재배차/운송 취소/예약 변경이 아님. 수신자 응답 이유/변경 이력은 계획·알림에 묶어 보존.

## 자원·수명·복구

상한은 배포 성능 보장이 아닌 보수적 설계 선택임. 본문256KiB/수신10초·HTTP 동시16, 입력 작업20/차량10/위치32/경로1024, 방법4개·방법별 예산10초(+기존 시작 여유5초), 글로벌 계산 대기 포함4·세션당1, 시작 전 큐 대기120초 상한. 단일 계산 worker를 재사용하며 종료 시 시작 전 작업 취소와 자식 timeout을 유지함.

세션 보관100개·TTL24h, 입력20개/계산20회/멱등 변경300회, 수신자3/초대10/전달10·알림별 사람 응답20회. 신규 세션 IP별5회/분, 역할별 조회/변경·재시도 요청량도 제한. 보관 상한에는 만료 후 남은 세션도 포함되므로 공개 부하/저장 용량·적정 수치는 대겸 환경에서 추가 검수해야 함. 기존20/50작업 엔진 기록을 공개 API SLA로 주장하지 않음.

`workflow/registry.sqlite3`(registry1)와 세션별 `sessions/<id>.sqlite3`(v0.1+추가2) 사용. 기존 로컬 demo DB/배포 v0.1 SQL은 변경하지 않음. 세션 생성 중 중단된 파일은 권한을 발급하지 않고 정리. 만료/해제는 즉시 접근 거절, 정리 작업은60초마다 구독 비밀/연결 해제. 정상 만료7일 뒤 내 계산/전송이 끝난 DB 파일만 절대 경로를 검사해 제거함. 다른 파일/기존 로컬 DB를 삭제하지 않음.

재시작 때 queued/running 계산은 실패, 시작 전 전달은 확정 미발송 실패, sending은 불명으로 복구. 자동 재발송하지 않음. 쿠키·입력/승인·사람 응답 이력은 TTL 안에 복구하며 `/v2/session`의 plans/latest_run_id/latest_revision_id로 재진입 가능.

운영 백업/복구는 **대겸이 서버를 중지한 뒤 workflow 디렉터리 전체와 원래 secrets.key·VAPID 파일을 비공개로 함께 보존/복구**하는 방식부터 사용. 키·DB·WAL의 일부만 다른 버전으로 섞거나 Git/제출 ZIP에 넣지 않음. 정상 재시작/보관 로직은 검사했으나 실제 서버 백업/rollback 운영은 대겸 환경에서 검수해야 함. `/health`는 기본/정리 실패 플래그만 반환하며 비밀값/파일 경로를 공개하지 않음.

## 검사 재현

```powershell
python -m pytest tests/test_workflow_api.py tests/test_workflow_push.py tests/test_workflow_contract.py -q
python -m pytest tests/test_workflow_acceptance.py -q
python -m pytest -q
python tools/check_development.py
```

실제 B1 계산을 사용한 서버 왕복과 가짜 DNS/HTTP를 사용한 실제 암호화/VAPID 검사임. 전화/푸시 실기기 수신 시험과 구분. [담당 인계](../../docs/team/handoffs/2026-11-11-he6venly-dispatch-response.md)의 실행 결과·남은 조건을 확인.

`test_workflow_acceptance.py`는 민준 #56의 보완 전후 4쌍을 v0.2의 실제 입력 등록·수정·B1 계산·비교·승인 경로로 검사한다. 원래 누락 입력은 0건 성공으로 바꾸지 않고, 준비시각 보완 뒤에도 남는 미처리와 조건 악화도 확인한다. 가정 시험의 승인 거절, 확인된 **모의** 조건의 변경 명세와 승인 후 다음 입력, 타 세션·잘못 연결한 결과 차단을 함께 대조한다. 외부 전송은 없으며 원본 fixture/동결 실험을 바꾸지 않는다.
