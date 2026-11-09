import { useState } from "react";
import type { Method } from "../src/api/types";
import {
  clock,
  filterCases,
  methods,
  signed,
  pairOverview,
  solutionLabel,
  jobStateLabel,
} from "./model";
import type { Archive, Case } from "./model";

const names: Record<Method, string> = {
  B0: "원안 진단",
  B1: "순차 삽입",
  B2: "미처리 → 이동 최소화",
  B3: "미처리 → 변경 → 이동 최소화",
};
const auditLabel = (status: string) =>
  status === "passed"
    ? "통과"
    : status === "baseline_not_applicable"
      ? "원안: 일정 검사 대상 아님"
      : status;

export function Showcase({ archive }: { archive: Archive }) {
  const [query, setQuery] = useState("");
  const [caseId, setCaseId] = useState(archive.cases[0].case_id);
  const [method, setMethod] = useState<Method>("B3");
  const selected = archive.cases.find((c) => c.case_id === caseId)!;
  const matching = filterCases(archive.cases, query);
  const summary = archive.context.summary;
  const overview = pairOverview(archive);
  return (
    <main>
      <header className="hero">
        <p className="eyebrow">반입맞춤 / 계산 기록 탐색</p>
        <h1>
          반입시간이 바뀌면,
          <br />
          배차는 얼마나 바뀌어야 할까요?
        </h1>
        <p className="intro">
          변경된 반입시간에 맞춰 남은 작업을 조정하고, 이미 출발한 작업과 남은
          위험을 함께 살펴봅니다.
        </p>
        <div className="notice">
          <strong>읽기 전용 · 모의 입력의 실제 계산 결과</strong>
          <p>
            2026-11-08에 실행해 보존한 기록입니다. 지금 계산하는 화면이나 현장
            배차가 아니며, 수작업 설명용 결과도 아닙니다. 승인·외부 예약·기사
            통보 기능은 없습니다.
          </p>
        </div>
      </header>
      <section className="card" aria-labelledby="evaluation-title">
        <h2 id="evaluation-title">선택 사례를 전체 평가 안에서 보기</h2>
        <div className="context-grid">
          <div>
            <b>{archive.context.total_records}회</b>
            <span>
              입력 {archive.cases.length}종 · 비교 기록의 계산 시드{" "}
              {overview.seedCount}종 · B0~B3 보존 기록
            </span>
          </div>
          <div>
            <b>{overview.pairCount}쌍</b>
            <span>B2 / B3 비교 · 같은 미처리 수 {overview.equalCount}쌍</span>
          </div>
          <div>
            <b>{overview.identicalCount}쌍</b>
            <span>실제로 처리한 작업 ID 집합도 동일</span>
          </div>
          <div>
            <b>{overview.objectiveProofLabel}</b>
            <span>B2·B3 전체 목적 최적성 입증</span>
          </div>
        </div>
        <p className="muted">
          독립 일정 검사 {summary.independently_validated}개 통과 · 원안 무결성{" "}
          {summary.baseline_integrity_passed}개 보존 · 실행 오류{" "}
          {summary.failures}개. 현장 효과·비용 절감이나 전체 문제의 최적성을
          입증한 것은 아닙니다.
        </p>
        <div aria-label="작업 규모별 비교 요약">
          <p>
            차이는 B3 − B2입니다. 음수는 감소, 양수는 증가이며 0은 동일합니다.
            같은 미처리 수와 같은 처리 작업 ID 집합을 모두 만족하는 쌍만 범위에
            포함합니다.
          </p>
          {overview.groups.map((group) => (
            <p key={group.size}>
              {group.size}건 입력: 동일 작업 비교 {group.comparable} /{" "}
              {group.total}쌍 ·{" "}
              {group.comparable === 0 ? (
                "동일 작업 비교 쌍 없음"
              ) : (
                <>
                  변경 차이(건) {group.changed.range} (미제공{" "}
                  {group.changed.unavailable}쌍) · 가변 이동 차이(분){" "}
                  {group.travel.range} (미제공 {group.travel.unavailable}쌍)
                </>
              )}
            </p>
          ))}
          {overview.pairCount === 0 && (
            <p>비교 기록이 없습니다. 차이 범위를 계산하지 않았습니다.</p>
          )}
          {overview.unmatchedCount > 0 && (
            <p>
              입력 규모 미확인 {overview.unmatchedCount}쌍은 규모별 요약에서
              제외했습니다.
            </p>
          )}
          <p>
            같은 입력의 시드 반복은 독립된 현장 표본이 아닙니다. 시드 수만으로
            모든 방법의 기록이 빠짐없이 존재한다고 판단하지 않습니다.
          </p>
        </div>
      </section>
      <section className="card" aria-labelledby="case-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">01 / 사례 고르기</p>
            <h2 id="case-title">모든 입력을 그대로 공개합니다</h2>
          </div>
          <span className="pill">
            계산 시드 {archive.selection.solver_seed} ·{" "}
            {archive.selection.record_count}개 기록 표시
          </span>
        </div>
        <div className="controls">
          <div>
            <label htmlFor="case-search">사례 검색</label>
            <input
              id="case-search"
              type="search"
              value={query}
              placeholder="마감, 준비, 고정, 50건…"
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="case-select">사례 선택</label>
            <select
              id="case-select"
              value={matching.some((c) => c.case_id === caseId) ? caseId : ""}
              onChange={(e) => setCaseId(e.target.value)}
            >
              <option value="" disabled>
                검색 결과에서 선택하세요
              </option>
              {matching.map((c) => (
                <option key={c.case_id} value={c.case_id}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <p className="muted" role="status">
          검색 결과 {matching.length} / {archive.cases.length}개.{" "}
          {matching.length === 0
            ? "일치하는 사례가 없습니다. 검색어를 지워 보세요."
            : "선택 전까지 아래 사례는 유지됩니다."}
        </p>
        <h3>{selected.label}</h3>
        <p>
          <code>{selected.case_id}</code> · 작업 {selected.job_count}건 · 차량{" "}
          {selected.vehicle_count}대 · 생성 시드 {selected.generation_seed} ·
          방법별 예산 {selected.budget_seconds}초
        </p>
        <p className="muted">
          입력 기준시각 {clock(selected.snapshot.as_of)} KST · 확인된 변경의
          이전 허용시간 {clock(selected.snapshot.change.previous_opens_at)} ~{" "}
          {clock(selected.snapshot.change.previous_closes_at)}
        </p>
        <p>
          변경 후 반입 허용시간:{" "}
          {selected.snapshot.windows
            .filter(
              (w) => w.window_id === selected.snapshot.change.new_window_id,
            )
            .map((w) => `${clock(w.opens_at)} ~ ${clock(w.closes_at)} KST`)
            .join(", ") || "원본 입력 확인 필요"}{" "}
          · 여유 {selected.snapshot.policy.buffer_minutes}분
        </p>
      </section>
      <PairComparison selected={selected} />
      <section className="card" aria-labelledby="metrics-title">
        <p className="eyebrow">03 / 네 가지 방법</p>
        <h2 id="metrics-title">미처리·위반·잔여 위험부터 비교</h2>
        <div className="table-scroll">
          <table>
            <caption>같은 입력·시드·계산 예산의 B0~B3 결과</caption>
            <thead>
              <tr>
                <th scope="col">방법 / 해 상태</th>
                <th scope="col">미처리</th>
                <th scope="col">가변 위반</th>
                <th scope="col">고정 위험</th>
                <th scope="col">변경 작업</th>
                <th scope="col">가변 이동(분)</th>
                <th scope="col">계산(밀리초)</th>
              </tr>
            </thead>
            <tbody>
              {methods.map((m) => {
                const r = selected.methods[m].result;
                return (
                  <tr key={m}>
                    <th scope="row">
                      {m} · {names[m]}
                      <small>
                        {solutionLabel(r.solution_status, r.objective_proven)} ·
                        전체 목적 입증 {r.objective_proven ? "예" : "아니오"}
                      </small>
                    </th>
                    <td>{r.metrics.unassigned_count}</td>
                    <td>{r.metrics.movable_violation_count}</td>
                    <td>{r.metrics.fixed_risk_count}</td>
                    <td>{r.metrics.changed_job_ids.length}</td>
                    <td>{r.metrics.movable_travel_minutes ?? "미제공"}</td>
                    <td>{r.metrics.elapsed_ms}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="muted">
          B0는 변경 후 원안을 진단합니다. 미처리가 0이어도 위반이 있으면 실행
          가능한 조정안이라는 뜻이 아닙니다. B2는 상용 TMS의 재현이 아닙니다.
        </p>
      </section>
      <section className="card" aria-labelledby="schedule-title">
        <p className="eyebrow">04 / 작업별 결과</p>
        <h2 id="schedule-title">일정과 남은 문제 확인</h2>
        <div
          className="method-buttons"
          role="group"
          aria-label="일정 방법 선택"
        >
          {methods.map((m) => (
            <button
              key={m}
              aria-pressed={method === m}
              onClick={() => setMethod(m)}
            >
              {m} {names[m]}
            </button>
          ))}
        </div>
        <Schedule selected={selected} method={method} />
      </section>
      <section className="card" aria-labelledby="provenance-title">
        <h2 id="provenance-title">원본과 검사 기록</h2>
        <p>
          원시 결과의 <code>validation_status: not_run</code>,{" "}
          <code>approval_eligible: false</code>를 그대로 보존합니다. 별도로
          실행한 독립 감사 결과를 원시 상태에 덮어쓰지 않았습니다.
        </p>
        <p className="muted">
          텍스트 해시는 줄바꿈을 LF로 맞춘 기준입니다. 원본 바이트 해시와 정규화
          방식은 보존 자료의 provenance에 별도로 남깁니다.
        </p>
        <dl className="provenance">
          <dt>계산 소스 커밋</dt>
          <dd>{archive.provenance.source_commit}</dd>
          <dt>프로토콜 SHA-256</dt>
          <dd>{archive.provenance.protocol_sha256}</dd>
          <dt>원시 결과 SHA-256 (LF)</dt>
          <dd>{archive.provenance.results_sha256}</dd>
        </dl>
        <details>
          <summary>선택한 사례의 원본 입력·결과·감사 JSON</summary>
          <pre>{JSON.stringify(selected, null, 2)}</pre>
        </details>
        <details>
          <summary>전체 {overview.pairCount}쌍의 비교 기록</summary>
          <pre>{JSON.stringify(archive.context.pairs, null, 2)}</pre>
        </details>
      </section>
      <footer>
        반입맞춤 · 학생팀 모의 평가 아카이브 · 실제 운송사 배차표·차량 GPS·현장
        효과는 미확보
      </footer>
    </main>
  );
}

function PairComparison({ selected }: { selected: Case }) {
  const c = selected.comparison;
  return (
    <section className="card comparison" aria-labelledby="pair-title">
      <p className="eyebrow">02 / 핵심 비교</p>
      <h2 id="pair-title">B2 → B3, 바꾸는 작업과 이동의 절충</h2>
      <p className={c.same_served_job_set ? "comparison-status" : "caution"}>
        <strong>
          {c.same_served_job_set
            ? "같은 작업 ID 집합을 처리했습니다."
            : "처리한 작업 ID 집합이 다릅니다."}
        </strong>{" "}
        미처리 수 {c.equal_unassigned_count ? "동일" : "다름"} · 고정 위험 수{" "}
        {c.equal_fixed_risk_count ? "동일" : "다름"}
      </p>
      {!c.same_served_job_set && (
        <p className="caution">
          미처리 수가 같아도 서로 다른 작업을 처리합니다. 변경량·이동량의 차이를
          같은 작업에 대한 개선으로 해석할 수 없습니다.
        </p>
      )}
      <div className="table-scroll">
        <table>
          <caption>B2와 B3 직접 비교</caption>
          <thead>
            <tr>
              <th scope="col">방법</th>
              <th scope="col">미처리</th>
              <th scope="col">고정 위험</th>
              <th scope="col">변경 작업</th>
              <th scope="col">가변 이동(분)</th>
              <th scope="col">해 상태</th>
            </tr>
          </thead>
          <tbody>
            {(["B2", "B3"] as const).map((m) => {
              const r = selected.methods[m].result;
              return (
                <tr key={m}>
                  <th scope="row">{m}</th>
                  <td>{r.metrics.unassigned_count}</td>
                  <td>{r.metrics.fixed_risk_count}</td>
                  <td>{r.metrics.changed_job_ids.length}</td>
                  <td>{r.metrics.movable_travel_minutes ?? "미제공"}</td>
                  <td>
                    {solutionLabel(r.solution_status, r.objective_proven)}
                    <small>
                      전체 목적 입증 {r.objective_proven ? "예" : "아니오"}
                    </small>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="delta-grid">
        <div>
          <span>변경 작업 차이</span>
          <b>{signed(c.delta_changed_jobs)}건</b>
        </div>
        <div>
          <span>가변 이동 차이</span>
          <b>{signed(c.delta_travel_minutes)}분</b>
        </div>
        <div>
          <span>차이 계산</span>
          <b>B3 − B2</b>
        </div>
      </div>
      <p className="muted">
        음수는 감소, 양수는 증가입니다. 변경이 줄어도 이동 증가·미처리·고정
        위험·해 상태를 함께 보아야 합니다.
      </p>
      <details>
        <summary>두 방법이 처리한 작업 ID 확인</summary>
        <p>B2: {c.b2_served_job_ids.join(", ") || "없음"}</p>
        <p>B3: {c.b3_served_job_ids.join(", ") || "없음"}</p>
      </details>
    </section>
  );
}

function Schedule({ selected, method }: { selected: Case; method: Method }) {
  const record = selected.methods[method];
  const r = record.result;
  return (
    <>
      <p>
        <strong>
          {method} · {solutionLabel(r.solution_status, r.objective_proven)}
        </strong>{" "}
        · 원시 검사 상태 <code>{r.validation_status}</code> · 보존된 승인 가능
        값 <code>{String(r.approval_eligible)}</code>
      </p>
      <div className="audit">
        <strong>별도 독립 감사</strong> · 무결성{" "}
        {auditLabel(record.audit.integrity)} · 일정{" "}
        {auditLabel(record.audit.schedule)} · 감사 실패{" "}
        {record.audit.failed ? "예" : "아니오"}
        <br />
        <small>
          원본 JSONL {record.source_jsonl_line}행 · 기록 외부 소요{" "}
          {record.wall_ms}ms
        </small>
      </div>
      <p>
        목적 단계:{" "}
        {r.objective_stages.length
          ? r.objective_stages
              .map(
                (s) =>
                  `${s.objective}: ${s.status} (값 ${s.value ?? "없음"}, 하한 ${s.best_bound ?? "없음"})`,
              )
              .join(" / ")
          : "해당 없음"}
      </p>
      <div className="table-scroll">
        <table>
          <caption>{method} 일정 · 모든 시각 KST · 원안과 조정 결과</caption>
          <thead>
            <tr>
              <th scope="col">작업 / 상태</th>
              <th scope="col">원안 차량·순서 / 도착</th>
              <th scope="col">결과 차량·순서</th>
              <th scope="col">픽업 출발</th>
              <th scope="col">게이트 도착</th>
              <th scope="col">복귀</th>
            </tr>
          </thead>
          <tbody>
            {selected.snapshot.jobs.map((j) => {
              const a = r.assignments.find((a) => a.job_id === j.job_id);
              const b = selected.snapshot.baseline_assignments.find(
                (a) => a.job_id === j.job_id,
              );
              return (
                <tr key={j.job_id}>
                  <th scope="row">
                    {j.job_id}
                    <small>
                      {j.frozen
                        ? "고정"
                        : r.metrics.changed_job_ids.includes(j.job_id)
                          ? "변경"
                          : "가변"}{" "}
                      · {jobStateLabel(j.state)}
                    </small>
                  </th>
                  <td>
                    {b
                      ? `${b.vehicle_id} #${b.sequence} / ${clock(b.gate_arrival_at)}`
                      : "원안 미배정"}
                  </td>
                  <td>
                    {a
                      ? `${a.vehicle_id} #${a.sequence}`
                      : r.unassigned_job_ids.includes(j.job_id)
                        ? "미처리"
                        : "결과 누락"}
                  </td>
                  <td>{a ? clock(a.pickup_departure_at) : "—"}</td>
                  <td>{a ? clock(a.gate_arrival_at) : "—"}</td>
                  <td>{a ? clock(a.return_at) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <h3>미처리 및 위험 사유 ({r.issues.length}개)</h3>
      {r.issues.length ? (
        <ul className="issues">
          {r.issues.map((i, n) => (
            <li key={n}>
              <strong>
                {i.job_id ?? "전체"} · {i.code}
              </strong>
              <p>{i.explanation}</p>
              <small>
                근거 수준: {i.proof_level} · {i.evidence_refs.join(", ")}
              </small>
            </li>
          ))}
        </ul>
      ) : (
        <p>이 결과에 보고된 문제는 없습니다.</p>
      )}
    </>
  );
}
