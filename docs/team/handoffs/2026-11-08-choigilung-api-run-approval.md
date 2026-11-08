# 작업 인계: 로컬 API 계산 요청·거절 화면·내부 승인 요청

- 날짜 / 담당 / 파트: 2026-11-08 / 최길웅 / 프론트
- 브랜치 / PR / 기준 커밋: 쌓인 PR 3개, 순서대로 병합
  - [PR #7](https://github.com/unknownamed/banipmatch/pull/7) `codex/choigilung-api-run-request` (base main)
  - [PR #8](https://github.com/unknownamed/banipmatch/pull/8) `codex/choigilung-blocked-inputs` (base #7)
  - [PR #9](https://github.com/unknownamed/banipmatch/pull/9) `codex/choigilung-approval-flow` (base #8), 기준 `0aa8c9c`
- 사용한 계약 버전: v0.1 (`docs/development/v0.1/`). 계약 변경 없음.

## 요청과 결정

[첫 화면 인계](2026-11-07-choigilung-fixture-result-view.md)의 남은 일을 작은 PR로 나눠 진행했다.

- #7: HTTP 모드에서 예제 입력을 `POST /v1/scenarios`로 등록하고 `POST /v1/runs`로 계산을 요청한 뒤 결과 화면으로 이동한다.
- #8: 07 입력 누락·08 미확인 변경 예제가 계산 거절될 때 저장된 입력·변경 근거·원안과 거절 사유를 보여준다.
- #9: 내부 계획 승인 `POST /v1/plans/{plan_id}/approvals`. 미처리·고정 위험 작업 확인 체크 후에만 보낸다.
- 황대겸이 병합 전 점검에서 세 PR에 직접 수정을 올렸다(2026-11-08, [review-policy](../review-policy.md)의 병합 담당 수정 허용 범위). 아래 "팀원 보완" 참조. 이 점검은 AI 자체 검증이며 #7·#9의 안선효 1회 검토 요청은 유지된다.

## 변경과 검증

- 바뀐 동작과 파일: `frontend/src/components/StartRunPanel.tsx`, `ApprovalPanel.tsx`, `src/lib/startRun.ts`, `src/lib/approval.ts`, `src/api/client.ts`·`types.ts`, 테스트 3개 파일. 상세는 [frontend/README.md](../../../frontend/README.md).
- API 연결 목록 (모두 `Authorization: Bearer`, POST는 `Idempotency-Key`):

  | 요청 | 화면 처리 |
  |---|---|
  | `POST /v1/scenarios` | 201 성공. 실패 시 같은 본문·키로 재시도 |
  | `POST /v1/runs` | 202 → 결과 화면. 422 입력 오류·503 `WINDOW_UNCONFIRMED`는 거절 화면(재시도 숨김). 503 `STORAGE_UNAVAILABLE`·본문 없는 오류·연결 실패는 재시도 유지 |
  | `GET /v1/scenarios/{id}`, `/v1/runs/{id}`, `/v1/runs/{id}/results` | 202면 1초→최대 10초 간격 재조회, ID가 다른 늦은 응답 무시 |
  | `POST /v1/plans/{plan_id}/approvals` | 응답의 계획·실행·방법·버전·외부 반영 여부를 요청과 대조. 409·422·503은 코드별 안내 |
  | `GET /v1/plans/{plan_id}` | 승인 뒤 현재 계획 재확인. 조회 실패는 승인 실패로 취급하지 않음 |

- 실제 실행한 명령·환경·결과 (Windows 11, Node 24.16.0, 2026-11-08 `0aa8c9c`):
  - `npm ci --ignore-scripts` — 0 vulnerabilities
  - `npx vitest run` — 5개 파일 55개 통과
  - `npm run build` — 타입 검사·빌드 성공
- 확인한 정상·실패 사례 (로컬 `python -m backend`, 모의 토큰):
  - 01: 등록201 → 실행202 → 결과200, J0 유지·J3 미처리·설명용 결과로 승인 차단.
  - 07: 422 `INPUT_INCOMPLETE`, J1 "준비시각 미확인" 표시.
  - 08: 503 `WINDOW_UNCONFIRMED`, 변경이 "미확정"으로 표시.
  - 확인 후 백엔드 종료, 임시 환경 파일 삭제.
- 팀원 보완 (황대겸, PR 댓글 기준):
  - #8 `31ff332`: 저장소 장애 503을 입력 거절로 분류하던 문제 수정.
  - #9 `46e5373`: 연속 클릭 중복 POST 차단, 응답 불일치 시 성공 미표시, 재시도 가능/불가 오류 구분, 방법 전환 후 같은 키 유지, jsdom 클릭 회귀 26개 추가.
- 실행하지 못한 검사와 이유:
  - 실제 승인 성공·409·503: 현재 서버가 설명용 결과만 주어 승인 버튼이 열리지 않는다. 모의 클라이언트 테스트로만 확인.
  - 팀원 보완 이후 브라우저 화면 재확인과 `python tools/check_development.py`(계약 미변경)는 하지 않음.

## 다음 작업

- 남은 일과 담당:
  - (안선효) #7·#9 검토 후 #7 → #8 → #9 순서 병합. 앞 PR 병합 때마다 다음 PR base를 main으로 변경.
  - (최길웅) 엔진 [PR #6](https://github.com/unknownamed/banipmatch/pull/6) 병합 뒤 B2/B3 결과의 탭·지표·해 상태 표시 확인. 현재 #6은 main과 충돌.
  - (최길웅·안선효) 실제 계산 결과가 생기면 승인 성공·충돌을 실제 서버로 확인.
  - (최길웅·심민준·안선효) API가 입력 검증 결과를 내보내면 source/row/path/message 행별 오류 표시.
- 연결된 파트에 전달할 것:
  - 안선효: 화면은 승인 응답의 `plan_id`, `run_id`, `method`, `version`, `external_actions_performed`를 요청과 대조한다. 서버도 승인 트랜잭션에서 현재 입력·계획 버전·권한을 다시 검사해야 한다.
  - 황대겸: 승인 확인 대상은 `unassigned_job_ids`와 `FIXED_RESIDUAL_RISK` issue의 `job_id` 합집합이다.
- 알려진 한계·미확인 사항: 멱등키는 메모리에만 있어 새로고침하면 초기화된다. 인증은 로컬 모의 토큰뿐이다. 지도 화면은 AP-04 키 확인용 `?view=map`만 있다.
- 다음 AI가 먼저 읽을 파일: `frontend/README.md`, 이 문서, `docs/development/v0.1/공통 규격/frontend_pages.json`.
