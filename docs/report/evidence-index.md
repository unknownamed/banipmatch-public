# 보고서 주장·근거·담당 인계표

2026-11-10. [본문 초안](report-draft.md)의 기존 근거를 연결한다. 새 테스트나 새 현장 증거를 만들었다는 문서가 아니다. 최종 PDF에서 필요한 원문 URL·확인일·그림/표 번호를 유지한다.

| ID | 본문에 사용할 주장 | 근거 | 한계 / 남은 일 |
|---|---|---|---|
| E01 | 반입마감 준수 필요와 과거 반입 기준 변경 사례 | [HJNC 공식 공지별 확인](../team/operational-evidence.md) | 현재 빈도·손실·항차 변경쌍의 증거는 아님 |
| E02 | 배차/지도 자체보다 변경 이후의 보호·절충 비교를 검토 | [공개 서비스 비교7곳](../team/service-comparison.md) | 로그인/알고리즘·실효과 미검증. 경쟁 미지원·우위 단정 금지 |
| E03 | B0~B3·고정보존·목적/변경 지표·독립검사 | [엔진 규칙](../../backend/engine/OPTIMIZATION.md), [작은 사례 검산](../team/handoffs/2026-11-09-unknownamed-frozen-oracle.md) | 솔버 최적성·일정 유효성·현장 적합성 구별 |
| E04 | 10입력×2시드×4방법=80회, 조정60/원안20 별도검사 | [고정 프로토콜/원시 결과](../experiments/engine-evaluation-2026-11-08/README.md) | 기존 실행 커밋0d2640b, 현 main 재실행이라고 표시하지 않음 |
| E05 | 동일 작업14쌍, 작은12쌍 변경4~7감소·이동12~82분증가,50건차이없음 | [20쌍 CSV](../experiments/engine-evaluation-2026-11-08/results/pairs.csv), [모든 대표행](../experiments/engine-evaluation-2026-11-08/showcase.md) | 다른 작업6쌍 별도. 기존228회와 합쳐 현장 표본/성능으로 세지 않음 |
| E06 | 자료 공백9사례: 완전4입력16계산·조정12검사,5개계산전차단 | [공백 사례/결과](../experiments/data-demo-2026-11-10/README.md) | 모의 수용검사, 실제 API/DB/웹 검수 아님 |
| E07 | 실표본 존재와 필드/권한·공백 | [HJNC](../data/hjnc-reference-verification.md), [KMA](../data/kma-response-verification.md), [도로](../data/road-api-verification.md), [자료 실행 계획](../team/data-demo-sprint-2026-11-10.md) | 민준·선효·길웅의 새 실제 연결/ORS/AIS/화면 결과를 인계 후 확정 |
| E08 | 공개 계산 앱의 동작·세션 격리·실배포 | [완료 계획 F07~F11](../team/completion-plan.md), [검수표](../team/release-acceptance-template.md) | **아직 증거 없음.** 대겸 통합/배포·팀원 시험·대겸 보완 후 채움 |
| E09 | 보고서/데이터·코드 제출 규칙 | [공식 보존 원본·요건](../team/completion-plan.md#8-공식-제출-요건과-현재-범위) | 새 공지/회신 재확인. PDF/ZIP/파일명은 팀 방침 |
| E10 | 차량별 정확한 변경 명세·미해결 근거/확인 안내 로직 | [B1 계산·명세·해시](../experiments/dispatch-response-2026-11-10/README.md), [구현·검수 인계](../team/handoffs/2026-11-10-unknownamed-dispatch-response.md) | 모의 입력 로직 검수. 현재 DB 승인/전송 권한·화면 연결·실수신 증거 아님 |
| E11 | 조건 재계산→확정→대상 전달→수신자 응답의 전체 흐름 | [확정 범위 R1~R8](../team/dispatcher-response-scope.md), [A15~A19 검수표](../team/release-acceptance-template.md) | **전체 구현/실기기 증거 아직 없음.** #54~#57 구현 후 대겸 통합·실배포/팀원 검수 필요 |

현재 할 수 있는 본문을 먼저 작성했고 E07의 새 연동·E08은 미완료로 남겼다. 팀원이 인계할 때 위 ID와 해당 이슈·검증 버전을 연결하면 대겸이 본문/최종 PDF에 반영한다. 숫자·그림이 바뀌면 입력/실행 버전도 함께 대조하며 동결 결과 원본은 수정하지 않는다.

E07 민준 인계: [데이터 파트 본문·자료/공백/추가자료 표](data-part.md), [합성wire21종](../data/provider-fixtures-2026-11-10/README.md). 합성 공급자 예제·기존 모의 계산·실관측 건수를 분리한다. 실제 서버→화면·공개 URL 검수는 인계 후 확인할 항목으로 유지한다.

E10/E11 민준 추가 근거: [대응 검수 9사례·조건 전후 4쌍·전달 기대 15종](../data/response-acceptance-2026-11-11/README.md), [PR61 고정 head의 주입 전송 API 대조 9종](../data/response-acceptance-2026-11-11/workflow-check.json). 모의 계산/로컬 API 검수이며 E11의 전체 화면·실기기 증거를 채우지 않는다.
