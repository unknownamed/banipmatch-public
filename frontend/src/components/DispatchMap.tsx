// 배차 담당자용 차량 현황 지도: 지금 각 트럭이 어디서 무엇을 하는지(배차 일정 기준 추정)와
// 다음 게이트 도착 예정이 반입 마감 안에 드는지 본다. 실시간 교통은 카카오 교통정보 레이어(실제 자료)다.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { MethodResult, Snapshot } from '../api/types'
import { PHASE_LABEL, locationPoints, vehiclesAt, type Pt, type VehicleNow } from '../lib/fleetPosition'
import { keepLaidOut, loadKakaoMaps } from '../lib/kakaoMaps'
import { kstTime } from '../lib/time'
import { jobName, jobInfo, planName, vehicleName, vehicleShort } from '../lib/labels'
import { TripStepper } from './TripStepper'

const GATE_LABEL = { ok: '여유', tight: '빠듯', late: '마감 초과' } as const

// 옆에서 본 트럭(방향은 글자 화살표로 표시). 핀 안에서는 회전하지 않는다.
function truckSvg(_heading?: number) {
  return `<svg class="truck" viewBox="0 0 24 14" width="22" height="13" aria-hidden="true">`
    + `<rect class="box" x="0.5" y="1" width="14" height="9" rx="1.2"/>`
    + `<path class="cab" d="M15.5 4 H20 L23 7.5 V10 H15.5 Z"/>`
    + `<circle cx="4.5" cy="11.5" r="2" class="wheel"/><circle cx="18.5" cy="11.5" r="2" class="wheel"/></svg>`
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
  // 기본은 실제 시각. 발표 시연에서는 10·60배로 흘려 일정대로 움직이는 모습을 보여 준다.
  const [speed, setSpeed] = useState<1 | 10 | 60>(1)
  const [traffic, setTraffic] = useState(false)
  const [sky, setSky] = useState(false)
  const [mapState, setMapState] = useState<{ ok: boolean; msg: string }>({ ok: false, msg: '지도 불러오는 중…' })
  useEffect(() => {
    const id = setInterval(() => setNow(x => (speed === 1 ? Date.now() : x + 1000 * speed)), speed === 1 ? 15000 : 1000)
    return () => clearInterval(id)
  }, [speed])

  const plan = usePlan === 'cand' && cand ? cand.assignments : base?.assignments ?? snapshot.baseline_assignments
  const planLabel = usePlan === 'cand' && cand ? planName(cand.method) : '원래 배차'
  const unassigned = usePlan === 'cand' && cand ? cand.unassigned_job_ids : base?.unassigned_job_ids ?? snapshot.baseline_unassigned_job_ids
  const fleet = useMemo(() => vehiclesAt(snapshot, plan, now), [snapshot, plan, now])
  const [pickedVehicle, setPickedVehicle] = useState<string | null>(null)
  const selVehicle = (selectedJob ? plan.find(a => a.job_id === selectedJob)?.vehicle_id : null) ?? pickedVehicle
  const placeName = (id: string) => snapshot.locations?.find(l => l.location_id === id)?.name.replace('(모의)', '').trim() ?? id

  const box = useRef<HTMLDivElement>(null)
  const kmap = useRef<any>(null)
  const pins = useRef<any[]>([])
  const jobLine = useRef<any>(null)
  const allBounds = useRef<any>(null)

  useEffect(() => {
    if (pts.size === 0) return
    let alive = true
    let unobserve = () => {}
    loadKakaoMaps().then(maps => {
      if (!alive || !box.current) return
      const ll = (p: Pt) => new maps.LatLng(p.lat, p.lon)
      const m = new maps.Map(box.current, { center: ll([...pts.values()][0]), level: 8 })
      kmap.current = m
      unobserve = keepLaidOut(m, box.current)
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
      // 넓게 볼 때는 차량 번호만, 확대하면 목적지·도착 시각까지 보여 준다.
      const zoomClass = () => box.current?.classList.toggle('dm-far', m.getLevel() >= 8)
      maps.event.addListener(m, 'zoom_changed', zoomClass)
      zoomClass()
      jobLine.current = new maps.Polyline({ map: m, path: [], strokeWeight: 4, strokeColor: '#ff3c00', strokeOpacity: 0.85, strokeStyle: 'dash' })
      setMapState({ ok: true, msg: '' })
    }).catch((e: Error) => alive && setMapState({ ok: false, msg: `${e.message} 아래 차량별 목록으로 확인할 수 있습니다.` }))
    return () => { alive = false; unobserve(); pins.current = []; kmap.current = null }
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
    // 같은 자리(약 100m 안)의 차량은 핀 하나로 묶는다. 이동 중인 차량은 각자 목적지와 도착 시각을 보여 준다.
    for (const o of pins.current) o.setMap(null)
    pins.current = []
    const groups = new Map<string, VehicleNow[]>()
    for (const v of fleet) {
      if (!v.pos) continue
      const moving = v.phase === 'to_gate' || v.phase === 'to_origin' || v.phase === 'returning'
      const key = moving ? v.vehicleId : `${v.pos.lat.toFixed(3)},${v.pos.lon.toFixed(3)}`
      groups.set(key, [...(groups.get(key) ?? []), v])
    }
    for (const list of groups.values()) {
      const v = list[0]
      const el = document.createElement('div')
      const picked = list.some(x => x.vehicleId === selVehicle)
      const worst = list.some(x => x.gate === 'late') ? 'late' : list.some(x => x.gate === 'tight') ? 'tight' : list.some(x => x.gate === 'ok') ? 'ok' : 'none'
      el.className = `dm-pin ${worst}${picked ? ' picked' : ''}`
      const heading = v.from && v.to ? bearing(v.from, v.to) : 90
      const ids = list.map(x => vehicleShort(x.vehicleId)).join(' · ')
      const what = list.length > 1 ? PHASE_LABEL[v.phase]
        : v.phase === 'to_gate' && v.gateEta ? `→ 게이트 ${kstTime(v.gateEta)}`
        : v.phase === 'to_origin' && v.jobId ? `→ 상차지 ${placeName(snapshot.jobs.find(j => j.job_id === v.jobId)?.origin_id ?? '')}`
        : v.phase === 'returning' ? '→ 차고지 복귀'
        : PHASE_LABEL[v.phase]
      el.innerHTML = `${truckSvg(heading)}<b>${ids}</b><span>${what}</span>`
      el.onclick = () => { setPickedVehicle(v.vehicleId); onSelectJob(v.jobId) }
      pins.current.push(new maps.CustomOverlay({ map: kmap.current, position: ll(v.pos!), content: el, yAnchor: 1.25, zIndex: picked ? 9 : list.length > 1 ? 5 : 6, clickable: true }))
    }
    const a = selectedJob ? plan.find(x => x.job_id === selectedJob) : null
    const j = selectedJob ? snapshot.jobs.find(x => x.job_id === selectedJob) : null
    const from = j && pts.get(j.origin_id), to = j && pts.get(j.terminal_id)
    jobLine.current?.setPath(a && from && to ? [ll(from), ll(to)] : [])
  }, [fleet, mapState.ok, selVehicle, selectedJob, plan, snapshot, pts, onSelectJob])

  const sel = fleet.find(v => v.vehicleId === selVehicle) ?? null
  const selPlan = sel ? plan.filter(a => a.vehicle_id === sel.vehicleId).sort((x, y) => x.sequence - y.sequence) : []
  const cur = sel?.jobId ? selPlan.find(a => a.job_id === sel.jobId) : undefined
  const curJob = cur ? snapshot.jobs.find(j => j.job_id === cur.job_id) : undefined
  const next = cur ? selPlan.find(a => a.sequence > cur.sequence) : undefined

  if (pts.size === 0)
    return <p className="muted small">이 입력에는 위치 좌표가 없어 차량 지도를 표시하지 않습니다. 예제 02로 계산하면 지도를 볼 수 있습니다.</p>

  const focusVehicle = (v: VehicleNow) => {
    setPickedVehicle(v.vehicleId)
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
          <p className="muted small"><b>{kstTime(new Date(now).toISOString())}</b> {speed === 1 ? '현재' : `${speed}배속`} · {planLabel} 기준 위치</p>
        </div>
        <div className="dm-tools">
          {cand && (
            <div className="vm-seg" role="radiogroup" aria-label="표시할 배차">
              <button type="button" role="radio" aria-checked={usePlan === 'base'} onClick={() => setUsePlan('base')}>원안</button>
              <button type="button" role="radio" aria-checked={usePlan === 'cand'} onClick={() => setUsePlan('cand')}>{planName(cand.method)}</button>
            </div>
          )}
          <label className="vm-speed small">시간 배속
            <select value={speed} onChange={e => { const v = Number(e.target.value) as 1 | 10 | 60; setSpeed(v); if (v === 1) setNow(Date.now()) }}>
              <option value={1}>실시간</option>
              <option value={10}>10배</option>
              <option value={60}>60배</option>
            </select>
          </label>
          <label className="dm-toggle"><input type="checkbox" checked={traffic} onChange={e => setTraffic(e.target.checked)} disabled={!mapState.ok} /> 실시간 교통</label>
          <label className="dm-toggle"><input type="checkbox" checked={sky} onChange={e => setSky(e.target.checked)} disabled={!mapState.ok} /> 위성</label>
        </div>
      </div>
      <div className="dm-body">
        <div className="vm-map-wrap">
          <div ref={box} className="dm-map" aria-label="차량 현황 지도" />
          {!mapState.ok && <p className="vm-map-msg muted small" role="status">{mapState.msg}</p>}
          {mapState.ok && (
            <div className="map-legend" aria-label="범례">
              <span><i className="lg ok-g" />마감 여유</span><span><i className="lg tight" />빠듯(20분 미만)</span><span><i className="lg late" />마감 초과</span><span><i className="lg idle" />작업 없음</span>
            </div>
          )}
          {mapState.ok && (
            <div className="dm-mapbtns">
              <button type="button" onClick={() => allBounds.current && kmap.current?.setBounds(allBounds.current, 40, 40, 40, 40)}>전체</button>
              {gate && <button type="button" onClick={() => { const maps = window.kakao.maps; kmap.current?.setLevel(4); kmap.current?.panTo(new maps.LatLng(gate.lat, gate.lon)) }}>게이트</button>}
            </div>
          )}
        </div>
        <div className="dm-side">
        {sel ? (
          <div className="vm-info" aria-live="polite">
            <div className="vm-info-head"><b>{vehicleName(sel.vehicleId)}</b><span className={`dm-gate ${sel.gate ?? 'none'}`}>{PHASE_LABEL[sel.phase]}</span></div>
            {sel.jobId && <TripStepper phase={sel.phase} late={sel.gate === 'late'} />}
            <dl>
              {cur && curJob ? (
                <>
                  <div><dt>컨테이너</dt><dd>{jobName(cur.job_id)} · {curJob.equipment_type === 'DRY40' ? '40ft' : curJob.equipment_type === 'DRY20' ? '20ft' : curJob.equipment_type}</dd></div>
                  <div><dt>항차 · 화주</dt><dd>{curJob.voyage_id}{curJob.cargo_owner ? ` · ${curJob.cargo_owner}` : ''}{jobInfo(cur.job_id)?.booking ? ` · 부킹 ${jobInfo(cur.job_id)!.booking}` : ''}</dd></div>
                  <div><dt>경로</dt><dd>{placeName(curJob.origin_id)} → {placeName(curJob.terminal_id)}</dd></div>
                  <div><dt>일정</dt><dd>출발 {kstTime(cur.pickup_departure_at)} · 도착 <b>{kstTime(cur.gate_arrival_at)}</b> · 복귀 {kstTime(cur.return_at)}</dd></div>
                  <div><dt>반입 마감</dt><dd>{kstTime(sel.cutoff)}{sel.marginMin !== null && (sel.gate === 'late' ? <b className="dm-late"> · 마감 초과</b> : ` · 여유 ${sel.marginMin}분`)}</dd></div>
                  <div><dt>다음 작업</dt><dd>{next ? `${jobName(next.job_id)} · ${kstTime(next.pickup_departure_at)} 출발` : '없음'}</dd></div>
                </>
              ) : <div><dt>작업</dt><dd>남은 작업 없음</dd></div>}
              <div><dt>위치</dt><dd className="muted">배차 일정 기준 추정</dd></div>
            </dl>
          </div>
        ) : <p className="muted small dm-hint">지도에서 차량을 누르거나 목록·작업표에서 고르면 일정이 보입니다.</p>}
        <ol className="dm-list" aria-label="차량별 현재 상태">
          {fleet.map(v => (
            <li key={v.vehicleId}>
              <button type="button" className={`dm-item${v.vehicleId === selVehicle ? ' picked' : ''}`} onClick={() => focusVehicle(v)}>
                <span className="dm-item-top"><b>{vehicleName(v.vehicleId)}</b> <span className="muted">{PHASE_LABEL[v.phase]}</span>
                  {v.gate && <span className={`dm-gate ${v.gate}`}>{GATE_LABEL[v.gate]}{v.marginMin !== null && v.gate !== 'late' ? ` ${v.marginMin}분` : ''}</span>}
                </span>
                {v.jobId && <TripStepper phase={v.phase} late={v.gate === 'late'} />}
                {v.jobId && v.gateEta ? (
                  <span className="small">{jobName(v.jobId)} · 게이트 <b>{kstTime(v.gateEta)}</b> · 마감 {kstTime(v.cutoff)}</span>
                ) : <span className="small muted">남은 작업 없음</span>}
              </button>
            </li>
          ))}
          {unassigned.length > 0 && <li className="dm-unassigned small">미처리 {unassigned.map(jobName).join(', ')} · 배정된 차량 없음</li>}
        </ol>
        </div>
      </div>
      <details className="tech-info dm-foot">
        <summary>자료 설명</summary>
        차량 위치는 배차 일정으로 계산한 추정이며(이동은 직선 표시), 차량 GPS가 연결되면 실제 위치로 대체됩니다. 실시간 교통은 카카오 교통정보이며 계산된 도착 시각에 자동 반영하지 않습니다. 여유 = 반입 마감 − (도착 + 여유시간 {snapshot.policy.buffer_minutes}분).
      </details>
    </section>
  )
}
