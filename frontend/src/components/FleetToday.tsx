// 홈 '오늘 저녁 배차' 현황: 지금 배차표(원안)대로 가면 차량마다 무엇을 하고 있고, 새 반입 마감에 맞는지.
// 물류 관제 화면의 'KPI 줄 + 상태 표' 구성. 위치·단계는 배차 일정으로 추정한 값이다(실제 GPS 아님).
import { useEffect, useMemo, useState } from 'react'
import type { Snapshot } from '../api/types'
import { PHASE_LABEL, gateStatus, vehiclesAt, type Phase } from '../lib/fleetPosition'
import { jobInfo, jobName, registerLabels, vehicleName } from '../lib/labels'
import { kstTimeWithDay } from '../lib/time'
import { Icon, type IconName } from './Icon'

const PHASE_TONE: Record<Phase, 'run' | 'gate' | 'wait' | 'off'> = {
  to_origin: 'run', to_gate: 'run', returning: 'run', at_gate: 'gate', loading_wait: 'wait', idle: 'wait', done: 'off',
}

export function FleetToday({ snapshot }: { snapshot: Snapshot }) {
  useMemo(() => registerLabels(snapshot), [snapshot])
  const [now, setNow] = useState(() => Date.now())
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
  const moving = vehicles.filter((v) => PHASE_TONE[v.phase] === 'run' || v.phase === 'at_gate').length
  const remaining = plan.filter((a) => Date.parse(a.gate_arrival_at) > now)
  const atRisk = plan.filter((a) => gateStatus(a.gate_arrival_at, cutoff(a.job_id), buffer).gate === 'late')
  const nextCut = [...new Set(remaining.map((a) => cutoff(a.job_id)).filter((c): c is string => !!c && Date.parse(c) > now))].sort()[0]
  const tiles: { icon: IconName; n: string | number; label: string; tone?: string }[] = [
    { icon: 'truck', n: `${moving}/${vehicles.length}`, label: '운행 중 트럭' },
    { icon: 'container', n: remaining.length, label: '반입 남은 컨테이너' },
    { icon: 'warning', n: atRisk.length, label: '새 마감에 늦는 컨테이너', tone: atRisk.length ? 'bad' : 'good' },
    { icon: 'clock', n: nextCut ? kstTimeWithDay(nextCut, snapshot.as_of) : '—', label: '다음 반입 마감' },
  ]
  return (
    <section className="card fleet-today" aria-labelledby="ft-title">
      <div className="ft-head">
        <h2 id="ft-title">오늘 저녁 배차 현황</h2>
        <span className="small ft-note">현재 배차표 기준 · 위치는 일정으로 추정 · 30초마다 갱신</span>
      </div>
      <div className="ft-kpis">
        {tiles.map((t) => (
          <div key={t.label} className={`ft-kpi${t.tone ? ` ${t.tone}` : ''}`}>
            <span className="ft-kpi-label">{t.label}</span>
            <b className="ft-kpi-n">{t.n}</b>
            <span className="ft-kpi-ic"><Icon name={t.icon} size={18} /></span>
          </div>
        ))}
      </div>
      <div className="ft-table-wrap">
        <table className="ft-table">
          <thead>
            <tr><th>차량</th><th>지금</th><th>현재·다음 컨테이너</th><th>상차지 → 터미널</th><th>게이트 도착</th><th>마감 여유</th></tr>
          </thead>
          <tbody>
            {vehicles.map((v) => {
              const info = v.jobId ? jobInfo(v.jobId) : null
              return (
                <tr key={v.vehicleId}>
                  <td data-label="차량"><b>{vehicleName(v.vehicleId)}</b></td>
                  <td data-label="지금"><span className={`ft-pill ${PHASE_TONE[v.phase]}`}>{PHASE_LABEL[v.phase]}</span></td>
                  <td data-label="컨테이너">{v.jobId ? <><b>{jobName(v.jobId)}</b>{info && <span className="ft-sub">{info.size} · {info.owner}</span>}</> : '—'}</td>
                  <td data-label="경로">{info ? `${info.origin} → ${info.terminal}` : '—'}</td>
                  <td data-label="게이트 도착" className="num">{v.gateEta ? kstTimeWithDay(v.gateEta, snapshot.as_of) : '—'}</td>
                  <td data-label="마감 여유">
                    {v.marginMin === null ? '—' : (
                      <span className={`ft-pill ${v.gate === 'late' ? 'late' : v.gate === 'tight' ? 'tight' : 'ok'}`}>
                        {v.gate === 'late' ? `${-v.marginMin}분 늦음` : `${v.marginMin}분`}
                      </span>
                    )}
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
