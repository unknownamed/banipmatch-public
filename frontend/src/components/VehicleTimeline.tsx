import { Plate } from './Ids'
import type { Assignment } from '../api/types'
import type { JobRow } from '../lib/compare'
import { Icon } from './Icon'
import { kstTime } from '../lib/time'
import { hasVehicleName, jobName, jobShort, vehicleName, vehicleShort } from '../lib/labels'

const HOUR = 3_600_000

export interface Bar {
  jobId: string
  left: number // 축 대비 % (출발)
  width: number // % (출발~복귀)
  arrival: number // % (게이트 도착)
  locked: boolean
  late: boolean // 도착 + 게이트 여유가 그 작업의 반입 마감을 넘김(엔진 위반 기준과 같다)
  cut: number | null // 그 작업 항차의 반입 마감 위치(%)
  changed: boolean // 조정안에서 차량·순서·시각이 바뀜
  label: string
}
export interface TimelineModel {
  ticks: { pct: number; label: string }[]
  deadlines: { pct: number; label: string }[]
  vehicles: { id: string; base: Bar[]; cand: Bar[] }[]
  unassigned: string[]
  baselineUnassigned: string[]
  missing: string[]
  incomplete: { jobId: string; vehicleId: string; side: 'base' | 'cand'; label: string }[]
}

/** 원안·조정안 배정을 차량별 시간 막대로 바꾼다. 응답에 있는 시각만 쓰고, 없는 값은 만들지 않는다. */
export function timelineModel(rows: JobRow[], hasCand: boolean, buffer = 0): TimelineModel | null {
  const all = rows.flatMap((r) => [r.baseline, hasCand ? r.candidate : undefined]).filter((a): a is Assignment => !!a)
  if (!rows.length) return null
  // 계약상 도착·복귀는 null일 수 있다. 런타임의 누락·형식 오류도 축에 전파하지 않는다.
  const t = (value: unknown) => typeof value === 'string' ? Date.parse(value) : NaN
  const known = all.flatMap((a) => [t(a.pickup_departure_at), t(a.gate_arrival_at), t(a.return_at)]).filter(Number.isFinite)
  const start = known.length ? Math.floor(Math.min(...known) / HOUR) * HOUR : null
  const end = start === null ? null : Math.max(start + HOUR, Math.ceil(Math.max(...known) / HOUR) * HOUR)
  const pct = (ms: number) => ((ms - start!) / (end! - start!)) * 100
  const incomplete: TimelineModel['incomplete'] = []
  const bars = (id: string, side: 'base' | 'cand'): Bar[] => rows.flatMap((r) => {
    const a = side === 'base' ? r.baseline : r.candidate
    if (!a || a.vehicle_id !== id) return []
    const label = `${jobName(r.job.job_id)}, 출발 ${kstTime(a.pickup_departure_at)}, 도착 ${kstTime(a.gate_arrival_at)}, 복귀 ${kstTime(a.return_at)}`
    if (![a.pickup_departure_at, a.gate_arrival_at, a.return_at].every((v) => Number.isFinite(t(v))) || t(a.return_at) <= t(a.pickup_departure_at)) {
      incomplete.push({ jobId: r.job.job_id, vehicleId: id, side, label })
      return []
    }
    return [bar(r, a, side === 'cand' && r.changes.length > 0)]
  })
  const bar = (r: JobRow, a: Assignment, changed: boolean): Bar => {
    const closes = r.window?.closes_at
    return {
      jobId: r.job.job_id,
      left: pct(t(a.pickup_departure_at)),
      width: pct(t(a.return_at)) - pct(t(a.pickup_departure_at)),
      arrival: pct(t(a.gate_arrival_at)),
      locked: r.locked,
      late: !!closes && t(a.gate_arrival_at) + buffer * 60000 > t(closes),
      cut: closes && start !== null && end !== null && t(closes) >= start && t(closes) <= end ? pct(t(closes)) : null,
      changed,
      label: `${jobName(r.job.job_id)}, 출발 ${kstTime(a.pickup_departure_at)}, 도착 ${kstTime(a.gate_arrival_at)}, 복귀 ${kstTime(a.return_at)}`,
    }
  }
  const ids = [...new Set(all.map((a) => a.vehicle_id))].sort()
  const vehicles = ids.map((id) => ({
    id,
    base: bars(id, 'base'),
    cand: hasCand ? bars(id, 'cand') : [],
  }))
  const deadlines = new Map<string, string>()
  for (const r of rows) if (r.window?.closes_at) deadlines.set(r.window.closes_at, r.job.voyage_id)
  const ticks = []
  for (let ms = start; ms !== null && end !== null && ms <= end; ms += HOUR) ticks.push({ pct: pct(ms), label: kstTime(new Date(ms).toISOString()) })
  return {
    ticks,
    deadlines: [...deadlines]
      .filter(([c]) => start !== null && end !== null && t(c) >= start && t(c) <= end)
      .map(([c, voyage]) => ({ pct: pct(t(c)), label: `${voyage} 마감 ${kstTime(c)}` })),
    vehicles,
    incomplete,
    baselineUnassigned: rows.filter((r) => !r.baseline).map((r) => r.job.job_id),
    missing: hasCand ? rows.filter((r) => r.candidateMissing).map((r) => r.job.job_id) : [],
    unassigned: hasCand ? rows.filter((r) => r.candidateUnassigned).map((r) => r.job.job_id) : [],
  }
}

