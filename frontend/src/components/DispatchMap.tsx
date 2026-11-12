// 배차 담당자용 차량 현황 지도: 지금 각 트럭이 어디서 무엇을 하는지(배차 일정 기준 추정)와
// 다음 게이트 도착 예정이 반입 마감 안에 드는지 본다. 실시간 교통은 카카오 교통정보 레이어(실제 자료)다.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { MethodResult, Snapshot } from '../api/types'
import { PHASE_LABEL, locationPoints, vehiclesAt, type Pt, type VehicleNow } from '../lib/fleetPosition'
import { loadKakaoMaps } from '../lib/kakaoMaps'
import { kstTime } from '../lib/time'

const GATE_LABEL = { ok: '여유', tight: '빠듯', late: '마감 초과' } as const

function truckSvg(heading: number) {
  return `<svg class="truck" viewBox="0 0 14 34" width="14" height="34" style="transform:rotate(${heading}deg)" aria-hidden="true">`
    + `<rect class="cab" x="2" y="0.8" width="10" height="7" rx="2"/>`
    + `<rect class="box" x="1" y="9.5" width="12" height="23.5" rx="1.4"/>`
    + `<line x1="1.5" y1="17" x2="12.5" y2="17"/><line x1="1.5" y1="25" x2="12.5" y2="25"/></svg>`
}
function bearing(a: Pt, b: Pt) {
  const r = Math.PI / 180
  const y = Math.sin((b.lon - a.lon) * r) * Math.cos(b.lat * r)
  const x = Math.cos(a.lat * r) * Math.sin(b.lat * r) - Math.sin(a.lat * r) * Math.cos(b.lat * r) * Math.cos((b.lon - a.lon) * r)
  return (Math.atan2(y, x) / r + 360) % 360
}

