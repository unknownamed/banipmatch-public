# 짧은 계산 예산의 병목 분석과 엔진 0.2.2

2026-11-08 로컬 모의 입력 실험입니다. [기존 156회](../engine-sensitivity-2026-11-08/README.md)는 0.2.1 기록으로 보존하고, 아래 진단 4회와 수정 후 비교 72회를 별도로 저장했습니다. 실제 운송사 성능이나 배포 서버의 응답시간 보장이 아닙니다.

## 원인과 변경

50건·차량8대 모형은 변수21,523개, 제약43,023개, 경로 간선20,400개입니다. 이전 진단에서 B1 초기안 구성 약0.063초, 모형 구성 약0.468초였으나 첫 목적 단계가 전처리 뒤 UNKNOWN으로 끝나 탐색 분기가0이었습니다. 이 사례에서는 단순한 파이썬 모형 작성보다 솔버 전처리가 짧은 예산의 병목이었습니다.

0.2.2는 같은 B1 초기안의 경로·출발·순서뿐 아니라 변경 여부·순서 역전 등 보조변수까지 일관된 힌트를 줍니다. 힌트는 강제 제약이 아니며 다음 단계에서도 더 나은 해를 탐색할 수 있습니다. `cp_model_probing_level=0`으로 probing만 끄고 나머지 presolve는 유지합니다. 목적·가능한 일정·고정 작업 보호·외부 계약은 바꾸지 않았습니다. [OR-Tools 9.15 파라미터 원문](https://github.com/google/or-tools/blob/v9.15/ortools/sat/sat_parameters.proto)에서 기본 probing=2, 0일 때 비활성임을 확인할 수 있습니다.

## 원인 확인용 진단 4회

| 폴더 | 조건 | 첫 목적 / 다음 목적 | 해석 |
|---|---|---|---|
| `before-default` | 0.2.1, 기존 힌트, probing2 | UNKNOWN / 미실행 | 전처리 뒤 종료, 분기0 |
| `probing-zero` | 기존 힌트, probing0 | OPTIMAL / UNKNOWN | 미처리26 증명, 변경 목적 미증명 |
| `complete-hint-default` | 보조변수 힌트 시도, probing2 | FEASIBLE / 미실행 | 상수1개는 아직 힌트에서 누락된 중간판 |
| `complete-hint-probing-zero` | 모든 변수 힌트, probing0 | OPTIMAL / FEASIBLE | 미처리26 증명, 변경23 유효안 |

각 `profile.json`에는 실제 소스 해시·설정·모형 크기·단계별 시간과 결과가 있고 `stage_*_solver.txt`에는 솔버 로그가 있습니다. 폴더명만 보고 `complete-hint-default`를 최종 완전 힌트로 해석하지 않습니다. 진단 로그 자체에 비용이 있고 각1회뿐이므로 최종 성능 비교에는 아래의 로그 없는 반복 실험을 사용합니다.

## 수정 후 반복 실험 72회

- `after-scale`:20/50건 ×3/10초 ×반복3 ×B0~B3=48회. 시드0.
- `after-mixed`:혼합12건/고정 포함12건 ×3초 ×시드0/17/41 ×B0~B3=24회.
- 모든 방법에 동일한 입력과 총 예산을 주며 Python3.12.14, OR-Tools9.15.6755, 단일 worker를 사용했습니다. 초기안 구성·모형 구성·목적 단계도 예산에 포함합니다.

| 조건 | 이전0.2.1 | 수정 후0.2.2 | 판정 |
|---|---|---|---|
| 20건 B3·3초 | 미처리8·변경10·최적 미증명 | 미처리8·변경2·이동720분 | 반복3회 모두 전체 OPTIMAL, 중앙2.37초 |
| 20건 B3·10초 | 같은 목적값, 중앙5.21초 | 같은 목적값, 중앙2.42초 | 반복3회 모두 전체 OPTIMAL |
| 50건 B2·10초 | 초기안만 유지, 솔버 UNKNOWN | 미처리26·변경24·이동1440분 | 반복3회 모두 전체 OPTIMAL |
| 50건 B3·10초 | 초기안의 변경24 | 미처리26·변경23·이동1440분 | 미처리만 증명, 변경 FEASIBLE·이동 미실행 |
| 50건 B2/B3·3초 | 솔버 UNKNOWN | 첫 목적 FEASIBLE, 나머지 미실행 | 전체 최적성 미증명 |
| 혼합12건 B3·3초 | 미처리3·변경5·이동540분 | 같은 목적값 | 모든 시드 OPTIMAL |
| 고정 포함12건 B3·3초 | 미처리3·변경5·이동420분 | 같은 목적값 | 고정2건·고정 잔여위험1건 보존 |

50건 B3는 계산 문제가 모두 해결된 상태가 아닙니다. 변경23이 최소라는 증명은 없으며, 3초 예산의 처리수도 증명되지 않았습니다. 입력은 제한된 합성 사례이므로 일반 입력·다른 장비·배포 환경에 그대로 일반화하지 않습니다. 특히 20/50건 기본 사례는 단일 시간창과 반복 이동구조입니다.

`checks.json`은 72회 결과 스키마·입력/실행 소스 해시·작업 전체 분할·고정 기록 보존과 조정 작업 위반0을 확인한 기록입니다. 독립 일정 검사는 여전히 미구현이며 모든 결과는 `validation_status=not_run`, `approval_eligible=false`입니다. 후속 결과에 기록한 Git HEAD는 실행 당시 직전 커밋이고 미커밋 코드의 정확한 식별자는 `source_sha256`입니다.

## 재현

저장소 루트에서 엔진 의존성을 설치한 뒤 실행합니다. 출력 디렉터리는 새 이름을 지정해야 하며 기존 결과를 덮어쓰지 않습니다.

```sh
python tools/profile_engine.py --input docs/experiments/engine-b0-b3/inputs/50_jobs_8_vehicles.json --output-dir local/profile-50-new --budget 10
python tools/benchmark_engine.py --inputs docs/experiments/engine-b0-b3/inputs/20_jobs_4_vehicles.json docs/experiments/engine-b0-b3/inputs/50_jobs_8_vehicles.json --output-dir local/scale-new --budgets 3 10 --seeds 0 --repeats 3
python tools/benchmark_engine.py --inputs docs/experiments/engine-sensitivity-2026-11-08/inputs/mixed_12.json docs/experiments/engine-sensitivity-2026-11-08/inputs/mixed_fixed_12.json --output-dir local/mixed-new --budgets 3 --seeds 0 17 41
```

`profile_engine.py`의 `--probing-level 2` 등은 해당 진단 실행에만 적용됩니다. 공통 엔진의 운영 설정을 변경하지 않으며 로그 기록으로 시간이 달라질 수 있습니다. 도구의 명시적 override가 엔진 기본값 뒤에 적용되는지 작은 입력으로 별도 확인했습니다.

[보고서용 표·그림·PDF](../engine-report-2026-11-08/README.md) · [엔진 모형](../../../backend/engine/OPTIMIZATION.md) · [최신 인계](../../team/handoffs/2026-11-08-unknownamed-engine-performance.md)
