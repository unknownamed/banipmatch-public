# 직접 계산 배포 전 코드 점검 — 대겸 인계

2026-11-10 main516151f의 코드 읽기 점검이다. 기능 구현·침투검사·실서버 실행을 완료한 기록이 아니다. [전체 계획 F07~F11](completion-plan.md)에 따라 대겸이 최종 통합/수정·배포를 맡고 선효는 백엔드 변경을 인계한다.

| 경계 | 현재 코드에서 확인 | 남은 작업 / 완료 증거 |
|---|---|---|
| 로컬 접근 | [app.py](../../backend/api/app.py)의 local_boundary가 loopback client와 localhost/127.0.0.1/::1 Host, 허용 Origin을 검사 | 공개 모드를 명시적으로 설계하고 Host/Origin/신뢰 프록시/쓰기 보호를 유지. 이 제한을 삭제하는 것만으로 배포하지 않음 |
| 공통 인증 | app.py authenticate는 [settings.py](../../backend/api/settings.py)의 공통 demo_token과 비교 | 공개 방문자용 세션과 권한 범위 필요. 공통 토큰을 모든 브라우저에 배포하지 않음 |
| 저장/접근 | [store.py](../../backend/db/store.py)는 DEMO_ACTOR 멱등 범위와 scenario/plan/run ID 기반 조회 | 세션→입력/실행/계획 소유를 연결하고 모든 조회/쓰기/멱등키에 검사. A/B 사용자 ID 교체 테스트 |
| 계산 프로세스 | [engine_replay.py](../../backend/api/engine_replay.py)는 방법별 별도 subprocess와 time_limit_seconds+5 timeout을 이미 사용 | 기존 격리/시간초과 처리 재사용. 공개 입력/규모/총요청 시간·취소/자원 회수·서버 예산 검증을 연결. timeout이 없다고 다시 구현하지 않음 |
| 실행 큐 | [runs.py](../../backend/api/runs.py)는 ThreadPoolExecutor(max_workers=1), submit과 재시작 recover를 사용 | 단일 worker는 대기열 크기·방문자 요청률 제한을 뜻하지 않음. admission/queue 상한, 중복/포화 응답, 재시작·만료/정리 검사 |
| 결과 검사 | runs.py가 결과 무결성·독립 일정검사를 한 뒤 승인 가능 여부를 결정 | 세션 분리 이후에도 동일 경계를 유지하고 오래된 실행/계획·중복 적용을 회귀검사 |
| 자료 제한 | [storage_checks.py](../../backend/api/storage_checks.py)의 simulated 저장 제한 | 직접 계산 공개는 모의자료로 구현 가능. 실제 참고 표시와 혼합계산은 별도. 제한만 해제하지 않음 |
| 공개 화면 | 기존 dist-showcase는 네트워크 계산 없는 정적 탐색 | 보조로 보존. 실제 API와 연결된 앱의 배포·세션/실패·직접 계산을 검수해야 이번 목표 달성 |

권장 인계 순서는 선효 세션/공개요청 경계 계약·예제 → 길웅 UI 연결 → 각자 자체검사 → 대겸 최종통합/수정·패키지 → 대겸 서버/주소/실제배포 → 팀원 시험보고 → 대겸 보완이다. 기존 입력/엔진 기능을 다시 만드는 계획이 아니다.

대겸이 배포 환경을 선택하면 OS/런타임·주소/HTTPS·프록시·프로세스 실행 방식·저장 위치/수명·CPU/RAM·동시 계산 상한·필요한 공급자 설정을 맞춘다. 지금 알 수 없는 호스팅/비용/주소를 정한 것으로 기록하지 않는다. 키 값은 이 문서에 넣지 않는다.
