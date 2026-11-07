# 팀 개발과 AI 사용 안내

ChatGPT·Claude 등 특정 구독으로 통일하지 않습니다. 같은 저장소, 역할표, 계약과 예제를 기준으로 작업합니다. AI가 저장소를 읽을 수 있는 방식인지는 각자 확인합니다.

## 시작 순서

1. 비공개 저장소 초대를 수락하고 자신의 PC에 저장소를 복제하거나 최신 파일을 받습니다.
2. [README](README.md), [공통 AI 지침](AGENTS.md), [역할표](docs/team/roles.md), [현재 상태](docs/team/status.md)를 읽습니다.
   [리뷰·병합 기준](docs/team/review-policy.md)에서 이번 변경에 사람의 검토가 필요한지도 판단합니다.
   [기존 서비스 비교](docs/team/service-comparison.md)의 공통 결론과 본인 파트 적용사항도 확인합니다. 제품 비교 근거와 현재 구현 계약을 구분합니다.
3. 개발 PDF 00과 자신의 01~04 담당 문서, 관련 규격·예제를 AI에도 전달합니다. PDF를 읽지 못하면 역할표에 연결된 동일 본문 JSON을 사용합니다.
4. 먼저 작은 예제 한 건을 연결합니다. 실제 외부 API 승인이나 키를 기다리며 개발 전체를 멈출 필요는 없습니다.
5. [API 신청 안내](docs/team/api-onboarding.md)에서 본인 담당 A/B 준비를 병행하고 [진행표](docs/team/api-access-status.md)에 상태·근거·다음 확인일을 남깁니다. C 후보도 조건은 미리 확인하되 기간제 체험·과금·발송은 정해진 단계에서 진행합니다.

## 도구별로 지침 전달하기

| 사용 방식 | 저장소에 둔 진입점 | 팀원이 확인할 것 |
|---|---|---|
| Codex | 루트 `AGENTS.md` | 이 저장소를 작업 폴더로 열고 읽은 지침을 확인 |
| Claude Code | 루트 `CLAUDE.md` → `AGENTS.md` 가져오기 | 저장소에서 시작하고 공통 지침과 담당을 읽었는지 확인 |
| GitHub Copilot | `.github/copilot-instructions.md` | 사용하는 환경의 저장소 지침 지원·설정 확인 |
| Cursor | `.cursor/rules/project.mdc` | 프로젝트 규칙 활성 상태 확인 |
| 일반 ChatGPT·Claude 웹 채팅 등 | 아래 시작 문구와 관련 파일을 직접 전달 | 비공개 GitHub 링크만 붙여서는 파일을 읽지 못할 수 있음 |

지침 파일은 AI에게 기준을 전달하는 장치입니다. 모든 도구가 자동으로 읽거나 항상 준수한다는 보장은 없으므로, 첫 답변에서 읽은 파일·담당·첫 작업을 확인합니다. Code용 지침 파일이 일반 웹 채팅에도 자동 적용되는 것은 아닙니다. 계정·구독이나 API 키를 서로 공유할 필요는 없습니다.

### AI에게 보낼 시작 문구

```text
나는 반입맞춤 팀의 [이름]이고 [파트]를 맡고 있어.
이 저장소의 AGENTS.md, README.md, docs/team/roles.md,
docs/team/status.md와 관련 인계 기록을 읽어줘.
docs/team/review-policy.md에 따라 작은 변경은 자체 검사 후 병합하고,
큰 변경만 관련자에게 1회 검토 요청해줘. 피드백 수정·검사 후에는 재승인을 반복해서 기다리지 마.
docs/team/service-comparison.md의 공통 결론과 내 파트 적용사항을 확인하고,
기존 서비스와 겹치는 기능·미확인 사항·시제품 범위를 지켜줘.
외부 API 준비는 docs/team/api-onboarding.md와 api-access-status.md에서
내 담당·이미 신청한 상태·다음 확인할 일을 먼저 확인해줘.
공통 개발 규격 00과 내 담당 명세, 같은 버전의 규격·예제도 확인해줘.
읽은 파일, 내 담당 범위, 현재 구현 상태와 첫 작업을 짧게 정리한 뒤
[이번에 만들 기능]을 구현하고 확인해줘.
공통 계약을 임의로 바꾸지 말고, 필요한 변경은 영향과 근거를 알려줘.
모의 결과와 실계산을 구분하고 작업 결과·검증·남은 일을 인계 기록에 남겨줘.
파일에 접근할 수 없으면 읽었다고 하지 말고 필요한 파일을 알려줘.
```

