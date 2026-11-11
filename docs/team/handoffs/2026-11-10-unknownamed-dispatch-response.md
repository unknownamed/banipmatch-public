# 대겸 인계 — 담당자 대응 명세와 확인 안내

기준 main `29fdbfb`, 작업 `codex/unknownamed-web-push`. 최신 범위는 [담당자 대응 완료 기준](../dispatcher-response-scope.md), 추적은 [#57](https://github.com/unknownamed/banipmatch/issues/57)이다.

## 구현한 부분

- `tools/dispatch_response.py`: 입력 의미·실계산 조정안·독립 일정 재검사 후 변경 전후와 차량별 명세·미해결 확인 안내를 생성한다.
- 차량 재배정은 기존/새 차량 양쪽에 포함하고, 원안 배정이 미처리가 된 건은 실제 운송 취소로 표시하지 않는다. 고정 작업 변경은 재검사에서 거절한다.
- 안내는 원래 오류 코드·설명·proof_level·evidence_refs를 보존한다. 추가 차량 확보·준비 완료·마감 연장·원인 확정을 자동으로 만들어내지 않는다.
- 지표의 시간 변경 허용오차와 전달할 정확한 시각 차이는 구분한다. 작은 시각 변화도 변경 명세에 나타나며 최적화 KPI 자체는 변경하지 않는다.
- `bind_archived_approval(snapshot, results, plan, approval)`은 보존한 입력 해시·실행ID·계획/승인ID·버전·방법·배정 일치를 확인한다. 파일의 일관성 검사는 서버의 현재 승인/전송 권한이 아니므로 항상 `delivery_authorized=false`다.

## 사용

기존 `requirements-dev.txt` 환경에서 저장소 루트:

```powershell
python -m tools.dispatch_response --snapshot local/input.json --result local/method-result.json --output local/response-preview.json
python -m pytest -q tests/test_dispatch_response.py
```

`--result`는 독립 검사를 거쳐 `validation_status=passed`/`approval_eligible=true`가 된 단일 `MethodResult`다. 이 플래그를 임의로 바꿔 통과시키지 않는다. 도구도 일정을 다시 검사한다. 설명용 결과·B0·검사 전/실패는 거절한다. 저장된 과거 입력은 이력 검토용으로 허용하지만 실제 발송에는 최신 DB/시각/권한을 다시 검사해야 한다. 출력은 새 파일만 만들며 덮어쓰지 않는다.

네트워크 호출·새 계획 저장·문자/푸시 발송·연락처 수집이 없다. 개인 채팅 원문이나 미검토 서버 초안을 공유 저장소에 넣지 않았다.

[실행 예제](../../experiments/dispatch-response-2026-11-10/README.md)에 B1 실계산 결과와 대응 명세·해시를 인계했다. J1/J2 차량 변경, J3 준비 지연 미처리와 확인할 사항, J0 고정 유지를 대조했다. 과거 모의 예제의 로직 실행이며 실제 사용자 승인·현재 계획·외부 전송이 아니다.

## 다음 담당 연결

- 선효 #54: 이 명세를 검토해 API/DB 새 계약과 현재 계획 검증·수신자 매핑·전송/응답 이력을 연결한다. 로컬 파일 산출물 자체를 전송 승인으로 취급하지 않는다.
- 길웅 #55: `changes`, `vehicle_changes`, `followups`, `limits`를 화면 설계에 사용하되 임시 JSON 형식을 확정 API라고 가정하지 않는다. 대상자 명단은 별도 매핑이며 차량ID만으로 기사 신원을 결정하지 않는다.
- 민준 #56: 보완 전후 입력·미해결·수신 실패/응답 사례를 대조한다.
- 대겸: 위 구현을 합친 뒤 실제 조건 편집→재계산→확정→휴대폰→응답까지 최종 검증한다. 이 인계만으로 전체 기능을 완료 처리하지 않는다.

## 검사

신규 회귀 19개 통과: 설명용/검사 전 거절, 고정 변경 차단, 양쪽 재배정, 미처리 보존, 작은 시각 변화, 신규/무변경, 승인 연결 오류6종, 원본 불변/결정성, 파일 덮어쓰기 방지, 다른 운영체제에서 받는 인계물의 해시·내용 재현. 추가 관련 회귀·CI 결과는 PR에 기록한다. 실제 휴대폰·웹 화면·공개 서버 검수는 아직 수행하지 않았다.

관련 일정/지표 회귀까지 41개·하위26개 통과. 좁은 보조 코드 검토에서도 재현 가능한 오류는 발견되지 않았다. 핵심 구현·수정·검증 판정은 대겸 작업에서 수행했다. 이는 API/DB 연결 단계에서 필요한 담당자 검토를 대신하지 않는다.
