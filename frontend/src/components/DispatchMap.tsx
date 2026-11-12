// 배차 담당자용 차량 현황 지도: 지금 각 트럭이 어디서 무엇을 하는지(배차 일정 기준 추정)와
// 다음 게이트 도착 예정이 반입 마감 안에 드는지 본다. 실시간 교통은 카카오 교통정보 레이어(실제 자료)다.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { MethodResult, Snapshot } from '../api/types'
import { PHASE_LABEL, locationPoints, vehiclesAt, type Pt, type VehicleNow } from '../lib/fleetPosition'
import { keepLaidOut, loadKakaoMaps } from '../lib/kakaoMaps'
import { LayerMenu } from './LayerMenu'
import { BoxNo, Plate } from './Ids'
import { ROAD_ATTRIBUTION, roadPath } from '../lib/fleetPosition'
import { kstTime } from '../lib/time'
import { jobName, jobInfo, planName, vehicleName, vehicleShort } from '../lib/labels'
import { TripStepper } from './TripStepper'
import { useMapStyle } from '../lib/mapStyle'


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

export function DispatchMap({ snapshot, base, cand, selectedJob, onSelectJob, compact = false }: {
  snapshot: Snapshot
  base: MethodResult | undefined
  cand: MethodResult | undefined
  selectedJob: string | null
  onSelectJob: (jobId: string | null) => void
  /** 홈처럼 아래에 차량 표가 따로 있으면 지도 옆 차량 목록을 숨긴다 */
  compact?: boolean
}) {
  const pts = useMemo(() => locationPoints(snapshot), [snapshot])
  const [usePlan, setUsePlan] = useState<'cand' | 'base'>(cand ? 'cand' : 'base')
  const [clock, setClock] = useState(() => Date.now())
  // 담당자가 '지금 / 30분 뒤 / 1시간 뒤 / 새 반입 마감 시각'에 차량이 어디 있을지 미리 본다.
  const cutoffAt = Date.parse(snapshot.windows.find((w) => w.window_id === snapshot.change.new_window_id)?.closes_at ?? '')
  const [ahead, setAhead] = useState<'now' | '30' | '60' | 'cut'>('now')
  const now = ahead === 'now' ? clock : ahead === 'cut' && Number.isFinite(cutoffAt) ? cutoffAt : clock + Number(ahead === 'cut' ? 0 : ahead) * 60000
  // 실시간 교통은 도착 판단에 바로 쓰이므로 기본으로 켠다. 위성 사진은 '레이어'에서 고른다.
  const [traffic, setTraffic] = useState(true)
  const [style, setStyle] = useMapStyle('dispatch', 'sky')
  const sky = style === 'sky'
  const setSky = (on: boolean) => setStyle(on ? 'sky' : 'map')
  // 지도를 확대·이동할 때마다 화면 거리 기준으로 차량 묶음을 다시 계산한다.
  const [viewTick, setViewTick] = useState(0)
  const [openCluster, setOpenCluster] = useState<string | null>(null)
  const [mapState, setMapState] = useState<{ ok: boolean; msg: string }>({ ok: false, msg: '지도 불러오는 중…' })
  useEffect(() => {
    const id = setInterval(() => setClock(Date.now()), 15000)
    return () => clearInterval(id)
  }, [])

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
  const legLines = useRef<any[]>([])
  const allBounds = useRef<any>(null)
  const focusBounds = useRef<any>(null)
  // 차고지·상차지 이름표. 차량 묶음이 그 자리에 있으면 이름표를 숨기고 묶음에 장소 이름을 붙인다(겹침 방지).
  const placeEls = useRef(new Map<string, { el: HTMLDivElement; pos: Pt; name: string }>())
  // 게이트 이름표(점 왼쪽·오른쪽에 붙음). 게이트에 차량 묶음이 있으면 원 바깥으로 비켜 놓는다.
  const gateEls = useRef(new Map<string, { el: HTMLDivElement; pos: Pt; west: boolean }>())
  // 기본 보기: 지금 차량이 있는 곳 + 게이트. 상차지 전체는 '전체', 게이트 앞은 '게이트'.
  const [mapView, setMapView] = useState<'fleet' | 'gate' | 'all'>('fleet')

  useEffect(() => {
    if (pts.size === 0) return
    let alive = true
    let unobserve = () => {}
    loadKakaoMaps().then(maps => {
      if (!alive || !box.current) return
      const ll = (p: Pt) => new maps.LatLng(p.lat, p.lon)
      const m = new maps.Map(box.current, { center: ll([...pts.values()][0]), level: 8 })
      kmap.current = m
      let touched = false
      maps.event.addListener(m, 'dragstart', () => { touched = true })
      // 차량 중심 맞춤: 지도 상자 크기가 정해진 뒤(홈에서는 옆 열 높이만큼 늘어남)에도 다시 맞춘다. 사용자가 움직이면 그만둔다.
      const fitFleet = () => {
        if (touched || !focusBounds.current) return
        m.setBounds(focusBounds.current, 50, 110, 50, 110)
        if (m.getLevel() < 6) m.setLevel(6)
      }
      unobserve = keepLaidOut(m, box.current, fitFleet)
      const bounds = new maps.LatLngBounds()
      for (const loc of snapshot.locations ?? []) {
        const p = pts.get(loc.location_id)
        if (!p) continue
        bounds.extend(ll(p))
        const el = document.createElement('div')
        el.className = `dm-place ${loc.kind}`
        el.textContent = loc.kind === 'terminal' ? `${loc.location_id} 게이트` : loc.name.replace('(모의)', '').trim()
        // 터미널 두 곳은 가까워서 이름표가 겹친다: 서쪽 터미널은 점의 왼쪽, 동쪽은 오른쪽에 붙인다.
        const terms = (snapshot.locations ?? []).filter(l => l.kind === 'terminal' && l.longitude != null)
        const midLon = terms.reduce((sum, l) => sum + (l.longitude ?? 0), 0) / Math.max(1, terms.length)
        const side = loc.kind === 'terminal' && terms.length > 1 ? (p.lon < midLon ? { xAnchor: 1.08, yAnchor: 0.5 } : { xAnchor: -0.08, yAnchor: 0.5 }) : { yAnchor: 1.3 }
        new maps.CustomOverlay({ map: m, position: ll(p), content: el, ...side, zIndex: loc.kind === 'terminal' ? 4 : 2 })
        if (loc.kind !== 'terminal') placeEls.current.set(loc.location_id, { el, pos: p, name: el.textContent ?? '' })
        else gateEls.current.set(loc.location_id, { el, pos: p, west: terms.length > 1 && p.lon < midLon })
        const dot = document.createElement('div')
        dot.className = `dm-dot ${loc.kind}`
        new maps.CustomOverlay({ map: m, position: ll(p), content: dot, zIndex: 1 })
      }
      allBounds.current = bounds
      // 차량 중심 범위: 게이트 + 지금(계획 기준) 차량 위치
      const focus = new maps.LatLngBounds()
      for (const loc of snapshot.locations ?? []) if (loc.kind === 'terminal' && pts.get(loc.location_id)) focus.extend(ll(pts.get(loc.location_id)!))
      for (const v of vehiclesAt(snapshot, plan, Date.now())) if (v.pos) focus.extend(ll(v.pos))
      focusBounds.current = focus
      fitFleet()
      setTimeout(() => { m.relayout(); fitFleet() }, 400)
      // 넓게 볼 때는 차량 번호만, 확대하면 목적지·도착 시각까지 보여 준다.
      const zoomClass = () => box.current?.classList.toggle('dm-far', m.getLevel() >= 8)
      maps.event.addListener(m, 'zoom_changed', zoomClass)
      maps.event.addListener(m, 'idle', () => setViewTick(x => x + 1))
      zoomClass()
      jobLine.current = new maps.Polyline({ map: m, path: [], strokeWeight: 4, strokeColor: '#2457E6', strokeOpacity: 0.85, strokeStyle: 'dash' })
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
    // 달리고 있는 차량은 지금 구간의 도로 경로를 마감 여유 색으로 옅게 그린다.
    for (const l of legLines.current) l.setMap(null)
    legLines.current = fleet.filter(v => v.path && v.path.length > 1).map(v => new maps.Polyline({
      map: kmap.current, path: v.path!.map(ll), strokeWeight: v.vehicleId === selVehicle ? 6 : 4,
      strokeColor: v.gate === 'late' ? '#c0262d' : v.gate === 'tight' ? '#d97706' : '#15803d', strokeOpacity: v.vehicleId === selVehicle ? 0.9 : 0.45,
    }))
    // 화면에서 46px 안에 있는 차량은 하나의 묶음으로 합친다(지도 서비스의 마커 묶음 방식). 누르면 확대해 풀린다.
    const proj = kmap.current.getProjection()
    const clusters: { x: number; y: number; list: VehicleNow[] }[] = []
    for (const v of fleet) {
      if (!v.pos) continue
      const pt = proj.containerPointFromCoords(ll(v.pos))
      const near = clusters.find(c => Math.hypot(c.x - pt.x, c.y - pt.y) < 46)
      if (near) near.list.push(v)
      else clusters.push({ x: pt.x, y: pt.y, list: [v] })
    }
    const zoomedIn = kmap.current.getLevel() <= 6
    // 묶음·차량이 차고지·상차지 이름표 위에 있으면 이름표를 숨기고 그 장소 이름을 묶음 아래에 붙인다.
    const placeAt = new Map<(typeof clusters)[number], string>()
    for (const place of placeEls.current.values()) {
      const pp = proj.containerPointFromCoords(ll(place.pos))
      const hit = clusters.find(c => Math.hypot(c.x - pp.x, c.y - pp.y) < 44)
      place.el.style.visibility = hit ? 'hidden' : ''
      if (hit && !placeAt.has(hit)) placeAt.set(hit, place.name)
    }
    for (const gate of gateEls.current.values()) {
      const gp = proj.containerPointFromCoords(ll(gate.pos))
      const hit = clusters.some(c => Math.hypot(c.x - gp.x, c.y - gp.y) < 30)
      gate.el.style.marginRight = hit && gate.west ? '20px' : ''
      gate.el.style.marginLeft = hit && !gate.west ? '20px' : ''
    }
    for (const c of clusters) {
      const at = placeAt.get(c)
      const list = c.list
      const v = list[0]
      const el = document.createElement('div')
      const picked = list.some(x => x.vehicleId === selVehicle)
      const worst = list.some(x => x.gate === 'late') ? 'late' : list.some(x => x.gate === 'tight') ? 'tight' : list.some(x => x.gate === 'ok') ? 'ok' : 'none'
      if (list.length > 1) {
        const key = list.map(x => x.vehicleId).sort().join(',')
        el.className = `dm-cluster ${worst}${picked ? ' picked' : ''}${openCluster === key ? ' open' : ''}`
        el.innerHTML = `<b>${list.length}</b><span>대</span>${at ? `<em class="cl-place">${at}</em>` : ''}`
        // 같은 자리(차고지 대기 등)에 모인 차량은 확대해도 갈라지지 않으므로 목록을 펼친다. 흩어져 있으면 확대한다.
        const spread = Math.max(...list.map(x => Math.hypot((x.pos!.lat - v.pos!.lat) * 111000, (x.pos!.lon - v.pos!.lon) * 91000)))
        const pop = document.createElement('div')
        pop.className = 'cl-list'
        for (const x of list) {
          const b = document.createElement('button')
          b.type = 'button'
          b.className = `cl-item ${x.gate ?? 'none'}`
          b.innerHTML = `<b>${vehicleName(x.vehicleId)}</b><span>${PHASE_LABEL[x.phase]}</span>`
          b.onclick = (e) => { e.stopPropagation(); setPickedVehicle(x.vehicleId); onSelectJob(x.jobId) }
          pop.appendChild(b)
        }
        el.appendChild(pop)
        el.onclick = () => {
          const m = kmap.current
          if (spread > 60 && m.getLevel() > 3) m.setLevel(Math.max(1, m.getLevel() - 2), { anchor: ll(v.pos!) })
          else setOpenCluster(openCluster === key ? null : key)
        }
        pins.current.push(new maps.CustomOverlay({ map: kmap.current, position: ll(v.pos!), content: el, yAnchor: 0.5, zIndex: picked ? 9 : 7, clickable: true }))
        continue
      }
      el.className = `dm-pin ${worst}${picked ? ' picked' : ''}`
      const heading = v.from && v.to ? bearing(v.from, v.to) : 90
      const what = v.phase === 'to_gate' && v.gateEta ? `→ 게이트 ${kstTime(v.gateEta)}`
        : v.phase === 'to_origin' && v.jobId ? `→ ${placeName(snapshot.jobs.find(j => j.job_id === v.jobId)?.origin_id ?? '')}`
        : v.phase === 'returning' ? '→ 차고지'
        : PHASE_LABEL[v.phase]
      // 이름표는 짧게(번호판 뒤 4자리). 목적지·도착 시각은 고른 차량이거나 충분히 확대했을 때만.
      el.innerHTML = `${truckSvg(heading)}<b>${vehicleShort(v.vehicleId)}</b>${picked || zoomedIn ? `<span>${what}</span>` : at ? `<span>${at}</span>` : ''}`
      el.setAttribute('aria-label', `${vehicleName(v.vehicleId)} ${PHASE_LABEL[v.phase]}`)
      el.onclick = () => { setPickedVehicle(v.vehicleId); onSelectJob(v.jobId) }
      pins.current.push(new maps.CustomOverlay({ map: kmap.current, position: ll(v.pos!), content: el, yAnchor: 1.25, zIndex: picked ? 9 : 6, clickable: true }))
    }
    const a = selectedJob ? plan.find(x => x.job_id === selectedJob) : null
    const j = selectedJob ? snapshot.jobs.find(x => x.job_id === selectedJob) : null
    const from = j && pts.get(j.origin_id), to = j && pts.get(j.terminal_id)
    const road = j ? roadPath(j.origin_id, j.terminal_id) : null
    jobLine.current?.setPath(a && road ? road.map(ll) : a && from && to ? [ll(from), ll(to)] : [])
  }, [fleet, mapState.ok, selVehicle, selectedJob, plan, snapshot, pts, onSelectJob, viewTick, openCluster])

  const sel = fleet.find(v => v.vehicleId === selVehicle) ?? null
  const selPlan = sel ? plan.filter(a => a.vehicle_id === sel.vehicleId).sort((x, y) => x.sequence - y.sequence) : []
  const cur = sel?.jobId ? selPlan.find(a => a.job_id === sel.jobId) : undefined
  const curJob = cur ? snapshot.jobs.find(j => j.job_id === cur.job_id) : undefined
  const next = cur ? selPlan.find(a => a.sequence > cur.sequence) : undefined

  if (pts.size === 0)
    return <p className="muted small">위치 정보가 없어 지도를 표시하지 않습니다.</p>

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
          <h3>차량 현황</h3>
          <p className="muted small"><b>{kstTime(new Date(now).toISOString())}</b> {ahead === 'now' ? '현재' : '예상'} · {planLabel} 기준 위치</p>
        </div>
        <div className="dm-tools">
          {cand && (
            <div className="vm-seg" role="radiogroup" aria-label="표시할 배차">
              <button type="button" role="radio" aria-checked={usePlan === 'base'} onClick={() => setUsePlan('base')}>원래 배차</button>
              <button type="button" role="radio" aria-checked={usePlan === 'cand'} onClick={() => setUsePlan('cand')}>{planName(cand.method)}</button>
            </div>
          )}
          <div className="seg" role="group" aria-label="지도 범위">
            {([['fleet', '차량 중심'], ['gate', '게이트'], ['all', '전체']] as const).map(([id, label]) => (
              <button key={id} type="button" aria-pressed={mapView === id} disabled={!mapState.ok || (id === 'gate' && !gate)} onClick={() => {
                setMapView(id)
                const m = kmap.current, maps = window.kakao?.maps
                if (!m || !maps) return
                if (id === 'all' && allBounds.current) m.setBounds(allBounds.current, 40, 110, 40, 110)
                else if (id === 'fleet' && focusBounds.current) { m.setBounds(focusBounds.current, 50, 110, 50, 110); if (m.getLevel() < 6) m.setLevel(6) }
                else if (id === 'gate' && gate) { m.setLevel(4); m.panTo(new maps.LatLng(gate.lat, gate.lon)) }
              }}>{label}</button>
            ))}
          </div>
          <div className="seg" role="group" aria-label="언제 위치를 볼지">
            {([['now', '지금'], ['30', '30분 뒤'], ['60', '1시간 뒤'], ['cut', '마감 시각']] as const).map(([id, label]) => (
              <button key={id} type="button" aria-pressed={ahead === id} disabled={id === 'cut' && !Number.isFinite(cutoffAt)} onClick={() => setAhead(id)}>{label}</button>
            ))}
          </div>
          <LayerMenu sky={sky} onSky={setSky} traffic={traffic} onTraffic={setTraffic} disabled={!mapState.ok} />
        </div>
      </div>
      <div className="dm-body">
        <div className="vm-map-wrap">
          <div ref={box} className="dm-map" aria-label="차량 현황 지도" />
          {!mapState.ok && <p className="vm-map-msg muted small" role="status">{mapState.msg}</p>}
          {mapState.ok && (
            <div className="map-legend" aria-label="범례">
              <span><i className="lg ok-g" />여유 있음</span><span><i className="lg tight" />빠듯함(20분 미만)</span><span><i className="lg late" />마감 넘김</span><span><i className="lg idle" />대기</span>
            </div>
          )}
          {mapState.ok && <span className="map-credit">{ROAD_ATTRIBUTION}</span>}
        </div>
        {!compact && <div className="dm-side">
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
                  <div><dt>일정</dt><dd>상차지 출발 {kstTime(cur.pickup_departure_at)} · 게이트 도착 <b>{kstTime(cur.gate_arrival_at)}</b> · 복귀 {kstTime(cur.return_at)}</dd></div>
                  <div><dt>반입 마감</dt><dd>{kstTime(sel.cutoff)}{sel.marginMin !== null && (sel.gate === 'late' ? <b className="dm-late"> · 마감 초과</b> : ` · 여유 ${sel.marginMin}분`)}</dd></div>
                  <div><dt>다음 작업</dt><dd>{next ? `${jobName(next.job_id)} · ${kstTime(next.pickup_departure_at)} 출발` : '없음'}</dd></div>
                </>
              ) : <div><dt>작업</dt><dd>남은 작업 없음</dd></div>}
              <div><dt>위치</dt><dd className="muted">배차 일정 기준 추정</dd></div>
            </dl>
          </div>
        ) : <p className="muted small dm-hint">지도에서 차량을 누르거나 목록·작업표에서 고르면 일정이 보입니다.</p>}
        <ol className="dm-list" aria-label="차량별 현재 상태">
          {[...fleet].sort((a, b) => ((a.gate === 'late' ? 0 : a.gate === 'tight' ? 1 : a.gate === 'ok' ? 2 : 3) * 10000 + (a.marginMin ?? 9999)) - ((b.gate === 'late' ? 0 : b.gate === 'tight' ? 1 : b.gate === 'ok' ? 2 : 3) * 10000 + (b.marginMin ?? 9999))).map(v => (
            <li key={v.vehicleId}>
              <button type="button" className={`dm-item${v.vehicleId === selVehicle ? ' picked' : ''}`} onClick={() => focusVehicle(v)}>
                <span className="dmi-top">
                  <Plate id={v.vehicleId} />
                  <span className="dmi-phase">{PHASE_LABEL[v.phase]}</span>
                  {v.gate && v.marginMin !== null && <span className={`st ${v.gate === 'late' ? 'bad' : v.gate === 'tight' ? 'warn' : 'ok'}`}>{v.gate === 'late' ? `${-v.marginMin}분 늦음` : `${v.marginMin}분 여유`}</span>}
                </span>
                {v.jobId && <TripStepper phase={v.phase} late={v.gate === 'late'} compact />}
                {v.jobId && v.gateEta ? (
                  <span className="dmi-line"><BoxNo jobId={v.jobId} /> <span className="nowrap">· 게이트 <b>{kstTime(v.gateEta)}</b> · 마감 {kstTime(v.cutoff)}</span></span>
                ) : <span className="dmi-line">남은 작업 없음</span>}
              </button>
            </li>
          ))}
          {unassigned.length > 0 && <li className="dm-unassigned small">미처리 {unassigned.map(jobName).join(', ')} · 배정된 차량 없음</li>}
        </ol>
        </div>}
      </div>
    </section>
  )
}
