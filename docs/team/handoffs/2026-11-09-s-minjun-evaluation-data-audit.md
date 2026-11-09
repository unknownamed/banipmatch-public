# 심민준 · 최신 평가 데이터 감사 보완

## 시작·확인한 남은 작업

브랜치 `codex/s-minjun-evaluation-data-audit`. 시작·PR 제출 전 원격을 fetch하여
main `f26352f`를 확인했고 그 버전에서 새 브랜치를 만들었다. 미커밋/타인 변경 없음.
열린 PR도 없어 중복 작업은 없었다. 최신 작업수칙·상태·역할·심사 근거와 평가 인계를 읽었다.

기존 데이터 근거는 개발용9종까지만 다뤘고 이후 추가된 평가10종과 변경 전 원안10종의
데이터 담당 감사가 연결되지 않았다. 해당 공백을 보완했다. 새 제품 기능·외부 자료 확보 작업이 아니다.

## 바꾼 것

- `tools/audit_evaluation_data.py`: 기존 프로토콜·전후20입력의 원본/정규화 해시, 사례ID·수량·모의 구분,
  변경 대상 창만 바뀌었는지, 이전 창 값·생성기 SHA·중복 사례를 확인. 솔버는 호출하지 않는다.
- `docs/data/evaluation-input-audit.json`:10사례/전후20입력 모두 정상. 일정 타당성·솔버 실행·외부 권한은
  이번 감사로 검증하지 않았다고 명시.
- `tests/data/test_evaluation_data_audit.py`: 신규11개.10쌍 생성 재현, 보관 보고서 대조,
  양쪽 원본 해시 변조·준비시각 동시 변경·잘못된 이전 창·누락·수량/ID·범위 밖 경로·중복·생성기 변경·출력 보존 검사.
- `docs/data/evaluation-data.md`: 생성값·전후 관계·기존80회/현장 검증의 구분·실제 미확보·한계와 재현 명령.
- 데이터 출처표와 문서 목록에 새 평가 및 기존 공식 공지 확인 기록을 연결.
  기존9종과 새10종은 분리하고 전후20파일을20개 독립 평가 사례로 세지 않도록 설명.

## 실제 검사

Windows Python3.13.7 개인 가상환경에서:

```sh
python tools/audit_evaluation_data.py --output docs/data/evaluation-input-audit.json
# valid=true / case_count=10 / snapshot_count=20 / valid_case_count=10
python -m pytest tests/data/test_evaluation_data_audit.py -q
# 11 passed / 12 subtests passed
python -m pytest -q
# 247 passed / 235 subtests passed
python tools/check_development.py
# 계약·예제29개 + DB32개 통과
git diff --check
# 오류 없음
```

보관 감사 파일은 새로 만들었으며 기존 개발용 감사·프로토콜·전후 입력·생성기·80회 결과는 수정하지 않았다.
전체 Python 검사에 기존 엔진 검사는 포함되지만80회 평가 실험을 다시 실행한 것은 아니다.

## 한계·검토·다음 작업

리뷰 불필요 — 담당 내부의 읽기 전용 데이터 감사와 근거 정리다. 제품 입력 판정·API·DB·공통 계약·솔버를 바꾸지 않는다.
정확한 head의 CI와 새 중요 지적을 확인하고 병합한 뒤 최종 main에서 감사 재산출·파일 트리를 대조한다.

입력 검증은 일정 독립 검사·최적성·현장 효과를 증명하지 않는다. 기존 원안 별도 검사와 결과 독립 검산은
기존 평가 기록을 그대로 참조한다. 해시 일치는 외부 원본 인증/권한이나 과거 동결 시점의 외부 증명도 아니다.

실제 배차 표본·허용된 API 전체 응답·자료 이용/보관/발표 조건·현재 시간대/누락률은 아직 증거가 부족하다.
외부 연락·가입·신청·수집은 이번 작업에서 하지 않았다. 근거 없이 확보 완료로 갱신하지 않는다.
후속 자료를 받으면 원본·이용조건·필드·단위를 기록해 모의 가정과 구분한다.
