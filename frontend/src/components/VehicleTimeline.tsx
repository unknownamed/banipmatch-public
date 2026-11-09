import type { Assignment } from '../api/types'
import type { JobRow } from '../lib/compare'
import { kstTime } from '../lib/time'

const HOUR = 3_600_000

export interface Bar {
  jobId: string
  left: number // 축 대비 % (출발)
  width: number // % (출발~복귀)
  arrival: number // % (게이트 도착)
  locked: boolean
  late: boolean // 도착이 그 작업 시간창 마감보다 늦음
  changed: boolean // 조정안에서 차량·순서·시각이 바뀜
  label: string
}
export interface TimelineModel {
  ticks: { pct: number; label: string }[]
  deadlines: { pct: number; label: string }[]
  vehicles: { id: string; base: Bar[]; cand: Bar[] }[]
  unassigned: string[]
}

/** 원안·조정안 배정을 차량별 시간 막대로 바꾼다. 응답에 있는 시각만 쓰고, 없는 값은 만들지 않는다. */
export function timelineModel(rows: JobRow[], hasCand: boolean): TimelineModel | null {
  const all = rows.flatMap((r) => [r.baseline, hasCand ? r.candidate : undefined]).filter((a): a is Assignment => !!a)
  if (!all.length) return null
  const t = (s: string) => Date.parse(s)
  const start = Math.floor(Math.min(...all.map((a) => t(a.pickup_departure_at))) / HOUR) * HOUR
  const end = Math.max(start + HOUR, Math.ceil(Math.max(...all.map((a) => t(a.return_at))) / HOUR) * HOUR)
  const pct = (ms: number) => ((ms - start) / (end - start)) * 100
  const bar = (r: JobRow, a: Assignment, changed: boolean): Bar => {
    const closes = r.window?.closes_at
    return {
      jobId: r.job.job_id,
      left: pct(t(a.pickup_departure_at)),
      width: pct(t(a.return_at)) - pct(t(a.pickup_departure_at)),
      arrival: pct(t(a.gate_arrival_at)),
      locked: r.locked,
      late: !!closes && t(a.gate_arrival_at) > t(closes),
      changed,
      label: `${r.job.job_id} · 출발 ${kstTime(a.pickup_departure_at)} · 도착 ${kstTime(a.gate_arrival_at)} · 복귀 ${kstTime(a.return_at)}`,
    }
  }
  const ids = [...new Set(all.map((a) => a.vehicle_id))].sort()
  const vehicles = ids.map((id) => ({
    id,
    base: rows.filter((r) => r.baseline?.vehicle_id === id).map((r) => bar(r, r.baseline!, false)),
    cand: hasCand ? rows.filter((r) => r.candidate?.vehicle_id === id).map((r) => bar(r, r.candidate!, r.changes.length > 0)) : [],
  }))
  const deadlines = new Map<string, string>()
  for (const r of rows) if (r.window?.closes_at) deadlines.set(r.window.closes_at, r.job.voyage_id)
  const ticks = []
  for (let ms = start; ms <= end; ms += HOUR) ticks.push({ pct: pct(ms), label: kstTime(new Date(ms).toISOString()) })
  return {
    ticks,
    deadlines: [...deadlines]
      .filter(([c]) => t(c) >= start && t(c) <= end)
      .map(([c, voyage]) => ({ pct: pct(t(c)), label: `${voyage} 마감 ${kstTime(c)}` })),
    vehicles,
    unassigned: hasCand ? rows.filter((r) => r.candidateUnassigned).map((r) => r.job.job_id) : [],
  }
}

function Lane({ name, bars, model }: { name: string; bars: Bar[]; model: TimelineModel }) {
  return (
    <div className="lane">
      <span className="lane-name">{name}</span>
      <div className="lane-track">
        {model.deadlines.map((d) => (
          <span key={d.label} className="deadline" style={{ left: `${d.pct}%` }} />
        ))}
        {bars.length === 0 && <span className="muted small lane-empty">배정 없음</span>}
        {bars.map((b) => (
          <span
            key={b.jobId}
            className={`job-bar${b.locked ? ' locked' : ''}${b.late ? ' late' : ''}${b.changed ? ' changed' : ''}`}
            style={{ left: `${b.left}%`, width: `${b.width}%` }}
            title={b.label}
          >
            {b.locked && '🔒 '}
            {b.jobId}
            <i className="arrival" style={{ left: `${((b.arrival - b.left) / b.width) * 100}%` }} aria-hidden="true" />
          </span>
        ))}
      </div>
    </div>
  )
}

/** 차량별 카드: 원안 줄과 조정안 줄을 같은 시간축에 그린다. 막대는 출발~복귀, 점은 게이트 도착. */
export function VehicleTimeline({ rows, baseLabel, candLabel }: { rows: JobRow[]; baseLabel: string; candLabel: string | null }) {
  const model = timelineModel(rows, candLabel !== null)
  if (!model) return <p className="muted">배정된 작업이 없어 차량별 일정을 그릴 수 없습니다.</p>
  return (
    <div className="timeline">
      <div className="timeline-legend small muted">
        막대: 출발~복귀 · 점: 게이트 도착 · <span className="legend-deadline">세로선</span>: 반입 마감 ·{' '}
        <span className="legend-late">빨강</span>: 마감 초과 · <span className="legend-changed">초록 테두리</span>: 조정안에서 변경 · 🔒 고정
      </div>
      <div className="lane axis">
        <span className="lane-name" />
        <div className="lane-track">
          {model.ticks.map((tk) => (
            <span key={tk.label} className="tick" style={{ left: `${tk.pct}%` }}>
              {tk.label}
            </span>
          ))}
          {model.deadlines.map((d) => (
            <span key={d.label} className="deadline-label" style={{ left: `${d.pct}%` }}>
              {d.label}
            </span>
          ))}
        </div>
      </div>
      {model.vehicles.map((v) => (
        <section key={v.id} className="vehicle-card" aria-label={`차량 ${v.id}`}>
          <h3>{v.id}</h3>
          <Lane name={baseLabel} bars={v.base} model={model} />
          {candLabel && <Lane name={candLabel} bars={v.cand} model={model} />}
        </section>
      ))}
      {model.unassigned.length > 0 && (
        <p className="unassigned-row">
          <span className="badge unassigned">미처리</span> {model.unassigned.join(', ')} — 조정안에서 어느 차량에도 배정되지 않았습니다.
        </p>
      )}
    </div>
  )
}
