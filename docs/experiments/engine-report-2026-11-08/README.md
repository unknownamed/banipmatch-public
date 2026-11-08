# 엔진0.2.1 · 기존156회 모의실험 보고서 자료

최종 대회 보고서(20쪽 이내)에 필요한 부분을 골라 삽입할 수 있는 4쪽 실험 요약입니다. 흑백·짙은 초록을 사용했습니다. 이 폴더는 기존 엔진0.2.1 결과만 다루며 후속 성능 개선 실험과 혼합하지 않습니다.

## 산출물

- `engine-experiment-summary.pdf`: 실험 설계, 규모/예산, 혼합/고정, 여유시간 및 한계의 4쪽 요약.
- `01_scale.png` / `.svg`: 20건의 변경 수와 실측 호출 시간.
- `02_mixed.png` / `.svg`: 같은 입력·처리 수준에서의 변경 수 비교.
- `03_buffer.png` / `.svg`: 여유시간별 변경 수와 미처리 수.
- `verified_runs.csv`: 원본156행에서 대조·추출한 주요 지표. 원본 전체 결과를 대체하지 않음.
- `summary.csv` / `.json`: 묶음·입력·여유·예산·방법별52개 집계(반복/시드 최소·중앙·최대, 증명 수).
- `source_manifest.json`: 사용한 원본 파일의 SHA-256. 엔진 소스가 후속 작업에서 바뀌어도 과거 결과를 현재 소스로 재생성한 것처럼 설명하지 않음.
- `checks.json`: 이번 재집계의 원본 대조 범위.
- `page-1.png` ~ `page-4.png`: PDF 전페이지 시각 검토용 렌더.

## 원본과 재현

원본은 `../engine-sensitivity-2026-11-08/{scale,mixed,buffer}/`의 `results.jsonl`, `runs.csv`, `metadata.json`입니다. 입력은 같은 실험 폴더의 `inputs/` 및 `../engine-b0-b3/inputs/`에 있습니다. 모두 보존했으며 새 솔버 실험은 실행하지 않았습니다.

저장소 루트에서 Python3.12, matplotlib, reportlab, Windows 맑은 고딕을 사용합니다.

```powershell
python tools/build_engine_report.py
python tools/build_engine_report.py --pdf
```

기본 실행은 원본 검증·집계·그림만 생성합니다. `--pdf`는 PDF도 생성합니다. 재실행 시 이 폴더의 파생 산출물은 갱신되며 원본 실험은 읽기만 합니다. 로컬 `_runtime/`는 필요한 matplotlib만 설치한 공유 제외 의존성 폴더입니다. 일반 환경에서는 해당 라이브러리를 별도 환경에 설치하면 됩니다.

## 검증과 해석

156행의 미처리·변경·이동·위반·잔여위험·호출시간·단계상태를 CSV와 JSONL 간 대조했습니다. 입력 원본과 각 여유시간 변형의 정규 JSON 해시를 메타데이터/실행 기록과 대조했습니다. PDF에 표시한 결과값은 해당 모든 반복/시드의 최소·최대와 별도로 대조합니다. 전체 PDF4쪽을 Poppler로 렌더하고 시각 확인했습니다.

이는 과거 결과의 정합성 확인이며 새 엔진 실행·API 독립 일정 검사·현장 검증이 아닙니다. 모든 결과는 `validation_status=not_run`, `approval_eligible=false`입니다. 모의 모집단이나 상용 우위를 주장하지 않으며, 처리량이 다른 이동량을 개선률로 비교하지 않습니다. 50건은 첫 목적단계UNKNOWN과 초기안 유지를 함께 표시합니다.

## 별도 후속 보완: 엔진0.2.2

`engine-performance-followup.pdf`는 0.2.2 후속72회를 기존156회와 분리해 비교한2쪽 자료입니다. 기존4쪽 PDF는 변경하지 않았습니다. `04_followup_20jobs.png/.svg`는20건B3 전체 호출 시간 비교 그림입니다. `followup_verified_runs.csv`, `followup_summary.csv/.json`, `followup_source_manifest.json`, `followup_checks.json`은 후속 전용 기록입니다.

```powershell
python tools/build_engine_report.py --followup
```

후속 원본은 `../engine-profile-2026-11-08/after-scale/`48회, `after-mixed/`24회이며 두 메타데이터의 completed=true를 확인했습니다. 진단4회는 시간 비교표에 합치지 않았습니다. 각 진단의 profile.json 해시는 별도 보존했습니다. 전체 후속PDF2쪽도 Poppler로 렌더·시각 확인했습니다.

같은3/10초 예산의20/50건을 기존 실험과 비교했습니다. 20건B3는3초에서도 변경2건의 최적성을 증명했고,10초 호출 중앙값은5.21→2.42초였습니다. 50건10초B2는 전체 최적성을 증명했으나 B3는 미처리OPTIMAL/변경FEASIBLE/이동NOT_RUN입니다. 50건3초B2/B3는 첫 목적FEASIBLE이며 전체 최적성은 미증명입니다. 혼합은3초·세 시드만 후속 확인했으며 기존10초 전체를 다시 실행한 것으로 표현하지 않습니다.
