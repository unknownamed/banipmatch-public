# 실제 참고 자료 표시 계약 · reference-display-1

2026-11-11 통합안. v0.1과 v0.2의 기존 배차·승인·수신자 계약은 유지하고, 담당자 세션의 읽기 경로를 추가한다. 새 필드/경로의 관련자 검토는 최종 통합 PR에서 1회 받는다.

`GET /v2/references/current` → 200 `LiveDisplay`. 기존 담당자 HttpOnly 세션이 필요하다. 수신자 쿠키만으로는 접근할 수 없다. 제공자 호출이나 갱신을 실행하는 경로가 아니며, 운영자가 미리 수신한 제한된 결과를 읽는다. 서버 설정 `BANIPMATCH_REFERENCE_FILE`이 없으면 503 `REFERENCE_NOT_CONFIGURED`, 읽기/형식 오류이면 503 `REFERENCE_UNAVAILABLE`. 실패를 합성 자료로 바꾸지 않는다.

- 최상위 `schema_version=reference-display-1`, `kind=reference`, `engine_conversion=blocked`, `approval_eligible=false`, `automatic_mock_fallback=false`는 고정값이다.
- `hjnc`: 기존 내부 `reference-read-preview-1` 투영. VOY_NO/YARD_OPEN/YARD_CLOSE/ETB만 표시하고 원문 시간대 미확인을 보존한다. 현재 표본 최대100행, 원문 오류/요청 URL/키/추가필드는 제외한다. 수신300초 경과는 표시상 stale이며 제공자 갱신 주기라고 주장하지 않는다.
- `weather`: 최대2개(해양 관측/특보). 관측·수신·발표·발효시각을 구분하고 결측/미해석/지점 불일치/미래 관측 경고를 유지한다. HTTP200·빈 본문은 특보가 없다는 증거가 아니다. 기상은 지연의 확정 원인이 아니다. `failure`는 실패 위치를 구분한다: `network`=응답을 받지 못함(연결 실패·시간 초과), `provider`=기상청이 오류 응답을 보냄(2026-11-13 추가).
- `ais`: 선택적 제한시험 집계만 제공한다. 구독 확인·시험범위·종료시각·위치 메시지 수·종료 상태. 실제 선박/항차 연결을 주장하지 않으며 `voyage_link_verified=false`이다.
- 보관 파일1MB 상한, Pydantic 허용 필드 투영, `Cache-Control:no-store`, 인증·기존 Origin/Host 경계 유지. 브라우저에 공급자 인증키를 주지 않는다.

정확한 타입은 [OpenAPI](openapi.json)의 `LiveDisplay`와 `GET /v2/references/current`, 구현은 `backend/references/display.py`를 따른다. [수집/운영 안내](../../../docs/deployment/live-demo.md)와 [통합 검수](../../team/handoffs/2026-11-11-unknownamed-live-demo.md)를 함께 읽는다.
