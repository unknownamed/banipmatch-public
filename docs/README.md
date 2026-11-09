# 문서 목록

- [심사 대응 설계 보완서(PDF 4쪽)](design/evaluation-addendum-2026-11-08.pdf): 설계v6 유지, 증거·실험·담당별 완료 기준·전문가 질의 준비.

- [11월 8일 최신 엔진 인계](team/handoffs/2026-11-08-unknownamed-engine-diagnostics.md): 0.2.3 시간 초과 시 입력 누락 진단 보존·연결 담당 참고.
- [보고서용 실험 표·그림·PDF](experiments/engine-report-2026-11-08/README.md): 기존156회4쪽과 후속72회2쪽, 모의 결과와 남은 한계.
- [규모·예산·여유시간·혼합 조건156회 비교](experiments/engine-sensitivity-2026-11-08/README.md): 전체 결과와 재현 명령, 성공·미증명 범위.

## 팀 작업 안내

- [데이터 출처·모의 생성·대표 사례 근거](data/README.md) — 심민준 담당, 이용조건 공백·필드 대응·입력9종 재현 감사
- [고정 평가10종의 데이터 근거](data/evaluation-data.md) — 변경 전후20파일의 원본 해시·사건 범위·생성 재현 감사
- [심사 항목별 주장·증거 준비](team/evaluation-evidence.md) — 사용자 제공 심사표, 담당별 근거·부족 증거·완료 기준, 보고서20쪽/발표15쪽 구성안
- [현재 역할·담당 범위](team/roles.md) — 기존 01~04 명세와 담당 연결
- [현재 구현 상태](team/status.md) — 구현·미구현·보류 구분
- [리뷰·병합 기준](team/review-policy.md) — 필요한 변경에 관련자 1회 검토, 수정·검사 후 재승인 대기 없음
- [기존 서비스 비교·개발 적용사항](team/service-comparison.md) — 공식 근거·중복·미확인·네 파트 반영 기준
- [API 신청·사전 준비 안내](team/api-onboarding.md) — 담당·공식 링크·우선순위·승인/체험 조건
- [API 준비·신청 진행표](team/api-access-status.md) — 신청·승인·응답 확인 증거와 다음 확인일
- [AI 작업수칙](../AGENTS.md) · [AI 도구별 시작과 협업](../CONTRIBUTING.md)
- [작업 인계 양식](team/handoffs/TEMPLATE.md)

공유한 v0.1 PDF는 보존하며, 현재 담당은 위 역할표를 기준으로 합니다.

## 개발 초안 v0.1 · 2026-11-07

팀에 공유한 PDF 원본 5개와 같은 버전의 API·DB·예제·검수 자료를 보관합니다.

| 문서 | 대상 | 분량 |
|---|---|---|
| [공통 개발 규격](development/v0.1/00_%EB%B0%98%EC%9E%85%EB%A7%9E%EC%B6%A4_%EA%B3%B5%ED%86%B5%EA%B0%9C%EB%B0%9C%EA%B7%9C%EA%B2%A9_v0.1.pdf) | 전체 | 6쪽 |
| [프론트 작업 명세](development/v0.1/%EB%8B%B4%EB%8B%B9%EB%B3%84%20%EB%AC%B8%EC%84%9C/01_%ED%94%84%EB%A1%A0%ED%8A%B8_%EC%9E%91%EC%97%85%EB%AA%85%EC%84%B8_v0.1.pdf) | 프론트 담당 | 3쪽 |
| [데이터 작업 명세](development/v0.1/%EB%8B%B4%EB%8B%B9%EB%B3%84%20%EB%AC%B8%EC%84%9C/02_%EB%8D%B0%EC%9D%B4%ED%84%B0_%EC%9E%91%EC%97%85%EB%AA%85%EC%84%B8_v0.1.pdf) | 데이터 담당 | 3쪽 |
| [최적화 엔진 작업 명세](development/v0.1/%EB%8B%B4%EB%8B%B9%EB%B3%84%20%EB%AC%B8%EC%84%9C/03_%EC%B5%9C%EC%A0%81%ED%99%94%EC%97%94%EC%A7%84_%EC%9E%91%EC%97%85%EB%AA%85%EC%84%B8_v0.1.pdf) | 최적화 담당 | 3쪽 |
| [API·통합 작업 명세](development/v0.1/%EB%8B%B4%EB%8B%B9%EB%B3%84%20%EB%AC%B8%EC%84%9C/04_API%ED%86%B5%ED%95%A9_%EC%9E%91%EC%97%85%EB%AA%85%EC%84%B8_v0.1.pdf) | API·통합 담당 | 3쪽 |

[묶음 안내](development/v0.1/%EB%A8%BC%EC%A0%80_%EC%9D%BD%EA%B8%B0.txt) · [규격](development/v0.1/%EA%B3%B5%ED%86%B5%20%EA%B7%9C%EA%B2%A9) · [예제](development/v0.1/%EC%98%88%EC%A0%9C%20%EB%8D%B0%EC%9D%B4%ED%84%B0) · [검수](development/v0.1/%EA%B2%80%EC%88%98)

## 대회 최종 제출물

- 최종 보고서: 준비 중
- 최종 발표자료: 준비 중
- [로컬 API 실행 안내](../backend/README.md): 설명용 재생 또는 선택형 실계산·독립 검사·내부 승인. [PR12·14 통합 검수](team/handoffs/2026-11-08-pr12-pr14-integration.md)
- [데이터 입력 검증 안내](../backend/data/README.md): CSV·JSON 입력과 행별 오류, API 연결 시 지킬 경계
- [B2/B3 엔진 인계](team/handoffs/2026-11-07-unknownamed-engine-b2-b3.md): 최적화·단계별 판정·후속 연결
- [B0~B3 모의 비교](experiments/engine-b0-b3/README.md): 입력7종·결과·재현 명령·성능 한계
- [프론트 실행 안내](../frontend/README.md): 설명용 예제 비교·HTTP 입력 등록/실행·입력 오류 안내, 실계산 계약 표시 반영·전체 브라우저 검수는 후속
- [B0~B3 엔진 실행 안내](../backend/engine/README.md) · [B0/B1 최초 결과](experiments/engine-b0-b1/README.md): 초기 결과와 현재 엔진 버전을 구분, 현장 검증은 후속

현재 PDF를 최종 보고서나 실제 실행 성과로 표시하지 않습니다. 새 버전은 별도 폴더에 보관하고 이 목록과 루트 README의 링크를 함께 갱신합니다.

## 새 평가와 현장 문제 근거

- [80회 모의 평가·재현·한계](experiments/engine-evaluation-2026-11-08/README.md) · [PDF4쪽](experiments/engine-evaluation-2026-11-08/engine-evaluation-summary.pdf)
- [HJNC 공식 근거·심사 질문 준비](team/operational-evidence.md)
- [황대겸 평가 인계](team/handoffs/2026-11-08-unknownamed-evaluation.md)
