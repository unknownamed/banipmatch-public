# 보고서·코드/데이터 검토본 재현 안내

현재 패키지는 **검토본**이다. 최종 보고서·실제 연결·공개 배포·휴대폰 전달 완료를 뜻하지 않는다. 최신 완료 범위는 [담당자 대응 R1~R8](../team/dispatcher-response-scope.md)과 [완료 계획](../team/completion-plan.md)이다. 서버·주소·실제 배포는 황대겸 본인이 직접 한다.

## 받는 사람: ZIP을 새 폴더에 풀어서 확인

ZIP 안 `banipmatch`가 작업 루트다. 소스/계약·모의 입력·동결 결과·합성 공급자 예제·검사 코드·보고서와 빌드 메타데이터가 포함된다. `.git`, 개인키/실제 `.env`, 로컬 DB, 실제 원문·개인 자료, 가상환경/node_modules·생성 빌드는 넣지 않는다. `.env.example`은 빈 값/예시만 담은 설정 설명이다.

먼저 Python 3.12 이상에서 의존성 설치나 서버 실행 **전** 파일 무결성을 검사한다.

```powershell
python tools/check_submission.py --files-only
```

이 검사는 파일별 바이트/해시·누락/추가·보고서와 소스 커밋을 대조한다. 별도 제공된 ZIP SHA-256과도 비교한다. 자체 manifest는 디지털 서명이나 배포자 신원 인증이 아니다.

검사 후 ZIP을 푼 폴더 **밖**에 Python 환경을 만든다. 데이터 검수 의존성도 함께 설치한다.

```powershell
python -m venv ../banipmatch-verify-env
..\banipmatch-verify-env\Scripts\python.exe -m pip install -r requirements-dev.txt -r backend/data/requirements.txt
```

외부 환경으로 다음 검사를 실행한다. 패키지 안에 `.venv`나 npm 의존성을 설치하면 파일이 늘어나 전체 무결성 검사가 추가 파일을 보고 실패하므로, 무결성 검사는 먼저 수행한다.

```powershell
# 패키지 밖에 준비한 환경을 사용한다. 솔버를 다시 실행하지 않는 80회 감사다.
..\banipmatch-verify-env\Scripts\python.exe tools/check_submission.py
..\banipmatch-verify-env\Scripts\python.exe tools/check_development.py
..\banipmatch-verify-env\Scripts\python.exe -m pytest -q --ignore=tests/engine/test_showcase_evidence.py --ignore=tests/engine/test_evaluation.py
```

위 pytest는 Git 이력 의존 모듈 두 개를 명시적으로 제외한 **패키지 회귀 검사**다. 원본 Git 저장소에서 실행하는 전체 검사와 같은 개수라고 주장하지 않는다. 두 모듈을 삭제하거나 테스트를 통과하도록 약화하지 않았으며, 제출 ZIP에도 소스를 보존한다. 원본 저장소 전체 검사는 기존 `python -m pytest -q`와 CI를 따른다.

기존 `tools/build_showcase_evidence.py --check`와 일부 평가 실행 도구는 역사 커밋에 `git show`를 수행한다. ZIP에는 Git이 없어 해당 명령 대신 `tools/check_submission.py`가 `submission-evidence/historical/0d2640b.../`의 21개 과거 소스 해시, 동결 기록/입력과 조정 일정·원안 무결성을 검사한다. 과거 소스를 현 버전으로 치환하거나 80회 솔버를 재실행하지 않는다. 새 평가·프로파일링은 원본 Git 체크아웃에서 소스 이력과 함께 실행한다.

프론트는 Node.js 24와 npm으로 확인한다. npm 설치 이후에는 원본 ZIP을 별도 추출해 무결성 검사를 재실행한다.

```powershell
cd frontend
npm ci --ignore-scripts
npm test
npm run build
```

실제 로컬 앱 실행은 [backend/README.md](../../backend/README.md), [frontend/README.md](../../frontend/README.md)를 따른다. 이 안내는 서버를 자동 시작하거나 공개하지 않는다. 공통 모의 토큰·loopback 제한을 해제해 인터넷에 바로 노출하면 안 된다. 제공기관 키 없이도 모의 계산·기존 결과 감사를 확인할 수 있으며 실제 자료 연동은 소유자 권한·설정·검증이 별도로 필요하다.

## 만드는 사람: 같은 커밋의 PDF·ZIP 생성

작업을 커밋한 뒤 보고서를 생성하고, 같은 커밋을 ZIP으로 내보낸다. PDF와 ZIP을 만든 뒤 코드가 바뀌면 둘 다 새 버전으로 다시 생성한다. 기존 산출물을 덮어쓰지 않는다. 출력은 저장소 밖의 새 디렉터리를 권장한다.

```powershell
python -m pip install -r requirements-report.txt
python tools/build_submission_report.py --output ../release-review/반입맞춤_문제해결_보고서_검토본.pdf
python tools/build_submission.py --ref HEAD --report ../release-review/반입맞춤_문제해결_보고서_검토본.pdf --report-meta ../release-review/반입맞춤_문제해결_보고서_검토본.build.json --output ../release-review/반입맞춤_코드_데이터_검토본.zip
```

PDF 기본 폰트는 Windows 맑은 고딕이다. 다른 OS는 설치된 한글 TrueType 폰트를 `--font`, `--bold-font`로 지정한다. 폰트 파일 자체를 ZIP에 복사하지 않는다. PDF 생성 후 페이지 PNG를 렌더해 표/줄바꿈/도표/한글·링크를 직접 검사한다. builder는 10쪽 구성을 확인하며 표지·참고문헌 포함20쪽 상한보다 작다. 분량을 맞추려 빈 내용을 늘리지 않는다.

보고서는 검증된 기존 원시 자료에서 표·그림을 만들며 구현 중인 부분을 명시한다. `report-build.json`은 소스 커밋·보고서 해시·입력 해시를 연결한다. `submission-manifest.json`은 ZIP의 모든 파일·크기·해시와 제외 목록을 연결한다. 두 파일은 개인정보·인증정보를 기록하지 않는다.

## 최종본으로 바꾸기 전에

실제 연결·조건 재계산/전달·응답·공개 세션 보호·실기기 결과를 담당 인계와 대조한다. 보고서와 소스를 같은 최종 커밋으로 고정하고 PDF 전 페이지·ZIP 새 폴더 검사·실제 URL을 재검수한다. 현재 builder는 검토본만 생성하며, 완료 증거 없이 stage를 final로 바꾸지 않는다.

공식 보존 공고의 문제해결 제출은 보고서20쪽 이내 및 데이터/코드 등 일체, 11월13일14시다. 최신 공지·회신·수신처는 최종 제출 직전 다시 확인한다. PDF/ZIP/파일명은 팀 정리 방식이며 배포 URL로 코드 제출을 대신하지 않는다. 실제 메일 제출은 별도 사용자 요청 단계다.
