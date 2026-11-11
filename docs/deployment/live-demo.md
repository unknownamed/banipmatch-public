# 통합 웹앱 시험 배포

2026-11-11 사용자가 전체 통합·배포·화면 시험을 요청했다. 대겸 책임 아래 이번 AI 보조 임시 HTTPS 배포를 허용한 범위이며 유료계약·상시 운영·실제 기사 연락까지 승인한 것은 아니다. 별도 계정이 없어 [Cloudflare Quick Tunnel](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)로 PC의 시연 서버를 연결했다. PC/프로세스 종료 시 접속이 끊기며 새 터널은 주소가 바뀔 수 있다. 운영 서비스의 가용성을 보장하지 않는다.

## 실행

Python3.12 환경에서 `pip install -r requirements-dev.txt -r backend/data/requirements.txt`. 실제 AIS 시험이 필요할 때만 `requirements-aisstream.txt`를 추가한다. 프론트는 Node24에서 다음과 같이 만든다.

```powershell
cd frontend
npm ci --ignore-scripts
$env:VITE_API_MODE='v2'
npm run build
cd ..
```

정적 결과용 `build:showcase`와 다르다. 프론트를 다시 빌드하면 정적 파일 허용 목록을 갱신하도록 **시연 서버도 재시작**한다. 실행 중인 디렉터리를 먼저 덮어쓰는 운영 배포는 피하고 상시 배포에서는 버전별 디렉터리로 전환해야 한다.

서버 설정 예시(실제 시험 주소로 대체, 키 값은 환경 출력/명령/공유 문서에 쓰지 않음):

```powershell
$env:BANIPMATCH_DEMO='1'
$env:BANIPMATCH_WORKFLOW='1'
$env:BANIPMATCH_PUBLIC='1'
$env:BANIPMATCH_RUN_MODE='engine'
$env:BANIPMATCH_PUBLIC_HOSTS='YOUR-HTTPS-HOST'
$env:BANIPMATCH_CORS_ORIGINS='https://YOUR-HTTPS-HOST'
$env:BANIPMATCH_WORKFLOW_DIR=(Join-Path (Get-Location) 'local/deployment/workflow')
$env:BANIPMATCH_REFERENCE_FILE=(Join-Path (Get-Location) 'local/live-reference/current.json')
python -m uvicorn backend.webapp:create --factory --host 127.0.0.1 --port 8877 --proxy-headers --forwarded-allow-ips 127.0.0.1 --workers 1 --no-access-log
```

HTTPS 중계는 공식 공급자 프로그램으로 `cloudflared tunnel --url http://127.0.0.1:8877 --no-autoupdate --protocol http2`. 중계가 준 호스트만 허용 목록에 넣는다. `0.0.0.0`, wildcard Host/Origin, 임의 프록시 신뢰로 바꾸지 않는다. Windows에서 백그라운드로 실행할 경우 `Start-Process -WindowStyle Hidden`을 쓰고 PID·시작시각·실행 파일·작업 디렉터리를 비공개 운영 기록에 남긴다. 종료 시 그 증거와 자식 프로세스를 확인해 본인이 시작한 것만 종료한다. 등록된 서비스/자동 시작은 만들지 않았다.

## 실제 자료

키는 `local/secrets/` 등 Git 제외 파일에 저장한다. 읽기 경로는 서버 설정만 사용하며 공개 화면에서 경로/URL/키를 지정할 수 없다.

```powershell
python -m tools.collect_live_reference --kma-key-file local/secrets/kma-api-key.txt --output local/live-reference/current.json --ais-report local/ais-live-probe.json
```

KMA 키나 AIS 시험 결과가 없으면 해당 인수를 생략한다. HJNC1회+KMA2회, 요청별15초·1MB·재시도 없음이다. 원문/키가 든 URL은 저장하지 않고 허용 필드만 기록한다. 자동 반복 호출은 없다. 방문자의 ‘수신 결과 새로 읽기’는 보관 결과만 읽는다. 키 이용자·약관/표시 허용 범위는 운영자가 확인한다. 개인 키를 번들·Git·이슈에 올리거나 무료 한도를 피하려고 여러 키를 돌리지 않는다.

## 동의한 기기 알림 시험

`python -m tools.workflow_admin generate-vapid --output local/secrets/vapid.pem`으로 한 번만 개인키를 생성하고, `BANIPMATCH_PUSH_ENABLED=1`, `BANIPMATCH_VAPID_PRIVATE_KEY_FILE`(절대경로), `BANIPMATCH_VAPID_SUBJECT=https://YOUR-HTTPS-HOST`를 설정한다. 키 파일을 덮어쓰면 기존 구독을 재사용할 수 있다고 가정하지 않는다.

일반 방문자는 계산만 할 수 있다. 대겸이 확인한 **팀원 시험 세션만** `tools.workflow_admin authorize-test-session` 명령으로 허가한다. 그 후 화면의 시험 수신자 연결에서 동의한 기기별 차량을 선택하고 초대를 만든다. 초대는30분·1회용이다. 사전 발행해서 GitHub에 남기지 말고 시험 직전에 개인 전달한다. 같은 브라우저에서 `/recipient`로 별도 수신자 쿠키를 사용한다.

- Android: Chrome에서 초대 수락 → 알림 허용 → 담당자가 변경 전달 → 잠금화면/앱 알림 확인 → 상세 열기 → 수행 가능 또는 곤란 응답.
- iPhone: iOS16.4 이상, Safari에서 홈 화면에 추가 → **홈 화면 앱에서** 초대 링크를 붙여넣고 수락 → 알림 허용. Safari에서 먼저 일회용 초대를 소진하지 않는다.
- 담당자는 중계망 접수, 열람, 명시 응답을 각각 확인한다. 중계망 접수만으로 휴대폰 도착 완료를 표시하지 않는다. 일반 방문자에게 발송 권한을 일괄 부여하지 않는다.

## 보존/제한

공개 경로는 빌드된 UI·정적 파일 허용 목록·기존 `/v2`만 제공한다. 키/원본/DB/저장소 및 `/v1`은 공개하지 않는다. 개인별 DB,24시간 세션, 입력·계산량·큐 제한은 그대로다. 운영 경로와 폰 초대 비밀을 보고서/제출ZIP에 넣지 않는다. 참고 자료 수신, 모의 배차 계산, 실제 연락 수신, 현장 운행 실증은 별도로 기록한다.
