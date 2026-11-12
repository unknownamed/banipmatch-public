# 운영 서버 배포 (2026-11-13 기준)

운영 주소: **https://banipmatch.duckdns.org**

접속 계정·서버 IP·SSH 키·API 키·알림 사용 코드·VAPID 개인키는 이 문서와 저장소에 넣지 않는다. 실제 값은 서버의 `/etc/banipmatch/` 아래 비밀 파일(소유자 root, 그룹 banipmatch, 권한 640)에만 둔다.

## 구성

| 계층 | 구성 | 설정 파일(저장소 예시) |
|---|---|---|
| 서버 | AWS Lightsail 서울 리전, Ubuntu, 메모리 2GB·디스크 60GB, 스왑 1GB | — |
| HTTPS | Caddy 리버스 프록시, Let's Encrypt 인증서 자동 발급·갱신 | `deployment/cloud/Caddyfile.example` |
| 앱 | `uvicorn backend.webapp:create --factory`(127.0.0.1:8877, 워커 1) | `deployment/cloud/banipmatch.service` |
| 실행 계정 | 전용 사용자 `banipmatch`, systemd 보호(ProtectSystem=strict, NoNewPrivileges, 메모리 상한 1.4GB) | 같은 서비스 파일 |
| 환경 | 공개 모드·세션 작업공간·실계산·웹 푸시 설정 | `deployment/cloud/app.env.example` |
| 저장 | `/var/lib/banipmatch/workflow`(방문자 작업공간별 SQLite), `/var/lib/banipmatch/reference/current.json`(수집 자료) | — |
| 의존성 | Python 3.12 가상환경 | `requirements-cloud.txt` |

## 배포 절차

1. 깨끗한 작업 트리에서 프론트를 `VITE_API_MODE=v2`로 빌드한다.
2. `tools/package_cloud_release.py`로 커밋 기준 배포 묶음(ZIP)을 만든다.
3. 서버의 `/opt/banipmatch/releases/<커밋-시각>/`에 풀고, `/opt/banipmatch/current` 심볼릭 링크를 새 버전으로 바꾼다.
4. `systemctl restart banipmatch` 후 로컬(127.0.0.1)과 공개 주소가 200인지 확인한다.
5. 최근 3개 버전만 남기고 이전 버전은 지운다(되돌릴 때는 링크만 바꾼다).

## 실제 자료 자동 수집

systemd 타이머 2개가 `tools.collect_live_reference`를 실행한다(`--only hjnc|kma`, 동시 실행은 `flock`으로 막음).

| 타이머 | 주기 | 하루 호출 | 한도 대비 |
|---|---|---:|---|
| HJNC 선석 배정 | 매시 20분 | 24 | 공개 조회, 시간당 1회로 제한 |
| 기상청 해양관측·특보 | 매시 5분·35분 | 96 | 일 20,000회의 0.5% |

수집에 실패하면 직전 정상 자료를 유지하고 실패 원인(제공처 응답 오류/연결 실패)을 기록한다. 화면은 서버에 저장된 사본을 5분마다 읽으므로 방문자 수와 외부 호출 수는 무관하다.

## 공개 운영 보호

- 방문자마다 별도 작업공간(쿠키 세션)과 DB, 24시간 뒤 자동 정리, 동시 작업공간 200개 상한
- 요청 제한: 작업공간당 분당 180회(쓰기 40회), 계산 대기열 30건, 계산 10초 제한
- 실제 웹 푸시 발송은 알림 사용 코드로 허가한 작업공간만(10분에 5회 시도 제한)
- 기사 초대 링크는 1회·30분·기기 1대, 기사 이름·전화번호 미수집, 위치는 동의 시 최신 1건만 보관
