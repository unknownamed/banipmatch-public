# 프론트 (최길웅)

배차 담당자용 단일 작업 화면. 현재는 **공통 예제(v0.1) 설명용 결과를 표시하는 단계**이며 백엔드·실제 계산과는 아직 연결하지 않았다.

## 도구 (첫 구현 제안 — 팀 확인 필요)

React 18 + TypeScript + Vite 5, 테스트는 Vitest. 상태 관리·UI 라이브러리는 쓰지 않았다.

## 실행

Node 20 이상.

```sh
cd frontend
npm install
npm run dev        # http://localhost:5173
npm test           # 공통 예제 판정 테스트
npm run build      # 타입 검사 + 빌드
```

- 기본은 fixture 모드: `docs/development/v0.1/예제 데이터`의 01·03·04 JSON을 **복사하지 않고 직접** 읽는다.
- 백엔드가 생기면 `VITE_API_MODE=http npm run dev` 로 `/v1` 요청을 `127.0.0.1:8000`에 넘긴다(포트는 백엔드에 맞춰 `vite.config.ts` 수정).
- 다른 ID 조회: `?scenario=S001&run=R001`.

## 구조

| 파일 | 역할 |
|---|---|
| `src/api/types.ts` | `contracts.schema.json` 중 화면에서 쓰는 타입(필드명·enum 그대로) |
| `src/api/client.ts` | `/v1` HTTP 조회 클라이언트(202 계산 중 처리) |
| `src/api/fixtureClient.ts` | 공통 예제를 돌려주는 조회 클라이언트 |
| `src/api/useDispatchView.ts` | 입력·실행·결과를 따로 조회, 202면 간격을 늘려 재조회, ID가 다른/늦은 응답 무시 |
| `src/lib/compare.ts` | 같은 작업 ID로 원안/조정안 맞추기, 고정 작업 이탈 감지 |
| `src/lib/approval.ts` | 승인 버튼 차단 조건(설명용·미검증·입력 불일치 등) |
| `src/lib/time.ts` | UTC Z → 한국 시각 표시, null은 `미확인` |

## 지키는 규칙

- 변경 여부·원인은 응답의 `metrics`, `issues`만 쓴다. 화면에서 원인을 만들어내지 않는다.
- `illustrative_fixture` 결과는 배너로 표시하고 승인 버튼을 막는다.
- 계산 중에도 입력·변경 근거는 먼저 보인다. 결과 POST는 자동 반복하지 않는다(아직 POST 화면 없음).
