# 개인 계정으로 준비할 API

담당 이슈: [기상청·민준 #35](https://github.com/unknownamed/banipmatch/issues/35) · [AIS·선효 #36](https://github.com/unknownamed/banipmatch/issues/36) · [ORS·길웅 #37](https://github.com/unknownamed/banipmatch/issues/37).

확인일: 2026-11-09. 사용자가 도로공사 외에도 개인이 신청할 수 있는 API의 담당 배정을 요청했다. 여기서 개인 신청은 **사업자등록·기관 공문·영업 계약 없이 일반 개인이 진행하는 경로**를 뜻한다. 회원가입·본인 인증·약관·무료 한도는 서비스별로 적용된다.

기존 계정/키 보유를 먼저 확인하고 없으면 담당자가 본인 명의로 신청한다. 발급만으로 제품 채택·데이터 저장·공개 시연까지 허용됐다고 판단하지 않는다. 담당 배정 이후 기상청 본인 발급·활용신청·첫 응답도 확인했다. 서비스별 실제 진행은 아래 표와 API 진행표를 따른다.

## 바로 진행할 항목

| 항목 | 담당 | 신청 경로·최소 작업 | 현재 상태 |
|---|---|---|---|
| 도로공사 영업소간 통행시간 | 심민준 | [기존 #30](https://github.com/unknownamed/banipmatch/issues/30), [인증키 발급](https://data.ex.co.kr/openapi/apikey/requestKey). 기존 보유 확인→없으면 신청→구간/단위 검증 | 본인 발급·소량 응답 확인. [단위/품질·필요 구간 검증](../data/road-api-verification.md)은 남음 |
| 기상청 API허브 | 심민준 | [일반회원 가입](https://apihub.kma.go.kr/join.do)→본인 휴대전화 인증→키 확인→서비스별 활용신청→해양 관측/특보 작은 표본 | 본인 발급·활용신청 후 [3개 HTTP200 응답 검증](../data/kma-response-verification.md). 결측/조회 범위·공유 환경 등은 남음 |
| AISstream | 안선효 | [계정](https://aisstream.io/account)에서 본인 GitHub 로그인→키 생성→부산 신항 주변 짧은 서버 수신 시험 | 신규 신청 작업 배정, 발급/대상 해역 수신 미확인 |
| openrouteservice(ORS) Standard | 최길웅 / 선효 서버·대겸 적합성 협조 | [개인 가입](https://account.heigit.org/signup)→무료 Standard 키→공공 항만/도로 좌표의 거리·시간 수치 소량 검증 | 신규 준비 대상, 발급/부산 경로 품질 미확인 |
| 카카오맵 Web SDK | 최길웅 | 기존 앱/지도를 재사용. [개발자 콘솔](https://developers.kakao.com/)에서 기존 도메인·무료량 확인 | 로컬 표시 확인된 기존 항목, 재가입 불필요 |

신청이 막히면 담당자가 화면의 필요한 항목과 이유만 공유한다. 개인정보·비밀번호·OTP·키 값은 이슈·Git·채팅에 남기지 않는다. 허위 사업자/기관 정보로 신청하거나 무료 한도 우회용으로 여러 계정을 만들지 않는다. 유료 상품 전환·자동결제·신규 외부 메일·기사 연락은 이번 배정에 포함하지 않는다.

## 기상청 — 민준

- 일반회원은 일반국민 대상 온라인 **자동승인**이고 가입 때 인증키가 발급된다. 기관회원의 공문/관리자 승인을 신청하지 않는다. [가입 안내](https://apihub.kma.go.kr/join.do)
- API 이용에는 연락처 등록·문자 인증이 필요하다. 담당자가 본인 휴대전화로 처리한다. [공식 활용신청 안내](https://apihub.kma.go.kr/urlRedirect.do?seqApi=3&seqApiSub=249)
- 무료 일반회원 한도는 **일20,000건·5GB**이며 시스템 상황에 따라 변경될 수 있다. 본인 전용 키의 양도·대여는 금지다. 계정 소유자가 직접 허용 환경에서 사용하고, 팀에는 공개/공유 가능한 표본·매핑·검증 기록을 전달한다. 데이터별 공공누리 조건도 확인한다. [이용안내](https://apihub.kma.go.kr/apiInfo.do) · [약관](https://apihub.kma.go.kr/policy.do)
- 첫 범위는 [해양 종합 관측자료](https://apihub.kma.go.kr/apiList.do?seqApi=3&seqApiSub=249)의 `sea_obs.php`와 [특보현황](https://apihub.kma.go.kr/apiList.do?seqApi=10&seqApiSub=288)의 `wrn_now_data.php`다. 필요한 부산 인근 지점·특보구역을 확인해 소량 시험한다. 전체 전국/장기간 일괄 수집부터 시작하지 않는다.
- 관측의 지점·KST 시각·풍속(m/s)·파고(m), 특보의 구역·발표/발효시각과 수신시각을 구분한다. 관측/특보의 실제 필드와 결측 표현을 표본으로 검증한다. 악천후와 지연이 함께 있었다는 이유로 지연 원인을 확정하지 않는다.
- 완료 기준: 가입/발급/첫 응답 상태, 비밀값 없는 한도·약관 근거, 표본 필드·단위·시각·구역 검증. 키 발급만으로 완료하지 않는다. 팀 공용 서버에서 개인키를 운영할 수 있는지는 별도 확인한다.

## AISstream — 선효

- 공식 사이트는 **무료**, GitHub 로그인 후 계정에서 API 키 생성 절차를 안내한다. 별도 사업자등록·영업 계약 단계는 안내되어 있지 않다. 실제 계정 발급 성공은 담당자가 확인한다. [공식 시작 안내](https://aisstream.io/)
- 계정당 구독 연결3개·출발IP당 연결3개, 연결 뒤3초 내 구독, 연결당 구독 변경 초당1회 제한이 있다. 2026년9월부터 비압축 연결에 대역폭 제한을 적용한다고 안내하지만 수치 한도는 미공개다. 부산 신항 주변 좁은 해역·필요한 메시지로 시작하고, 시험 후 연결을 종료한다. [공식 명세](https://aisstream.io/documentation)
- 키는 서버 환경에 두고 **브라우저 직접 연결은 하지 않는다**. 초기 시험은 수신 상태·건수·시각·메시지 종류를 확인한다. 데이터 보관·공개 시연·재배포 범위를 확인하기 전 원본 대량 저장·공개를 시작하지 않는다.
- MMSI·위치·속도·방향·관측/수신시각과 정적 선박 정보의 연결 가능성을 확인한다. 선박 AIS가 트럭/개별 컨테이너 GPS는 아니다. 부산·중국 해역의 무중단 수신, 완전한 이력, ETA 정확도를 보장하지 않는다. 수신0건은 해당 구역에 배가 없다는 증거가 아니다.
- 완료 기준: 키 발급 여부, 정한 짧은 시험 구간의 수신/연결 종료, 누락·재접속·키 비노출 검사, 실제 제공 필드와 위치 신선도 확인. 키 값과 허가 불명 원본을 Git에 올리지 않는다.

## 바로 신청하는 목록에서 제외하는 항목

| 후보 | 이번 기준에서의 처리 |
|---|---|
| HJNC 연구 계정/API | 사업자 정보가 필요한 가입 경로를 학생에게 강제하지 않는다. 기존 공개표 검증과 이미 보낸 문의는 유지한다. 공개표 접근이 무제한 수집 허가라는 뜻은 아니다. |
| 체인포털/BPA OpenAPI | 일반회원 가입 가능성과 API 승인은 별개다. 현행 학생 API 자격/승인 절차가 미확인이므로 무심사 즉시 발급 목록에 넣지 않는다. 기존 문의·공개자료 검토를 유지한다. |
| SeaVantage | [공식 가격표](https://www.seavantage.com/pricing)에서 API는 영업 문의 항목이다. 웹 체험7일/10개를 무료 API 권한으로 해석하지 않는다. 기존 문의 회신은 계속 확인할 수 있다. |
| ShipsGo | 허용된 실제 화물 식별자/시험 크레딧·사용조건이 필요한 후보다. 우리 팀의 대상 표본이 없어 즉시 신청 필수로 배정하지 않는다. |
| SOLAPI | 실제 문자에는 발신번호 인증·비용·수신 동의가 필요하다. 이번 무료 자료 수집 신청과 분리하고 현재는 화면 알림으로 준비한다. |

## ORS Standard — 길웅, 선효·대겸 협조

- [공식 플랜](https://account.heigit.org/info/plans)의 Standard는 개인 누구나 무료로 이용하는 플랜이다. 공개 [가입 화면](https://account.heigit.org/signup)의 필수 항목은 이메일·이름·성·비밀번호·약관 동의이며 회사/사업자번호/카드 필드가 없다. 실제 가입 성공은 아직 확인하지 않았다. 별도 자격이 있는 Collaborative 플랜이나 유료 상품을 선택하지 않는다.
- Directions는 **일2,000건·분40건**, Matrix는 **일500건·분40건**으로 안내된다. Matrix 요청당 기본 출발×도착3,500셀, 동적 인수 사용 시25셀 제한이며 [공식 제한표](https://giscience.github.io/openrouteservice/hosted-api-restrictions)와 실제 계정 값을 함께 확인한다. 무료 한도를 넘기는 자동 유료 전환을 신청하지 않는다.
- 새 호출 기본 주소는 `https://api.heigit.org/openrouteservice/v2/`다. 구 주소 종료 일정이 2026년11월2~6일로 [공식 공지](https://ask.openrouteservice.org/t/deprecating-api-openrouteservice-org-in-favour-of-api-heigit-org/7912/)됐다. 오래된 코드의 `api.openrouteservice.org` 주소를 복사하지 않는다.
- 우선 Matrix **시간·거리 수치**를 검증한다. 영구 저장·재사용 질문에 운영자는 [서비스 약관 준수 조건으로 이용 가능](https://ask.openrouteservice.org/t/persistent-storage-and-reuse-of-matrix-api-duration-results/8010)하다고 답했다. 결과는 현행 [약관](https://account.heigit.org/info/tos)의 CC-BY-SA 4.0·출처/라이선스/변경 표시 등 공유 조건을 검토한다. 화면·관련 산출물에 `© openrouteservice by HeiGIT | Data from OpenStreetMap` 및 OpenStreetMap 연결을 표시한다. 이를 앱 전체 소스 공개 의무라고 단정하지 않는다.
- 경로선 geometry의 영구 저장·다른 지도 위 공개 표시는 [별도 문의로 안내된 사례](https://ask.openrouteservice.org/t/persistent-storage-and-commercial-reuse-of-directions-api-route-geometry/8057)가 있어 이번 숫자 표본 범위에 포함하지 않는다. 카카오 지도 위 경로선을 곧바로 겹쳐 공개하지 않는다.
- [화물차 옵션](https://giscience.github.io/openrouteservice/api-reference/endpoints/directions/routing-options)의 `driving-hgv`는 크기·중량 등의 조건을 지정할 수 있으나 OSM의 제한 정보에 의존한다. 부산항 대상 경로 연결·도로 최신성·실제 통행 가능 여부는 표본으로 별도 검증한다. 무료 API의 [실시간 교통 미제공 안내](https://ask.openrouteservice.org/t/can-ors-support-traffic/6139)도 확인했다. 시간값을 실제 트럭 GPS 도착시각이나 현재 교통이 반영된 실시간 ETA로 표시하지 않는다.
- API에 실제 기사/고객 개인정보를 보내지 않는다. 첫 검증은 공개 항만·도로 좌표를 사용하고 키를 프론트 번들·Git·채팅에 넣지 않는다. 계정 소유자가 허용 환경에 설정하고 팀 서버 이용 범위를 확인한다.
- 길웅 완료물: 기존 계정 확인/없으면 무료 Standard 신청, 키 값 없는 발급 상태·플랜/한도 확인. 선효는 서버의 소량 시험·실패/요청 제한, 대겸은 단위·구간 품질·화물차 조건과 결과 재사용 조건을 함께 검토한다. 무료 발급과 엔진/공개 지도 채택은 별도다.

## 카카오 자동차 길찾기에서 새로 확인한 제약

개인·학생의 비상업 테스트에서 무료량 내 사용 가능하다는 [공식 학생 답변](https://devtalk.kakao.com/t/api-directions-api/151192)과 [개인 개발자 답변](https://devtalk.kakao.com/t/topic/152563)이 있다. 그러나 후자는 **응답 저장을 허용하지 않는다**고 명시한다. 현재 우리가 보존하려는 거리/ETA·이동행렬·평가 입력에 곧바로 사용할 수 있는 자료로 선정하지 않는다. 캐시·로그·DB·보고서용 표본 파일로 남기는 절차도 기본 활성화하지 않는다.

또한 [공식 차종 답변](https://devtalk.kakao.com/t/car-type/147383)은 REST 오픈 API에서 중량·높이 제한 미지원, `car_type`은 통행요금 계산용이라고 설명한다. 일반 경로를 컨테이너 트럭 통행 적합성의 증거로 삼지 않는다. 기존 카카오맵 화면은 별개이며 그대로 활용한다. 새로운 앱 생성/별도 키 신청을 의무화하지 않는다.

## 팀 공통 완료 기준

`미확인 → 가입/발급 → 소량 응답 확인 → 의미·권한 검증 → 채택 판단`을 구분해 [진행표](api-access-status.md)와 담당 이슈에 기록한다. 막히면 구체적인 다음 행동을 남긴다. 각 API 키는 소유자와 약관 범위 내에서 사용한다. 허용된 출력 공유와 키 공유는 다르다.

신청 준비는 지금 병행하지만 모든 API의 제품 구현을 확정한 것은 아니다. 혼합 입력은 기존 [실자료 연결 기준](real-data-integration.md)을 따른다. 특히 현재 API의 `simulated` 전용 저장 제한을 우회하지 않으며, 실제 연결 변경은 관련자1회 검토 후 진행한다.
