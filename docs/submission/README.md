# 제출 묶음(보고서·코드·데이터) 확인과 재현

제출물은 두 파일이다.

| 파일 | 내용 |
|---|---|
| `반입맞춤_문제해결_보고서.pdf` | 문제해결 보고서(20쪽 이내). 원고는 `docs/report/final/report.html` |
| `반입맞춤_코드_데이터.zip` | 같은 커밋의 소스·계약·모의 입력·실험 원자료·검사 코드·운영 설정 예시와 보고서 PDF |

운영 서비스: <https://banipmatch.duckdns.org> (배포 커밋은 ZIP의 `submission-manifest.json`의 `source_commit`과 같다).

## 받는 사람: ZIP을 새 폴더에 풀어서 확인

ZIP 안 `banipmatch` 폴더가 작업 루트다. `.git`, 실제 `.env`·키, 로컬 DB, 개인 자료, 가상환경·`node_modules`·빌드 결과는 넣지 않았다. `.env.example`, `deployment/cloud/*.example`은 빈 값·예시만 담은 설정 설명이다.

의존성 설치 **전에** 파일 무결성을 먼저 검사한다(Python 3.12 이상, 추가 패키지 불필요).

```powershell
python tools/check_submission.py --files-only
```

파일별 크기·해시, 누락·추가 파일, 보고서와 소스 커밋의 일치를 대조한다. 자체 manifest는 디지털 서명이 아니다.

검사 후 ZIP을 푼 폴더 **밖**에 Python 환경을 만들어 회귀 검사를 실행한다(폴더 안에 설치하면 파일이 늘어 무결성 검사가 실패한다).

```powershell
python -m venv ../banipmatch-verify-env
..\banipmatch-verify-env\Scripts\python.exe -m pip install -r requirements-dev.txt -r backend/data/requirements.txt -r requirements-workflow.txt
..\banipmatch-verify-env\Scripts\python.exe tools/check_submission.py
..\banipmatch-verify-env\Scripts\python.exe -m pytest -q --ignore=tests/engine/test_showcase_evidence.py --ignore=tests/engine/test_evaluation.py
..\banipmatch-verify-env\Scripts\python.exe tools/report_demo_scenarios.py        # 보고서 5.1 시연 사례 재계산
..\banipmatch-verify-env\Scripts\python.exe tools/check_engine_robustness.py .    # 보고서 5.2 무작위 입력 검사
```

제외한 두 시험 모듈은 Git 이력(과거 커밋)을 읽기 때문에 ZIP에서는 실행할 수 없다. 대신 `tools/check_submission.py`가 `submission-evidence/historical/0d2640b.../`에 담은 과거 소스 해시와 80회 실험 기록·입력의 무결성을 검사한다. 원본 저장소에서는 `python -m pytest -q`로 전체를 실행한다.

화면은 Node.js 24로 확인한다.

```powershell
cd frontend
npm ci --ignore-scripts
npm test
npm run build
```

직접 실행 방법은 저장소 [README](../../README.md), 운영 서버 구성은 [docs/deployment/production.md](../deployment/production.md)에 있다. 카카오 지도·웹 푸시 키가 없어도 배차 계산·조건 보완·확정은 동작한다.

## 만드는 사람: 같은 커밋으로 PDF·ZIP 생성

모든 변경을 커밋한 뒤 같은 커밋에서 PDF와 ZIP을 만든다. 코드가 바뀌면 둘 다 다시 만든다. 기존 산출물은 덮어쓰지 않는다(이미 있으면 도구가 멈춘다).

```powershell
python -m pip install pypdf
python tools/build_final_report.py --output ../release-final/반입맞춤_문제해결_보고서.pdf
python tools/build_submission.py --ref HEAD --report ../release-final/반입맞춤_문제해결_보고서.pdf --report-meta ../release-final/반입맞춤_문제해결_보고서.build.json --output ../release-final/반입맞춤_코드_데이터.zip
```

`build_final_report.py`는 Chrome 헤드리스로 보고서 HTML을 A4로 인쇄하고, 소스 커밋·PDF 해시·원고와 그림 파일 해시를 `.build.json`에 남긴다. `build_submission.py`는 이 기록이 묶을 커밋과 다르면 ZIP을 만들지 않는다. 이전 검토본 도구(`tools/build_submission_report.py`)도 그대로 동작한다.

제출: 2026-11-13 14:00까지 보고서 PDF와 코드·데이터 ZIP을 주최측 메일로 보낸다.
