# 작업 인계: 공통 예제 설명용 결과 화면

- 날짜 / 담당 / 파트: 2026-11-07 / 최길웅 / 프론트
- 브랜치 / PR / 기준 커밋: `codex/choigilung-fixture-result-view` / PR 미생성 / `5ffd96a`
- 사용한 계약 버전: v0.1 (`docs/development/v0.1/`)

## 요청과 결정

역할표의 프론트 첫 작업: 공통 예제의 J0 고정, J1/J2 조정, J3 미처리 이유를 설명용 응답으로 표시하고, 설명용 결과임을 알리며 승인을 막는다.

- 프론트 도구는 **React 18 + TypeScript + Vite 5 + Vitest**로 제안한다(공통 규격상 팀 합의 대상 — PR에서 확인 요청).
- 예제 JSON은 `frontend/`에 복사하지 않고 Vite 별칭 `@examples`로 원본을 읽는다. 예제가 바뀌면 화면·테스트가 같이 따라간다.
- 계약 필드·상태는 바꾸지 않았다. 계약 변경 없음.

## 변경과 검증

- 바뀐 동작과 파일: `frontend/` 신규(화면·조회 클라이언트·비교/승인 로직·테스트), 이 인계 기록.
- 추가 반영: 엔진 PR #1 인계의 프론트 요청(HEURISTIC/FEASIBLE을 최적으로 표시하지 않음, 미처리 증가 경고), `service-comparison.md` 기준의 시간 구분 문구(반입 허용시간 ≠ 접안예정·방문예약, 내부 계획 승인 ≠ 예약 변경·TMS 반영), AP-04 카카오맵 확인 화면 `?view=map`(키는 `frontend/.env.local`, Git 제외).
- 실제 실행한 명령·환경·결과 (Windows 11, Node 24.16.0):
  - `npm test` — 8개 통과 (J0 고정 유지, J1/J2 차량·시각 변경, J3 READY_TOO_LATE 미처리, B0 J1 마감 초과 보존, 고정 작업 누락 감지, 설명용 승인 차단, computed+eligible+passed+같은 입력일 때만 승인 허용, KST 변환·null 미확인)
  - `npm run build` — 타입 검사·빌드 성공
  - 개발 서버에서 화면 확인: 배너 2종, 변경 근거(V1 12:00→10:30 KST, 확정), 실행 R001 완료/해 상태, B0↔B3 비교표, J3 미해결 설명, 승인 버튼 비활성+이유 3개. 콘솔 오류 없음.
  - `?run=R999`: 입력·변경 근거는 표시되고 실행·결과 칸에만 조회 실패가 뜨는 것 확인.
  - 375px 폭: 가로 스크롤 없음.
- 실행하지 못한 검사와 이유:
  - `python tools/check_development.py`: 계약·예제를 수정하지 않아 실행하지 않음.
  - HTTP 모드(`VITE_API_MODE=http`): 백엔드가 없어 미확인. 202 재조회·늦은 응답 무시는 코드만 있고 실제 서버로는 검증 안 됨.
  - `npm audit`가 개발 의존성(vite/esbuild 개발 서버) 취약점 경고를 냄. 개발 서버 전용이며 이번에 버전을 올리지 않음.

## 다음 작업

- 남은 일과 담당:
  - (최길웅) 07 입력누락·08 미확인변경 예제 표시, 06 버전 충돌·422 RESULT_NOT_COMPUTED 오류 화면, 승인 요청(POST, Idempotency-Key) 흐름.
  - (최길웅·안선효) 백엔드 `/v1` 조회 연결, 포트·CORS/프록시 합의.
- 연결된 파트에 전달할 것:
  - 안선효: 화면은 `GET /v1/scenarios/{id}`, `GET /v1/runs/{id}`, `GET /v1/runs/{id}/results`(202=Run, 200=Results)를 쓴다. 응답의 `scenario_id`/`run_id`가 요청과 다르면 표시하지 않는다.
  - 황대겸: 변경 표시는 `metrics.*_changed_job_ids`, 미처리 이유는 `issues`(job_id, code, explanation, proof_level, evidence_refs)만 쓴다. 미처리 작업에 issue가 없으면 화면에 "이유 미제공" 경고가 뜬다.
- 알려진 한계·미확인 사항: 인증·승인 POST 없음, 지도 없음, B1/B2 결과가 있으면 탭으로 고르게 했지만 예제에 없어 실제로는 B3만 보임.
- 다음 AI가 먼저 읽을 파일: `frontend/README.md`, 이 문서, `docs/development/v0.1/공통 규격/frontend_pages.json`.
