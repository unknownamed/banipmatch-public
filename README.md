# 반입맞춤 · BanipMatch

**개인 API 신청 담당:** [기상청은 민준, AISstream은 선효, ORS 무료 Standard는 길웅](docs/team/personal-api-signup.md). 기존 계정/키 확인 후 없으면 본인 명의로 신청하고, 실제 발급·응답 결과를 기록합니다. 도로공사 민준 담당과 기존 지도는 유지합니다. 회원가입·본인 인증·약관/무료량은 적용됩니다.

**부산항 신항(진해) 수출 컨테이너 반입시간 변경 대응 배차 점검·조정**

국립창원대학교 컴퓨터공학과 학생팀 **반입맞춤**의 프로젝트입니다.
**2026 스마트물류 문제해결 경진대회**에 참가해 보고서와 발표를 준비하고 있습니다.

터미널에서 확인한 반입 시작·마감 시간이 바뀌었을 때, 기존 배차에서 영향을 받는 작업을 찾습니다.
이미 출발한 차량과 변경할 수 없는 작업은 유지하고, 남은 작업의 조정안을 비교하는 모의 웹앱을 개발하고 있습니다. 로컬 계산·비교·내부 승인 흐름은 검수했으며 공개 배포와 현장 검증은 별도입니다.
조정해도 해결되지 않는 작업은 이유와 함께 보여주고, 배차 담당자가 검토한 뒤 내부 계획을 승인하도록 설계합니다.

**11월9일 후속 작업:** [실제 자료 검증·연결](docs/team/real-data-integration.md)을 시작합니다. 민준은 도로공사 키 보유 확인→없으면 즉시 신청→첫 응답 검증, 선효는 읽기 전용 연결·실패 상태, 길웅은 출처·실제/참고/모의 표시, 대겸은 관측 비교·혼합 사례 검증을 맡습니다. HJNC 실제 응답 확인과 운영 앱의 연동 완료는 구분합니다.

## 현재 상태

[심사 항목별 주장·증거 준비 기준](docs/team/evaluation-evidence.md): 사용자 제공 심사표에 맞춘 담당별 부족 증거·완료 기준과 보고서20쪽/발표15쪽 구성안입니다. 현재 기능·모의 결과의 한계를 유지하며 공식 최신 공고 확인이나 새 기능 구현을 뜻하지 않습니다.

현재 계약은 **개발 규격 초안 v0.1**입니다. 데이터 입력 검증·로컬 API/저장·설명용 비교 화면과 **B0~B3 계산 엔진**이 있습니다. B2/B3는 같은 처리 수준에서 이동과 변경 부담을 비교하며 [모의 실험과 한계](docs/experiments/engine-b0-b3/README.md)를 기록했습니다. 선택형 실계산 API·독립 일정 검사·로컬 내부 승인과 데이터 준비 CLI까지 연결했습니다. 대표 모의 사례의 화면 비교·실계산·내부 승인 흐름은 [PR18·22 검수](docs/team/handoffs/2026-11-08-he6venly-demo-evidence.md)로 확인했습니다. 운영 인증·공개 배포·현장 효과는 별도입니다.

| 구분 | 상태 |
|---|---|
| 공통·담당별 개발 문서 | PDF 5종, 총 18쪽 작성 |
| 내부 API·데이터 계약 | OpenAPI 3.1.1, JSON Schema 초안 |
| DB | SQLite 기준 16개 테이블·133개 필드, 실행 가능한 초기 스키마 |
| 예제 | 모의 입력·설명용 결과·오류 사례·CSV 제공 |
| 검수 | main `6b8a776`의 CI: Python259개/하위235개, 계약·예제29개, DB32개 통과 |
| 데이터 첫 구현 | [CSV·JSON 입력 검증](backend/data/README.md), 오류의 필드·출처·행 반환, CLI 준비와 수신/관측시각 검사. API 실행 전 점검에 연결 |
| 로컬 API 1차 | 입력 등록·조회·SQLite 저장. 설명용 재생 또는 선택형 B0~B3 실계산·독립 검사·내부 승인. API 테스트61건 |
| 엔진 | 0.2.3 B0/B1 및 B2/B3 사전식 최적화, 엔진·평가 테스트100건. 완전한 초기안 힌트·probing0 보완. [기존0.2.1·156회](docs/experiments/engine-sensitivity-2026-11-08/README.md)와 [후속72회](docs/experiments/engine-profile-2026-11-08/README.md)를 분리 보존. 실제 API 연결 및 대표 사례 브라우저 시연 검수 |
| 프론트 | React·TypeScript 비교·입력 등록·오류 입력 안내·내부 승인 요청 화면. main `6b8a776`의 테스트68건·타입 검사·빌드 통과. 탭 전환 중 승인 상태·재시도 보존, 실계산 목표 단계 표시. PR18~20의 승인 거절·버전 차단·방법 선택·실패 이유 표시 검수 |
| 통합·인증·배포 | CLI·실계산 API·독립 검사·로컬 승인 연결 검수. 운영 인증·사용자 격리·공개 배포 미구현 |
| 외부 API 연동·실제 운송 자료 | 권한·표본 확인 필요 |
| 최종 대회 보고서·발표자료 | 준비 중 |

