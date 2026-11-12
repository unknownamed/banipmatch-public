// 홈 '오늘 저녁 배차 현황': 지금 배차표(원안)대로 가면 차량마다 무엇을 하고 있고, 새 반입 마감에 맞는지.
// 관제 화면의 '요약 수치 + 검색·필터가 있는 상태 표' 구성. 위치·단계는 배차 일정으로 추정한 값이다(실제 GPS 아님).
import { useEffect, useMemo, useState } from 'react'
import type { Snapshot } from '../api/types'
import { PHASE_LABEL, gateStatus, vehiclesAt, type Phase } from '../lib/fleetPosition'
import { jobInfo, jobName, registerLabels, vehicleName } from '../lib/labels'
import { kstTimeWithDay } from '../lib/time'
import { BoxNo, Plate } from './Ids'
import { Icon } from './Icon'

const PHASE_TONE: Record<Phase, 'run' | 'gate' | 'wait'> = {
  to_origin: 'run', to_gate: 'run', returning: 'run', at_gate: 'gate', loading_wait: 'wait', idle: 'wait', done: 'wait',
}
type Filter = 'all' | 'run' | 'wait' | 'risk'

export function FleetToday({ snapshot }: { snapshot: Snapshot }) {
  useMemo(() => registerLabels(snapshot), [snapshot])
  const [now, setNow] = useState(() => Date.now())
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000)
    return () => clearInterval(t)
  }, [])
  const plan = snapshot.baseline_assignments
  const buffer = snapshot.policy.buffer_minutes
  const cutoff = (jid: string) => {
    const j = snapshot.jobs.find((x) => x.job_id === jid)!
    return snapshot.windows.find((w) => w.voyage_id === j.voyage_id && w.terminal_id === j.terminal_id)?.closes_at ?? null
  }
  const vehicles = vehiclesAt(snapshot, plan, now)
  const moving = vehicles.filter((v) => PHASE_TONE[v.phase] !== 'wait').length
  const remaining = plan.filter((a) => Date.parse(a.gate_arrival_at) > now)
  const atRisk = plan.filter((a) => gateStatus(a.gate_arrival_at, cutoff(a.job_id), buffer).gate === 'late')
  const nextCut = [...new Set(remaining.map((a) => cutoff(a.job_id)).filter((c): c is string => !!c && Date.parse(c) > now))].sort()[0]
  const stats = [
    { label: '운행 중 트럭', value: `${moving}`, unit: `/ ${vehicles.length}대` },
    { label: '반입 남은 컨테이너', value: `${remaining.length}`, unit: '개' },
    { label: '새 마감에 늦는 컨테이너', value: `${atRisk.length}`, unit: '개', tone: atRisk.length ? 'bad' : '' },
    { label: '다음 반입 마감', value: nextCut ? kstTimeWithDay(nextCut, snapshot.as_of) : '—', unit: '' },
  ]
  const q = query.trim().toLowerCase().replace(/\s/g, '')
  // 급한 순: 마감 넘김 → 빠듯함 → 여유(적은 순) → 남은 작업 없음
  const urgency = (v: (typeof vehicles)[number]) => (v.gate === 'late' ? 0 : v.gate === 'tight' ? 1 : v.gate === 'ok' ? 2 : 3) * 10000 + (v.marginMin ?? 9999)
  const rows = [...vehicles].sort((a, b) => urgency(a) - urgency(b)).filter((v) => {
    const tone = PHASE_TONE[v.phase]
    if (filter === 'run' && tone === 'wait') return false
    if (filter === 'wait' && tone !== 'wait') return false
    if (filter === 'risk' && v.gate !== 'late' && v.gate !== 'tight') return false
    if (!q) return true
    const info = v.jobId ? jobInfo(v.jobId) : null
    return `${vehicleName(v.vehicleId)}${v.jobId ? jobName(v.jobId) : ''}${info?.owner ?? ''}${info?.origin ?? ''}${info?.voyage ?? ''}`.toLowerCase().replace(/\s/g, '').includes(q)
  })
  const count = (f: Filter) => vehicles.filter((v) => f === 'all' || (f === 'run' ? PHASE_TONE[v.phase] !== 'wait' : f === 'wait' ? PHASE_TONE[v.phase] === 'wait' : v.gate === 'late' || v.gate === 'tight')).length
  return (
    <section className="card fleet-today" aria-labelledby="ft-title">
      <div className="ft-head">
        <h2 id="ft-title">오늘 배차 현황</h2>
        <span className="updated">위치는 배차 일정으로 추정</span>
      </div>
      <dl className="stat-strip">
        {stats.map((s) => (
          <div key={s.label} className={s.tone ? `ss-${s.tone}` : undefined}>
            <dt>{s.label}</dt>
            <dd><b>{s.value}</b>{s.unit && <span>{s.unit}</span>}</dd>
          </div>
        ))}
      </dl>
      <div className="toolbar">
        <div className="seg" role="group" aria-label="차량 상태">
          {([['all', '전체'], ['run', '운행 중'], ['wait', '대기'], ['risk', '마감 위험']] as [Filter, string][]).map(([id, label]) => (
            <button key={id} type="button" aria-pressed={filter === id} onClick={() => setFilter(id)}>{label}<span className="n">{count(id)}</span></button>
          ))}
        </div>
        <label className="search">
          <Icon name="search" size={15} />
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="차량 번호·컨테이너·화주 검색" aria-label="차량 검색" />
        </label>
      </div>
      <div className="dt-wrap">
        <table className="dt ft-table">
          <thead>
            <tr><th>차량</th><th>지금</th><th>컨테이너</th><th>상차지 → 터미널</th><th>게이트 도착</th><th>마감 여유</th></tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr className="empty-row"><td colSpan={6}>조건에 맞는 차량이 없습니다.</td></tr>}
            {rows.map((v) => {
              const info = v.jobId ? jobInfo(v.jobId) : null
              const tone = v.gate === 'late' ? 'bad' : v.gate === 'tight' ? 'warn' : 'ok'
              return (
                <tr key={v.vehicleId}>
                  <td data-label="차량"><Plate id={v.vehicleId} /></td>
                  <td data-label="지금"><span className={`st ${PHASE_TONE[v.phase]}`}>{PHASE_LABEL[v.phase]}</span></td>
                  <td data-label="컨테이너">{v.jobId ? <><BoxNo jobId={v.jobId} />{info && <span className="sub">{info.size}, {info.owner}</span>}</> : '—'}</td>
                  <td data-label="경로">{info ? <>{info.origin} → {info.terminal}<span className="sub">항차 {info.voyage}</span></> : '—'}</td>
                  <td data-label="게이트 도착" className="num">{v.gateEta ? kstTimeWithDay(v.gateEta, snapshot.as_of) : '—'}</td>
                  <td data-label="마감 여유" className="num">
                    {v.marginMin === null ? '—' : <span className={`st ${tone}`}>{v.gate === 'late' ? `${-v.marginMin}분 늦음` : `${v.marginMin}분 여유`}</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