웹 채팅을 쓰는 경우 `AGENTS.md`, 역할표·상태, 리뷰·병합 기준, 서비스 비교, 공통/담당 문서를 먼저 전달하고 관련 코드·규격을 추가합니다. 저장소 전체나 비밀값을 무조건 업로드하지 않습니다. 웹 채팅에서 받은 코드는 본인 작업 브랜치에 적용하고 직접 실행해 확인합니다.

## 브랜치와 PR

- 작업 전 최신 `main`과 기존 변경을 확인합니다. 작업별 `codex/<담당>-<작업>` 브랜치를 사용합니다. 예: `codex/s-minjun-csv-validation`.
- 짧은 기능 단위로 PR을 엽니다. 작은 담당 내부 변경은 자체 검사 후 병합하며, 큰 기능·파트 연결·중요한 공통 변경만 관련자가 1회 검토합니다. 두 담당자의 판단이 꼭 필요할 때만 2명 요청합니다. 상세 기준은 [리뷰·병합 기준](docs/team/review-policy.md)을 따릅니다.
- 지적 사항을 수정하고 관련 검사·CI가 통과하면 추가 Approve나 재검토 요청 없이 병합합니다. 알려진 중요한 오류와 검사 실패는 먼저 해결하고, 지적별 수정·검사 근거를 PR에 남깁니다.
- 병합 중 발견한 오류는 병합 담당 AI가 직접 수정·검사해 main에 반영할 수 있습니다. 변경 이력을 남기고 다른 사람의 작업을 보존하며, 무관한 기능 추가나 공통 계약 변경까지 포함하지 않습니다.
- [.github/CODEOWNERS](.github/CODEOWNERS)의 자동 요청 패턴은 비활성화했습니다. 경로별 담당은 역할표에 있으며, 필요한 사람에게만 직접 요청합니다. 실제 브랜치 보호·필수 검사 설정은 변경하지 않습니다.
- 최초 협업 규칙 등록 이후 구현부터 이 흐름을 사용합니다. 강제 푸시·다른 사람 변경 취소·자동 병합을 기본으로 삼지 않습니다.

## 로컬 검수

Python 3.12의 개인 가상환경에서 저장소 루트 기준으로 실행합니다.

```sh
python -m pip install -r "docs/development/v0.1/검수/requirements-validation.txt"
python tools/check_development.py
```

검사 도구는 버전 문서의 임시 복사본에서 기존 계약·예제 29개와 DB 32개 검사를 실행하고 실패 시 종료합니다. 생성 보고서와 임시 DB는 원본을 덮어쓰지 않습니다. 현재 검사는 실제 엔진·웹앱·보안·운송 성과를 검증하지 않습니다.

GitHub Actions에도 같은 검사를 연결합니다. 실제 실행 결과는 PR의 Checks 또는 저장소 Actions에서 확인합니다. 변경에 맞는 검사·CI는 통과해야 하며, 사람의 검토는 위 기준에 해당할 때만 1회 받습니다. 코드가 생기면 해당 기능의 정상·실패 검사를 추가하며, 문서 교정만으로 불필요한 테스트를 늘리지 않습니다.

## 작업이 끝나면

- PR에 바꾼 행동, 사용한 규격 버전, 실제 검사 결과, 남은 일과 검토할 사람을 적습니다.
- AI 세션이나 담당자가 바뀌면 [인계 양식](docs/team/handoffs/TEMPLATE.md)을 복사해 `날짜-담당-작업.md`로 기록합니다. PR에 같은 정보가 있으면 인계에는 링크와 핵심만 남깁니다.
- 공통 상태가 달라질 때만 [현재 상태](docs/team/status.md)를 갱신합니다. 모든 사람이 매 작업마다 같은 상태 파일을 수정할 필요는 없습니다.
- 채팅 원문·서명·연락처·키·허가 없는 실제 자료는 공유 Git에 올리지 않습니다. 공유 기록에는 결정, 출처, 가정, 검증과 다음 작업을 남깁니다.
- 각자 자신의 보고서·발표 부분과 검증 근거를 준비합니다. 팀장이나 통합 담당에게 미완성 기능 전체를 넘기지 않습니다.

## 지침 형식 확인에 사용한 공식 자료

확인일: 2026-11-07. 도구별 기능 지원은 사용 환경에 따라 확인합니다.

- [OpenAI — AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Claude Code — CLAUDE.md와 파일 가져오기](https://code.claude.com/docs/en/memory)
- [GitHub Copilot — 저장소 지침](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions)
- [Cursor — 프로젝트 규칙](https://cursor.com/docs/rules)
- [GitHub — CODEOWNERS와 적용 조건](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
