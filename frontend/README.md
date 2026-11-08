# 프론트 (최길웅)

배차 담당자용 단일 작업 화면. 현재는 **공통 예제(v0.1) 설명용 결과를 표시하는 단계**이며 로컬 API의 입력 등록·실행 요청·결과 조회에 연결했다. API의 실제 최적화 엔진 연결과 독립 일정 검사·승인은 아직 구현하지 않았다.

## 도구

React 18 + TypeScript + Vite 6.4.5, 테스트는 Vitest 4.1.12. 상태 관리·UI 라이브러리는 쓰지 않았다. 개발 도구의 알려진 취약점을 줄이기 위해 버전과 잠금 파일을 함께 갱신했다(2026-11-08 `npm audit` 보고 0건이며 모든 보안 문제의 부재를 보장하지 않음).

## 실행

Node 24 권장(CI와 같은 버전). Vitest는 Node 20·22·24 이상 지원 계열을 사용한다.

```sh
cd frontend
npm ci --ignore-scripts
npm run dev        # http://localhost:5173
npm test           # 공통 예제 판정 테스트
npm run build      # 타입 검사 + 빌드
```

PR과 main 변경마다 위 테스트·빌드를 GitHub Actions가 실행한다. 실제 브라우저 조작과 전체 API 연결 검수는 별도로 남긴다.

- 기본은 fixture 모드: `docs/development/v0.1/예제 데이터`의 01·03·04 JSON을 **복사하지 않고 직접** 읽는다.
- [백엔드 안내](../backend/README.md)에 따라 로컬 API를 실행한 뒤 `frontend/.env.local`에 `VITE_API_MODE=http`와 서버 모의 토큰과 같은 `VITE_API_TOKEN`을 설정하고 개발 서버를 시작한다. `.env.example`을 참고하며 실제 설정값은 Git에 올리지 않는다. `/v1` 요청은 `127.0.0.1:8000`으로 전달한다(포트는 백엔드에 맞춰 `vite.config.ts` 수정).
- HTTP 모드에서 `?run=`이 없으면 **예제로 계산 요청** 화면이 뜬다. 버튼을 누르면 예제 01을 새 ID로 `POST /v1/scenarios`, 02로 `POST /v1/runs`를 보내고 받은 `run_id` 결과 화면으로 이동한다. 실패 후 다시 시도는 같은 본문·같은 Idempotency-Key를 쓴다. 2026-11-08 main의 로컬 API로 등록 201 → 실행 202 → 결과 200과 J0 고정·J3 미처리·승인 차단 표시, 백엔드 중단 시 오류 안내를 확인했다. 승인 POST와 07/08 오류 입력 화면은 아직 없다.
- 다른 ID 조회: `?scenario=S001&run=R001`.

## 구조

| 파일 | 역할 |
|---|---|
| `src/api/types.ts` | `contracts.schema.json` 중 화면에서 쓰는 타입(필드명·enum 그대로) |
| `src/api/client.ts` | `/v1` 입력·실행 POST와 HTTP 조회 클라이언트(202 계산 중 처리) |
| `src/components/StartRunPanel.tsx`, `src/lib/startRun.ts` | 예제 입력 등록→실행 요청, 같은 본문·멱등키 재시도 |
| `src/api/fixtureClient.ts` | 공통 예제를 돌려주는 조회 클라이언트 |
| `src/api/useDispatchView.ts` | 입력·실행·결과를 따로 조회, 202면 간격을 늘려 재조회, ID가 다른/늦은 응답 무시 |
| `src/lib/compare.ts` | 같은 작업 ID로 원안/조정안 맞추기, 고정 작업 이탈 감지 |
| `src/lib/approval.ts` | 승인 버튼 차단 조건(설명용·미검증·입력 불일치 등) |
| `src/lib/time.ts` | UTC Z → 한국 시각 표시, null은 `미확인` |

## 지키는 규칙

- 변경 여부·원인은 응답의 `metrics`, `issues`만 쓴다. 화면에서 원인을 만들어내지 않는다.
- `illustrative_fixture` 결과는 배너로 표시하고 승인 버튼을 막는다.
- 계산 중에도 입력·변경 근거는 먼저 보인다. 등록·실행 POST는 버튼을 누를 때만 전송하며 자동 반복하지 않는다. 실패 후 다시 시도에는 같은 본문·멱등키를 사용한다.
