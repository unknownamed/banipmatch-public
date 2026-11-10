# 공급자 형식의 합성 예제 · F01

모든 원문은 **별도로 생성한 합성 자료**다. 실제 응답·키·개인정보를 복사하지 않았다. 실제 필드/인코딩을 따르지만 실제 관측·발표·항차 변경 이력이나 현장 분포를 재현했다는 뜻은 아니다. 서버·화면 담당은 실자료를 받을 수 없어도 이 예제로 오류·누락 표시를 먼저 연결할 수 있다.

## 실행과 바이트 보존

```sh
python tools/provider_fixture_bundle.py --check
python -m pytest tests/data/test_provider_fixture_bundle.py -q
python tools/provider_fixture_bundle.py --directory local/provider-fixtures-new
```

[manifest.json](manifest.json)은21개 파일의 경로·인코딩·해시·HTTP 상태·예상 감사 결과를 기록한다. 생성기 SHA와 고정 모의 시계도 포함한다. `--check`는 생성 규칙/바이트 일치와 기존 감사 도구의 예상 결과를 대조한다. 생성은 새 폴더만 사용하고 기존 폴더·파일을 덮어쓰지 않는다. 실패 시 생성 중인 새 폴더가 남을 수 있으므로 종료코드0과 valid를 함께 확인한다.

wire 파일은 CP949 텍스트와UTF-8 JSON이 섞여 있다. 편집기에서 일괄UTF-8 변환하지 않는다. `.gitattributes`에서 wire 경로의 바이트를 보존한다. 생성기를 수정하면 새 폴더에서 재생성해 비교한 후 버전 관리할 예제를 함께 갱신한다. 개인 `local/` 폴더 전체를 제출ZIP에 넣지 않는다.

[PR42 대조 기록](reader-check.json): head `122db8fae706316526092767dabad05913733e47`의 읽기 모듈에 HJNC7종을 모의시계/`kind=simulated`로 넣어 received/empty/partial/stale/failed와 계산·승인 차단을 확인했다. PR42는 아직 main 기능이 아니며 KMA 어댑터는 제공하지 않아 KMA14종은 main 감사기로 검증했다. API·화면 연동이 끝난 것처럼 해석하지 않는다.

## 범위

| 공급자 | 예제 | 예상 동작 |
|---|---|---|
| HJNC7종 | normal / empty / partial-page / missing-window / stale / format-changed / http-error | 중첩 `stringContent` 파싱,0행과 실패 구분, 표시 총건수/필수 값 누락은partial, 잘못된 날짜는format_error |
| KMA 지점1종 | station-normal | 가상 지점99999, 이름·좌표 등9개 값 |
| KMA 해양7종 | sea-normal / sea-empty / sea-missing / sea-unknown-negative / sea-future / sea-wrong-station / sea-stale | 실제로 확인한14열과 빈 필드/행 종료를 검사. 빈/음수는0으로 보충하지 않고 미래/다른 지점을 검출 |
| KMA 오류3종 | application-required / rate-limited / truncated | 403 신청 필요,429 HTTP 오류, 잘린 본문을 정상 빈 자료와 구분 |
| KMA 특보3종 | warning-normal / warning-preliminary / warning-empty | 주의의 시각과 예비 기간코드 구분. 예비 발효시각은null 보존,0행만으로 해당 구역 특보 없음 단정 금지 |

`-99.0`은 **미확인 음수값 처리 시험**이며 KMA가 이 값을 모든 필드의 공식 결측 코드로 쓴다고 선언한 것이 아니다. 예제의 고정 시계는2026-11-10T03:00Z, 신선도300초는 시험용 표시 정책이며 제공기관 갱신 보장이 아니다. `stale`은 수신시각 기준 나이이고 관측시각·필드 완전성과 별개다.

## 선효·길웅에게 넘기는 경계

- manifest의 `data_kind=simulated`, `simulated_received_at`, `engine_eligible=false`를 유지한다. 모의 원문의 시간을 실제 수신 로그로 표시하거나 실자료 실패 후 이 파일로 자동 전환하지 않는다.
- 각 case의 HTTP 상태도 전달한다. 오류 파일만 HTTP200 정상처럼 읽지 않는다. 전체 `expected`는 파서/로컬 시험의 기대값이며 공개 서버 응답 계약이 아니다.
- `hjnc-stale`, `kma-sea-stale`의 본문만 읽으면 오래됨을 알 수 없다. 별도로 전달하는 모의 수신시각·모의 현재시각을 사용한다. 테스트 외에는 현재 시각·보존 정책과 실제 공급자 조건을 검토한다.
- 고정된 모의 시계는 실제 오늘 시각이 아니다. PR42의 `ReferenceReader`와 대조할 때도 `kind=simulated`와 manifest의 시계를 주입한다. 실제 서버 시계를 임의로 바꾸거나 과거/미래 고정 표본을 최신 실자료로 승인하지 않는다.
- `audit_kma_response.py`·`audit_hjnc`를 재사용한다. KMA 정상 수신 상태여도 결측·미래·지점 불일치가 있으면 계산/현재 확정 정보로 승격하지 않는다. `valid`는예상 판정 일치이고21개 정상 자료라는 뜻이 아니다.
- PR42/43은 main 병합 여부와 head를 따로 확인한다. 이 묶음을 제공했다는 사실만으로 실제 서버/화면 연결·혼합 계산·세션 격리가 완료되지 않는다.

자료별 실제 확인 범위·필드·한계는 [데이터 본문](../../report/data-part.md), [HJNC 최신 수신기록](../hjnc-reference-verification.md), [KMA 검증](../kma-response-verification.md)을 따른다. 보고서에서21종은 합성 검수 입력으로만 집계하고 실제 표본/현장 건수에 더하지 않는다.
