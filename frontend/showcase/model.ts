import type {
  Method,
  MethodResult,
  Snapshot,
  SolutionStatus,
} from "../src/api/types";

export const methods: Method[] = ["B0", "B1", "B2", "B3"];
export interface RecordEntry {
  result: MethodResult;
  audit: { integrity: string; schedule: string; failed: boolean };
  source_jsonl_line: number;
  wall_ms: number;
  seed: number;
}
export interface Case {
  case_id: string;
  label: string;
  profile: string;
  job_count: number;
  vehicle_count: number;
  generation_seed: number;
  budget_seconds: number;
  snapshot: Snapshot;
  methods: Record<Method, RecordEntry>;
  comparison: {
    same_served_job_set: boolean;
    b2_served_job_ids: string[];
    b3_served_job_ids: string[];
    delta_changed_jobs: number;
    delta_travel_minutes: number | null;
    equal_unassigned_count: boolean;
    equal_fixed_risk_count: boolean;
  };
}
export interface ComparisonPair {
  case_id: string;
  seed: number;
  identical_assigned_set: boolean;
  equal_count_comparable: boolean;
  changed_delta: number | null;
  travel_minutes_delta: number | null;
}
export interface Archive {
  schema_version: string;
  evidence_kind: string;
  provenance: {
    source_commit: string;
    protocol_sha256: string;
    results_sha256: string;
  };
  selection: { solver_seed: number; case_count: number; record_count: number };
  context: {
    total_records: number;
    total_pairs: number;
    summary: {
      independently_validated: number;
      baseline_integrity_passed: number;
      identical_workload_comparable: number;
      equal_count_comparable: number;
      objective_proven: number;
      failures: number;
    };
    pairs: ComparisonPair[];
  };
  cases: Case[];
}
export function filterCases(cases: Case[], query: string) {
  const needle = query.trim().toLocaleLowerCase();
  return cases.filter((c) =>
    `${c.case_id} ${c.label} ${c.profile} ${c.job_count}건`
      .toLocaleLowerCase()
      .includes(needle),
  );
}
export const signed = (n: number | null) =>
  n === null ? "미제공" : `${n > 0 ? "+" : ""}${n}`;
export function clock(value: string | null) {
  return value
    ? new Intl.DateTimeFormat("ko-KR", {
        timeZone: "Asia/Seoul",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).format(new Date(value))
    : "미확인";
}

// Compare only equal-count, identical-workload pairs; retain unavailable deltas.
export function pairOverview(archive: Archive) {
  const pairs = archive.context.pairs;
  const knownCases = new Map(archive.cases.map((c) => [c.case_id, c]));
  const sizes = [...new Set(archive.cases.map((c) => c.job_count))].sort(
    (a, b) => a - b,
  );
  return {
    seedCount: new Set(pairs.map((p) => p.seed)).size,
    pairCount: pairs.length,
    objectiveProofLabel: objectiveProofLabel(
      archive.context.summary.objective_proven,
      pairs.length * 2,
    ),
    equalCount: pairs.filter((p) => p.equal_count_comparable).length,
    identicalCount: pairs.filter(isComparable).length,
    unmatchedCount: pairs.filter((p) => !knownCases.has(p.case_id)).length,
    groups: sizes.map((size) => {
      const group = pairs.filter(
        (p) => knownCases.get(p.case_id)?.job_count === size,
      );
      const comparable = group.filter(isComparable);
      return {
        size,
        total: group.length,
        comparable: comparable.length,
        changed: deltaRange(comparable.map((p) => p.changed_delta)),
        travel: deltaRange(comparable.map((p) => p.travel_minutes_delta)),
      };
    }),
  };
}
function isComparable(pair: ComparisonPair) {
  return pair.equal_count_comparable && pair.identical_assigned_set;
}
export function deltaRange(values: (number | null)[]) {
  const available = values.filter(
    (v): v is number => typeof v === "number" && Number.isFinite(v),
  );
  return {
    range: available.length
      ? `${signed(Math.min(...available))} ~ ${signed(Math.max(...available))}`
      : "미제공",
    unavailable: values.length - available.length,
  };
}
const statusNames: Record<SolutionStatus, string> = {
  BASELINE: "원안",
  HEURISTIC: "휴리스틱",
  OPTIMAL: "최적",
  FEASIBLE: "실행 가능 · 최적 미증명",
  INFEASIBLE: "실행 불가능",
  UNKNOWN: "해 상태 미확인",
  MODEL_INVALID: "모델 오류",
  INPUT_INCOMPLETE: "입력 부족",
};
export function solutionLabel(
  status: SolutionStatus,
  objectiveProven: boolean,
) {
  const label =
    status === "OPTIMAL" && !objectiveProven
      ? "최적 상태 · 전체 목적 최적 미증명"
      : statusNames[status];
  return `${label}(${status})`;
}
export function jobStateLabel(state: string) {
  const labels: Record<string, string> = { planned: "계획", departed: "출발" };
  return labels[state] ? `${labels[state]}(${state})` : state;
}

function objectiveProofLabel(proven: number, total: number) {
  if (total === 0) return "비교 기록 없음";
  if (!Number.isInteger(proven) || proven < 0 || proven > total)
    return "자료 불일치 · 원본 확인 필요";
  return `${proven} / ${total}`;
}