function Lane({ name, bars, incomplete }: { name: string; bars: Bar[]; model?: TimelineModel; incomplete: boolean }) {
  return (
    <div className="lane">
      <span className="lane-name">{hasVehicleName(name) ? <><b>{vehicleShort(name)}</b><small>{vehicleName(name)}</small></> : name}</span>
      <div className="lane-track">
        {/* 마감선은 차량 전체가 아니라 그 막대 작업의 항차 마감에만 긋는다(다른 항차 작업이 넘긴 것처럼 보이지 않게) */}
        {bars.filter((b) => b.cut !== null).map((b) => (
          <span key={`cut-${b.jobId}`} className={`cut-mark${b.late ? ' late' : ''}`} style={{ left: `${b.cut}%` }} />
        ))}
        {bars.length === 0 && <span className="muted small lane-empty">{incomplete ? '시각 확인 필요' : '배정 없음'}</span>}
        {bars.map((b) => (
          <span
            key={b.jobId}
            className={`job-bar${b.locked ? ' locked' : ''}${b.late ? ' late' : ''}${b.changed ? ' changed' : ''}`}
            style={{ left: `${b.left}%`, width: `${b.width}%` }}
            aria-label={b.label}
          >
            {b.locked && <Icon name="lock" size={11} />}
            {jobShort(b.jobId)}
            <i className="arrival" style={{ left: `${((b.arrival - b.left) / b.width) * 100}%` }} aria-hidden="true" />
          </span>
        ))}
      </div>
    </div>
  )
}

/** 차량별 카드: 원안 줄과 조정안 줄을 같은 시간축에 그린다. 막대는 출발~복귀, 점은 게이트 도착. */
export function VehicleTimeline({ rows, baseLabel, candLabel, buffer = 0 }: { rows: JobRow[]; baseLabel: string; candLabel: string | null; buffer?: number }) {
  const model = timelineModel(rows, candLabel !== null, buffer)
  if (!model) return <p className="muted">배정된 작업이 없어 차량별 일정을 그릴 수 없습니다.</p>
  return (
    <div className="timeline">
      {/* 범례는 실제 막대와 같은 모양의 견본으로 보여준다 */}
      <ul className="timeline-legend small muted">
        <li><i className="sw sw-bar" />출발~복귀</li>
        <li><i className="sw sw-dot" />게이트 도착</li>
        <li><i className="sw sw-deadline" />그 작업의 반입 마감</li>
        <li><i className="sw sw-late" />마감 넘김(여유 {buffer}분 포함)</li>
        <li><i className="sw sw-changed" />조정안 변경</li>
        <li><i className="sw sw-locked"><Icon name="lock" size={10} /></i>고정</li>
      </ul>
      <div className="lane axis">
        <span className="lane-name" />
        <div className="lane-track">
          {model.ticks.map((tk) => (
            <span key={tk.pct} className="tick" style={{ left: `${tk.pct}%` }}>
              {tk.label}
            </span>
          ))}
        </div>
      </div>
      {model.vehicles.map((v) => (
        <section key={v.id} className="vehicle-card" aria-label={`차량 ${v.id}`}>
          <h3><Plate id={v.id} /></h3>
          <Lane name={baseLabel} bars={v.base} model={model} incomplete={model.incomplete.some((a) => a.vehicleId === v.id && a.side === 'base')} />
          {candLabel && <Lane name={candLabel} bars={v.cand} model={model} incomplete={model.incomplete.some((a) => a.vehicleId === v.id && a.side === 'cand')} />}
          {model.incomplete.filter((a) => a.vehicleId === v.id).map((a) => (
            <p key={`${a.side}-${a.jobId}`} className="warn small">
              {a.side === 'base' ? baseLabel : candLabel}: {a.label}, 시각 확인 필요
            </p>
          ))}
        </section>
      ))}
      {model.ticks.length === 0 && <p className="muted">확인된 배정 시각이 없어 시간축을 그릴 수 없습니다.</p>}
      {model.baselineUnassigned.length > 0 && <p className="unassigned-row">{baseLabel} 배정 없음: {model.baselineUnassigned.map(jobName).join(', ')}</p>}
      {model.missing.length > 0 && <p className="warn">조정안 결과 누락(배정·미처리 모두 아님): {model.missing.join(', ')}</p>}
      {model.unassigned.length > 0 && (
        <p className="unassigned-row">
          <span className="badge unassigned">미배정</span> {model.unassigned.map(jobName).join(', ')}: 조정안에서 맡을 차량을 찾지 못했습니다.
        </p>
      )}
    </div>
  )
}