검수는 **명세·저장 구조·예제와 B0~B3 동작**을 대상으로 합니다. 모형의 최적성 증명은 실제 운송 자료의 효과 검증과 다릅니다.

[엔진 실행·연결 안내](backend/engine/README.md) · [모의 예제의 실계산 결과](docs/experiments/engine-b0-b1/README.md) · [최신 엔진 인계](docs/team/handoffs/2026-11-08-unknownamed-engine-diagnostics.md)

보고서 삽입용 [기존156회 요약 PDF4쪽](docs/experiments/engine-report-2026-11-08/engine-experiment-summary.pdf) · [0.2.2 후속72회 PDF2쪽](docs/experiments/engine-report-2026-11-08/engine-performance-followup.pdf). 후속20건 B3는3초에서도 변경2건의 최적성을 증명했고10초 호출 중앙값은5.21→2.42초였습니다. 50건10초 B2는 전체 최적성을 증명했지만 B3는 미처리26/변경23/이동1,440분의 `FEASIBLE`로 전체 최적성은 미증명입니다. 모의 결과이며 API 독립 일정 검사·승인·현장 검증은 별도입니다.

로컬 API 실행·프론트 연결·검증 방법은 [백엔드 안내](backend/README.md)에 있습니다. 기본 서버는 설명용 재생이며 `BANIPMATCH_RUN_MODE=engine`에서 모의 입력을 실제 계산합니다. 검증된 결과만 로컬 내부 승인할 수 있고 외부 예약·기사 통보는 수행하지 않습니다. [통합 검수와 한계](docs/team/handoffs/2026-11-08-pr12-pr14-integration.md)를 확인하세요.

[심사 대응 설계 보완서(PDF 4쪽)](docs/design/evaluation-addendum-2026-11-08.pdf)는 기존 설계v6와 함께 읽는 내부 개발 자료입니다. 최종 보고서·발표자료와 구분합니다.

새 [80회 평가와 한계](docs/experiments/engine-evaluation-2026-11-08/README.md) · [설명용 PDF4쪽](docs/experiments/engine-evaluation-2026-11-08/engine-evaluation-summary.pdf): 조정안60개를 별도 검사했고, 같은 처리 작업에서 변경 감소와 이동 증가를 함께 확인했습니다. 50건에서는 이점·전체 최적성을 확인하지 못했습니다. [HJNC 공식 업무 근거](docs/team/operational-evidence.md)와 함께 읽습니다.

[전체10사례 화면·보고서 비교 근거](docs/experiments/engine-evaluation-2026-11-08/showcase.md): 같은 화물을 처리했는지와 변경·이동·고정 위험·최적성 한계를 함께 확인합니다. 기존80회 원본은 보존합니다.

[공개 모의 시연 준비](docs/team/public-showcase.md): 기존 로컬 계산·승인 앱과 분리한 읽기 전용 평가 화면을 준비했습니다. 새 계산이나 공개 URL 배포 완료를 의미하지 않습니다.

## 팀원이 처음 작업할 때