export function DispatchMap({ snapshot, base, cand, selectedJob, onSelectJob }: {
  snapshot: Snapshot
  base: MethodResult | undefined
  cand: MethodResult | undefined
  selectedJob: string | null
  onSelectJob: (jobId: string | null) => void
}) {
  const pts = useMemo(() => locationPoints(snapshot), [snapshot])
  const [usePlan, setUsePlan] = useState<'cand' | 'base'>(cand ? 'cand' : 'base')
  const [now, setNow] = useState(() => Date.now())
  const [traffic, setTraffic] = useState(false)
  const [sky, setSky] = useState(false)
  const [mapState, setMapState] = useState<{ ok: boolean; msg: string }>({ ok: false, msg: '지도 불러오는 중…' })
  useEffect(() => { const id = setInterval(() => setNow(Date.now()), 15000); return () => clearInterval(id) }, [])

  const plan = usePlan === 'cand' && cand ? cand.assignments : base?.assignments ?? snapshot.baseline_assignments
  const planLabel = usePlan === 'cand' && cand ? `${cand.method} 조정안` : '원안'
  const unassigned = usePlan === 'cand' && cand ? cand.unassigned_job_ids : base?.unassigned_job_ids ?? snapshot.baseline_unassigned_job_ids
  const fleet = useMemo(() => vehiclesAt(snapshot, plan, now), [snapshot, plan, now])
  const selVehicle = selectedJob ? plan.find(a => a.job_id === selectedJob)?.vehicle_id ?? null : null

  const box = useRef<HTMLDivElement>(null)
  const kmap = useRef<any>(null)
  const trucks = useRef(new Map<string, { overlay: any; el: HTMLDivElement }>())
  const jobLine = useRef<any>(null)
  const allBounds = useRef<any>(null)

  useEffect(() => {
    if (pts.size === 0) return
    let alive = true
    loadKakaoMaps().then(maps => {
      if (!alive || !box.current) return
      const ll = (p: Pt) => new maps.LatLng(p.lat, p.lon)
      const m = new maps.Map(box.current, { center: ll([...pts.values()][0]), level: 8 })
      kmap.current = m
      const bounds = new maps.LatLngBounds()
      for (const loc of snapshot.locations ?? []) {
        const p = pts.get(loc.location_id)
        if (!p) continue
        bounds.extend(ll(p))
        const el = document.createElement('div')
        el.className = `dm-place ${loc.kind}`
        el.textContent = loc.kind === 'terminal' ? `${loc.location_id} 게이트` : loc.name.replace('(모의)', '').trim()
        new maps.CustomOverlay({ map: m, position: ll(p), content: el, yAnchor: 1.3, zIndex: loc.kind === 'terminal' ? 4 : 2 })
        const dot = document.createElement('div')
        dot.className = `dm-dot ${loc.kind}`
        new maps.CustomOverlay({ map: m, position: ll(p), content: dot, zIndex: 1 })
      }
      allBounds.current = bounds
      m.setBounds(bounds, 40, 40, 40, 40)
      jobLine.current = new maps.Polyline({ map: m, path: [], strokeWeight: 4, strokeColor: '#ff3c00', strokeOpacity: 0.85, strokeStyle: 'dash' })
      for (const v of snapshot.vehicles ?? []) {
        const el = document.createElement('div')
        el.className = 'dm-truck'
        el.setAttribute('role', 'button')
        const overlay = new maps.CustomOverlay({ map: m, position: ll([...pts.values()][0]), content: el, zIndex: 6, clickable: true })
        trucks.current.set(v.vehicle_id, { overlay, el })
      }
      setMapState({ ok: true, msg: '' })
    }).catch((e: Error) => alive && setMapState({ ok: false, msg: `${e.message} 아래 차량별 목록으로 확인할 수 있습니다.` }))
    return () => { alive = false; trucks.current.clear(); kmap.current = null }
  }, [pts, snapshot])

  useEffect(() => {
    const maps = window.kakao?.maps
    if (!mapState.ok || !maps || !kmap.current) return
    kmap.current.setMapTypeId(sky ? maps.MapTypeId.HYBRID : maps.MapTypeId.ROADMAP)
    if (traffic) kmap.current.addOverlayMapTypeId(maps.MapTypeId.TRAFFIC)
    else kmap.current.removeOverlayMapTypeId(maps.MapTypeId.TRAFFIC)
  }, [mapState.ok, traffic, sky])

  useEffect(() => {
    const maps = window.kakao?.maps
    if (!mapState.ok || !maps) return
    const ll = (p: Pt) => new maps.LatLng(p.lat, p.lon)
    // 같은 지점에 선 차량은 조금씩 비켜 그린다.
    const seen = new Map<string, number>()
    for (const v of fleet) {
      const t = trucks.current.get(v.vehicleId)
      if (!t || !v.pos) continue
      const key = `${v.pos.lat.toFixed(4)},${v.pos.lon.toFixed(4)}`
      const n = seen.get(key) ?? 0
      seen.set(key, n + 1)
      t.overlay.setPosition(ll({ lat: v.pos.lat - n * 0.0016, lon: v.pos.lon + n * 0.0022 }))
      const heading = v.from && v.to ? bearing(v.from, v.to) : 0
      const picked = v.vehicleId === selVehicle
      t.el.className = `dm-truck ${v.gate ?? 'none'} ${v.phase}${picked ? ' picked' : ''}`
      t.overlay.setZIndex(picked ? 9 : 6)
      const tail = v.gateEta && v.phase !== 'returning' && v.phase !== 'at_gate' ? ` · ${kstTime(v.gateEta)} 도착` : ''
      t.el.innerHTML = `${truckSvg(heading)}<span><b>${v.vehicleId}</b>${v.jobId ? ` ${v.jobId}` : ''}${tail}</span>`
      t.el.onclick = () => onSelectJob(v.jobId)
    }
    const a = selectedJob ? plan.find(x => x.job_id === selectedJob) : null
    const j = selectedJob ? snapshot.jobs.find(x => x.job_id === selectedJob) : null
    const from = j && pts.get(j.origin_id), to = j && pts.get(j.terminal_id)
    jobLine.current?.setPath(a && from && to ? [ll(from), ll(to)] : [])
  }, [fleet, mapState.ok, selVehicle, selectedJob, plan, snapshot, pts, onSelectJob])

  if (pts.size === 0)
    return <p className="muted small">이 입력에는 위치 좌표가 없어 차량 지도를 표시하지 않습니다. 예제 02로 계산하면 지도를 볼 수 있습니다.</p>

  const focusVehicle = (v: VehicleNow) => {
    onSelectJob(v.jobId)
    const maps = window.kakao?.maps
    if (kmap.current && maps && v.pos) kmap.current.panTo(new maps.LatLng(v.pos.lat, v.pos.lon))
  }
  const gate = [...pts.entries()].find(([id]) => snapshot.locations?.find(l => l.location_id === id)?.kind === 'terminal')?.[1]

  return (
    <section className="dispatch-map">
      <div className="dm-head">
        <div>
          <h3>차량 현황 · 게이트 도착</h3>
          <p className="muted small">지금 시각 {kstTime(new Date(now).toISOString())} 기준 · {planLabel}대로 운행한다고 가정한 위치입니다.</p>
        </div>
        <div className="dm-tools">
          {cand && (
            <div className="vm-seg" role="radiogroup" aria-label="표시할 배차">
              <button type="button" role="radio" aria-checked={usePlan === 'base'} onClick={() => setUsePlan('base')}>원안</button>
              <button type="button" role="radio" aria-checked={usePlan === 'cand'} onClick={() => setUsePlan('cand')}>{cand.method} 조정안</button>
            </div>
          )}
          <label className="dm-toggle"><input type="checkbox" checked={traffic} onChange={e => setTraffic(e.target.checked)} disabled={!mapState.ok} /> 실시간 교통</label>
          <label className="dm-toggle"><input type="checkbox" checked={sky} onChange={e => setSky(e.target.checked)} disabled={!mapState.ok} /> 위성</label>
        </div>
      </div>
      <div className="dm-body">
        <div className="vm-map-wrap">
          <div ref={box} className="dm-map" aria-label="차량 현황 지도" />
          {!mapState.ok && <p className="vm-map-msg muted small" role="status">{mapState.msg}</p>}
          {mapState.ok && (
            <div className="dm-mapbtns">
              <button type="button" onClick={() => allBounds.current && kmap.current?.setBounds(allBounds.current, 40, 40, 40, 40)}>전체</button>
              {gate && <button type="button" onClick={() => { const maps = window.kakao.maps; kmap.current?.setLevel(4); kmap.current?.panTo(new maps.LatLng(gate.lat, gate.lon)) }}>게이트</button>}
            </div>
          )}
        </div>
        <ol className="dm-list" aria-label="차량별 현재 상태">
          {fleet.map(v => (
            <li key={v.vehicleId}>
              <button type="button" className={`dm-item${v.vehicleId === selVehicle ? ' picked' : ''}`} onClick={() => focusVehicle(v)}>
                <span className="dm-item-top"><b>{v.vehicleId}</b> <span className="muted">{PHASE_LABEL[v.phase]}</span>
                  {v.gate && <span className={`dm-gate ${v.gate}`}>{GATE_LABEL[v.gate]}{v.marginMin !== null && v.gate !== 'late' ? ` ${v.marginMin}분` : ''}</span>}
                </span>
                {v.jobId && v.gateEta ? (
                  <span className="small">{v.jobId} 게이트 도착 <b>{kstTime(v.gateEta)}</b> · 반입 마감 {kstTime(v.cutoff)}</span>
                ) : <span className="small muted">남은 작업 없음</span>}
              </button>
            </li>
          ))}
          {unassigned.length > 0 && <li className="dm-unassigned small">미처리 {unassigned.join(', ')} · 배정된 차량이 없어 지도에 표시되지 않습니다</li>}
        </ol>
      </div>
      <p className="muted small dm-foot">차량 위치는 배차 일정으로 계산한 추정이며 실제 GPS가 아닙니다(이동은 직선으로 표시). 실시간 교통은 카카오 교통정보이며 계산된 도착 시각에 자동 반영하지 않습니다. 여유 = 반입 마감 − (도착 + 여유시간 {snapshot.policy.buffer_minutes}분).</p>
    </section>
  )
}