**매 작업 시작·재개 및 PR 제출·병합 전에 [최신 main 반영 절차](CONTRIBUTING.md#최신-main을-반영하는-순서)를 따릅니다.** 원격 정보를 가져온 뒤 새 작업은 최신 `origin/main`에서 시작하고, 진행 중인 작업은 기존 변경을 보존하며 합칩니다. Git 접근이 없는 웹 채팅 AI에는 직접 최신 파일을 전달해야 합니다.

**[열린 PR의 최신 커밋·리뷰 확인](CONTRIBUTING.md#최신-pr을-확인하는-순서)도 함께 합니다.** PR을 검토·수정할 때는 해당 소스 브랜치까지 가져와 기준 커밋을 맞춥니다. main만 갱신했다고 미병합 PR도 최신인 것은 아니며, 열린 PR을 전부 작업 브랜치에 합치지는 않습니다.

1. [AI 공통 작업수칙](AGENTS.md)과 [역할·담당 범위](docs/team/roles.md), [현재 구현 상태](docs/team/status.md), [기존 서비스 비교·담당별 적용사항](docs/team/service-comparison.md)을 읽습니다.
2. 아래 공통 PDF 00과 본인 담당 PDF 01~04를 읽고 같은 버전의 규격·예제를 사용합니다.
3. [AI 사용·브랜치·검수 안내](CONTRIBUTING.md)의 시작 문구를 사용하는 AI에게 전달합니다.
4. 작업 브랜치에서 구현하고 PR에 검증 결과를 남깁니다. AI 세션이 바뀌면 [인계 양식](docs/team/handoffs/TEMPLATE.md)으로 이어갑니다.

ChatGPT·Claude 등 특정 구독으로 통일하지 않습니다. Codex·Claude Code·Copilot·Cursor용 진입점을 마련했고, 일반 웹 채팅에는 관련 파일과 시작 문구를 직접 전달합니다. 모든 AI가 자동으로 저장소를 읽는 것은 아니므로 읽은 파일과 담당 범위를 확인합니다.

### API 사전 준비도 담당 작업에 포함합니다

승인·자료 협의가 필요한 서비스는 개발과 병행해 준비합니다. **[담당별 신청 링크·절차·우선순위](docs/team/api-onboarding.md)**와 **[신청 진행표](docs/team/api-access-status.md)**를 먼저 확인하세요. 민준은 HJNC·도로 자료와 키 신청, 길웅은 기존 지도·자료 출처 표시, 선효는 읽기 전용 연결·캐시·실패 상태, 대겸은 관측 비교·혼합 사례와 기존 문의 창구를 맡습니다. 기상·AIS·유료 추적은 조건부 후보입니다.

다음 담당 작업 세션에 보유 확인·신청·실응답 또는 막힌 이유와 다음 행동을 기록합니다. 실제 발급/응답 증거 없이 완료로 표시하지 않습니다. 본인 전용 키는 공유하지 않고, 유료 계약·새 외부 발송은 별도 요청 범위입니다. 승인 대기 중에도 연결 검사는 준비합니다.

### 기존 서비스와 비교하며 개발합니다

[서비스 비교·개발 적용 문서](docs/team/service-comparison.md)에 TIGER FACE·PortQM·PortWise와 유사 서비스의 공식 근거, 중복 기능, 미확인 사항을 정리했습니다. 네 파트 모두 자신의 적용사항을 확인합니다.

이번 프로젝트는 확인된 반입시간 변경이 기존 배차에 미치는 영향을 점검하고, 남은 작업의 처리 수준과 변경 부담을 비교하는 데 집중합니다. 지도·추적·자동배차 자체를 새로운 기능으로 주장하지 않습니다. 출발 작업 고정은 시제품의 범위이며, 내부 계획 승인은 터미널 예약 확정을 뜻하지 않습니다. 이 비교는 기존 API·DB 계약을 바꾸거나 구현 범위를 넓히는 지시가 아닙니다.

기존 TMS에서 내보낸 배차를 점검하는 보조 도구라는 도입 방향을 검토합니다. 먼저 모의 CSV·JSON으로 흐름을 만들고, 실제 내보내기·필드·사용 권한을 확인한 뒤 연결합니다. 기존 TMS로의 자동 반영이나 추가 도입 비용이 없다는 점은 보장하지 않습니다.

## 개발 문서

공통 문서를 먼저 읽고, 담당 문서와 같은 버전의 규격·예제를 함께 사용합니다.
팀에 전달한 PDF 원본을 그대로 보관했습니다.

| 문서 | 읽을 사람 | 분량 |
|---|---|---|
| [공통 개발 규격](docs/development/v0.1/00_%EB%B0%98%EC%9E%85%EB%A7%9E%EC%B6%A4_%EA%B3%B5%ED%86%B5%EA%B0%9C%EB%B0%9C%EA%B7%9C%EA%B2%A9_v0.1.pdf) | 전체 | 6쪽 |
| [프론트 작업 명세](docs/development/v0.1/%EB%8B%B4%EB%8B%B9%EB%B3%84%20%EB%AC%B8%EC%84%9C/01_%ED%94%84%EB%A1%A0%ED%8A%B8_%EC%9E%91%EC%97%85%EB%AA%85%EC%84%B8_v0.1.pdf) | 프론트 담당 | 3쪽 |
| [데이터 작업 명세](docs/development/v0.1/%EB%8B%B4%EB%8B%B9%EB%B3%84%20%EB%AC%B8%EC%84%9C/02_%EB%8D%B0%EC%9D%B4%ED%84%B0_%EC%9E%91%EC%97%85%EB%AA%85%EC%84%B8_v0.1.pdf) | 데이터 담당 | 3쪽 |
| [최적화 엔진 작업 명세](docs/development/v0.1/%EB%8B%B4%EB%8B%B9%EB%B3%84%20%EB%AC%B8%EC%84%9C/03_%EC%B5%9C%EC%A0%81%ED%99%94%EC%97%94%EC%A7%84_%EC%9E%91%EC%97%85%EB%AA%85%EC%84%B8_v0.1.pdf) | 최적화 담당 | 3쪽 |
| [API·통합 작업 명세](docs/development/v0.1/%EB%8B%B4%EB%8B%B9%EB%B3%84%20%EB%AC%B8%EC%84%9C/04_API%ED%86%B5%ED%95%A9_%EC%9E%91%EC%97%85%EB%AA%85%EC%84%B8_v0.1.pdf) | API·통합 담당 | 3쪽 |

- [전체 자료 읽는 순서](docs/development/v0.1/%EB%A8%BC%EC%A0%80_%EC%9D%BD%EA%B8%B0.txt)
- [OpenAPI 명세](docs/development/v0.1/%EA%B3%B5%ED%86%B5%20%EA%B7%9C%EA%B2%A9/openapi.yaml) · [JSON 형식](docs/development/v0.1/%EA%B3%B5%ED%86%B5%20%EA%B7%9C%EA%B2%A9/openapi.json)
- [공통 JSON Schema](docs/development/v0.1/%EA%B3%B5%ED%86%B5%20%EA%B7%9C%EA%B2%A9/contracts.schema.json)
- [DB 스키마](docs/development/v0.1/%EA%B3%B5%ED%86%B5%20%EA%B7%9C%EA%B2%A9/schema.sql) · [DB 필드사전](docs/development/v0.1/%EA%B3%B5%ED%86%B5%20%EA%B7%9C%EA%B2%A9/DB_%ED%95%84%EB%93%9C%EC%82%AC%EC%A0%84.tsv)
- [업무 의미 검증 규칙](docs/development/v0.1/%EA%B3%B5%ED%86%B5%20%EA%B7%9C%EA%B2%A9/%EC%9D%98%EB%AF%B8%EA%B2%80%EC%A6%9D_%EA%B7%9C%EC%B9%99.txt)
- [모의 예제와 기대결과](docs/development/v0.1/%EC%98%88%EC%A0%9C%20%EB%8D%B0%EC%9D%B4%ED%84%B0) · [검수 기록](docs/development/v0.1/%EA%B2%80%EC%88%98)

## 먼저 만들 기능

1. 배차 입력과 확인된 반입시간 변경을 등록합니다.
2. 영향 작업과 고정 작업을 확인합니다.
3. 원안과 조정안의 미처리·변경량·이동 부담을 비교합니다.
4. 해결되지 않은 작업과 근거를 보여줍니다.
5. 최신 입력·계획 버전을 다시 확인한 뒤 내부 계획을 승인합니다.

첫 범위는 단일 운송사의 일반 수출 Dry 컨테이너 작업과 지정 장소 복귀입니다.
지도·선박/화물 추적·기상·알림은 이 흐름을 돕는 보조 기능으로 검토합니다.
선박 ETA가 바뀌었다는 이유만으로 반입마감이나 지연 원인을 확정하지 않습니다.

## 초기 개발 담당 · 2026-11-07

| 담당 | 파트·문서 | 맡을 일 |
|---|---|---|
| 최길웅 | 프론트 · 01 | 한 화면에서 변경 근거·배차 비교·미해결 이유·실행 상태 확인, API 연결 |
| 심민준 | 데이터 · 02 | 입력 변환·검증·표준화, 출처·갱신시각·사용량, 시나리오와 예상 판정 |
| 황대겸 | 최적화 · 03 | 고정 조건을 지키는 조정안, B0~B3 비교와 미해결 설명 |
| 안선효 | API·DB·통합 · 04 | 실행·조회·승인, 버전 관리, DB 저장과 독립 일정 검증 |

공통 개발 규격 00은 네 명 모두 읽습니다. [역할표](docs/team/roles.md)에 첫 작업·산출물·담당 경계가 있습니다.
배포 PDF의 담당 미정 문구는 작성 당시 상태이며 현재 담당은 위 표와 역할표를 따릅니다.
Python 백엔드 하나 안에서 모듈을 나누며, 프론트 첫 구현은 React·TypeScript·Vite를 사용합니다.
최적화 조건은 공동 검토하고, 각자 자기 파트 연결·검증·보고서 부분을 작성합니다.

## 팀

**[리뷰·병합 기준](docs/team/review-policy.md):** 작은 변경은 작성자가 검사 후 병합합니다. 큰 기능·파트 연결·중요한 공통 변경만 관련자가 1회 검토하고, 피드백 수정·검사 후에는 재검토나 추가 승인을 기다리지 않습니다. 담당은 역할표에서 확인하며 자동 전체 리뷰 요청은 사용하지 않습니다.

**반입맞춤 · 국립창원대학교 컴퓨터공학과**

| 이름 | 구분 | GitHub |
|---|---|---|
| 황대겸 | 팀장 · 최적화 | [@unknownamed](https://github.com/unknownamed) |
| 최길웅 | 프론트 | [@choigilung](https://github.com/choigilung) |
| 심민준 | 데이터 | [@S-minjun](https://github.com/S-minjun) |
| 안선효 | API·DB·통합 | [@He6venly](https://github.com/He6venly) |

## 검수 재실행

Python 3.12 기준입니다. 별도 가상환경에서 아래 명령을 실행합니다.
아래 명령은 계약·예제·메모리 DB와 데이터 입력·로컬 API·엔진을 검사합니다. 프론트 검사는 `frontend/README.md`를 따릅니다. 외부 API는 호출하지 않습니다.

```sh
python -m pip install -r requirements-dev.txt
python tools/check_development.py
python -m pytest -q
```

원본을 보존하도록 임시 복사본에서 검사합니다. PR과 `main` 변경 시 GitHub Actions도 같은 검사를 수행합니다.
실행 결과는 [Actions](https://github.com/unknownamed/banipmatch/actions)에서 확인합니다.
현재 CI와 역할별 검토 담당 설정은 실제 앱 검증이나 필수 승인·병합 차단 설정을 뜻하지 않습니다.

## 데이터와 결과를 읽을 때

- 개발 예제는 모두 모의 자료입니다. 실제 운송사 배차표와 차량 GPS는 아직 확보하지 못했습니다.
- 설명용 결과(`illustrative_fixture`)는 수작업 예시이며 실제 계산 성능·최적성의 근거로 쓰지 않습니다.
- 참고 근거의 HJNC 파일은 공개 스케줄 조회 요약과 예시 1행입니다. 전체 응답 원본이나 API 이용 승인 증빙은 아닙니다.
- 실자료 연결 전에는 이용 권한·응답 필드·최신성·호출 한도를 확인합니다.
- 내부 계획 승인과 외부 예약 변경·기사 통보는 별도입니다. 현재 규격은 외부 행동을 비활성화합니다.

## 보고서·발표에서 연결할 주소

프로젝트 저장소: **https://github.com/unknownamed/banipmatch**

현재 보관된 산출물은 개발 문서·규격·모의 예제, 로컬 API·저장 코드, B0~B3 코드·계산 결과, 프론트 설명용 비교 화면입니다.
최종 대회 보고서와 발표자료는 완성 후 [문서 목록](docs/README.md)에 추가합니다.
보고서 제출 시에는 해당 시점의 커밋 또는 태그 주소를 함께 적어, 어떤 버전을 사용했는지 확인할 수 있게 할 예정입니다.

현재 저장소는 **비공개**로 운영합니다. 외부 열람이 필요하면 팀원 접근 권한과 공개 범위를 먼저 정합니다.
완성 후 공개 전환 및 라이선스는 별도로 결정합니다.

## 저장소 구성

```text
README.md
AGENTS.md              # AI 공통 기준
CLAUDE.md              # Claude Code에서 공통 기준 읽기
CONTRIBUTING.md        # 도구별 시작·PR·검수·인계
.github/               # Copilot 안내·CODEOWNERS·PR 양식·CI
.cursor/rules/         # Cursor에서 공통 기준 읽기
tools/                 # 원본을 보존하는 검수 실행 도구
backend/               # 데이터·API·DB 로컬 모의 구현과 B0~B3 엔진
frontend/              # 설명용 비교 화면·상태 표시
tests/                 # API·DB·엔진 동작과 실패 경계 검증
requirements.txt       # API 실행 의존성
requirements-dev.txt   # 개발·검수 의존성
docs/
  README.md
  team/                # 역할·현재 상태·인계 양식
  experiments/         # 모의 실계산 결과와 해석
  development/v0.1/
    공통 개발 규격 PDF
    담당별 문서/       # 프론트·데이터·최적화·API·통합
    공통 규격/         # OpenAPI·JSON Schema·SQL·필드사전
    예제 데이터/       # 모의 입력·결과·오류 사례
    참고 근거/         # HJNC 공개 조회 요약
    검수/              # 검수 기록·재실행 스크립트
```
