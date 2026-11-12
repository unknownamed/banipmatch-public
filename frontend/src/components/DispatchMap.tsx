// 배차 담당자용 차량 현황 지도: 지금 각 트럭이 어디서 무엇을 하는지(배차 일정 기준 추정)와
// 다음 게이트 도착 예정이 반입 마감 안에 드는지 본다. 실시간 교통은 카카오 교통정보 레이어(실제 자료)다.
import { useEffect, useMemo, useRef, useState } from 'react'
import type { MethodResult, Snapshot } from '../api/types'
import { PHASE_LABEL, distanceKm, locationPoints, vehiclesAt, type Pt, type VehicleNow } from '../lib/fleetPosition'
import { keepLaidOut, loadKakaoMaps } from '../lib/kakaoMaps'
import { LayerMenu } from './LayerMenu'
import { BoxNo, Plate } from './Ids'
import { ROAD_ATTRIBUTION, roadPath } from '../lib/fleetPosition'
import { kstTime } from '../lib/time'
import { jobName, jobInfo, planName, vehicleName, vehicleShort } from '../lib/labels'
import { TripStepper } from './TripStepper'
import { useMapStyle } from '../lib/mapStyle'
import { useDriverLocations } from '../lib/driverLocations'


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

export function DispatchMap({ snapshot, base, cand, selectedJob, onSelectJob, compact = false, pickedVehicleId, onPickVehicle }: {
  snapshot: Snapshot
  base: MethodResult | undefined
  cand: MethodResult | undefined
  selectedJob: string | null
  onSelectJob: (jobId: string | null) => void
  /** 홈처럼 아래에 차량 표가 따로 있으면 지도 옆 차량 목록을 숨긴다 */
  compact?: boolean
  /** 홈처럼 지도 밖 표와 차량 선택을 맞출 때: 바깥에서 고른 차량, 지도에서 고르면 알려 줌 */
  pickedVehicleId?: string | null
  onPickVehicle?: (vehicleId: string | null) => void
}) {
  const pts = useMemo(() => locationPoints(snapshot), [snapshot])
  const [usePlan, setUsePlan] = useState<'cand' | 'base'>(cand ? 'cand' : 'base')
  const [clock, setClock] = useState(() => Date.now())
  // 담당자가 시간 막대를 밀어 앞으로 차량이 어디 있을지 미리 본다(선박 지도와 같은 방식).
  const cutoffAt = Date.parse(snapshot.windows.find((w) => w.window_id === snapshot.change.new_window_id)?.closes_at ?? '')
  const [ahead, setAhead] = useState(0)
  const now = clock + ahead * 60000
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
    // 배차 일정상 위치가 도로를 따라 조금씩 움직이도록 자주 갱신한다.
    const id = setInterval(() => setClock(Date.now()), 2000)
    return () => clearInterval(id)
  }, [])

  const plan = usePlan === 'cand' && cand ? cand.assignments : base?.assignments ?? snapshot.baseline_assignments
  const planLabel = usePlan === 'cand' && cand ? planName(cand.method) : '원래 배차'
  // 조정안을 볼 때 원래 배차와 일정이 달라지는 차량(작업을 넘기거나 받거나 시각이 바뀜)을 표시한다.
  const changedVehicles = useMemo(() => {
    const out = new Set<string>()
    if (!cand) return out
    for (const id of cand.metrics.changed_job_ids) {
      const b = (base?.assignments ?? snapshot.baseline_assignments).find((a) => a.job_id === id)?.vehicle_id
      const c = cand.assignments.find((a) => a.job_id === id)?.vehicle_id
      if (b) out.add(b)
      if (c) out.add(c)
    }
    return out
  }, [cand, base, snapshot])
  const showChanged = usePlan === 'cand' && changedVehicles.size > 0
  const unassigned = usePlan === 'cand' && cand ? cand.unassigned_job_ids : base?.unassigned_job_ids ?? snapshot.baseline_unassigned_job_ids
  // 기사가 휴대폰 위치를 보내 주면 지금 위치는 그 값을 쓴다(미래 위치를 볼 때는 일정 기준).
  const driverLocs = useDriverLocations()
  const fleet = useMemo(() => vehiclesAt(snapshot, plan, now).map((v) => {
    const loc = ahead === 0 ? driverLocs.get(v.vehicleId) : undefined
    if (!loc) return v
    const actual = { lat: loc.latitude, lon: loc.longitude }
    // 위치만으로는 작업 중인지·늦는지 알 수 없으므로 마감 여유·색은 배차 일정 기준 그대로 두고,
    // 일정상 위치와 떨어진 거리(사실)만 함께 보여 담당자가 기사에게 확인하게 한다.
    return { ...v, pos: actual, path: null, live: { captured_at: loc.captured_at, accuracy_m: loc.accuracy_m, offKm: Math.round(distanceKm(v.pos, actual) * 10) / 10 } }
  }), [snapshot, plan, now, driverLocs, ahead])
  const liveCount = fleet.filter((v) => v.live).length
  // 막대 끝은 이 배차의 마지막 복귀 시각(최소 1시간)까지다.
  const lastReturn = Math.max(...plan.map((a) => Date.parse(a.return_at)).filter(Number.isFinite), clock)
  const maxAhead = Math.max(60, Math.ceil((lastReturn - clock) / 600000) * 10)
  const cutAhead = Number.isFinite(cutoffAt) && cutoffAt > clock ? Math.round((cutoffAt - clock) / 60000) : null
  const [pickedVehicle, setPickedVehicleState] = useState<string | null>(null)
  const setPickedVehicle = (id: string | null) => { setPickedVehicleState(id); onPickVehicle?.(id) }
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
    // 게이트 이름표: 기본 자리(서쪽 터미널은 점 왼쪽, 동쪽은 오른쪽)가 차량·묶음·장소 이름표와 겹치면
    // 반대쪽·위·아래 중 비어 있는 자리로 옮긴다(모두 막히면 가장 덜 겹치는 자리).
    type Box = [number, number, number, number]
    const overlap = (a: Box, b: Box) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]))
    const obstacles: Box[] = clusters.map(c => (c.list.length > 1 ? [c.x - 26, c.y - 26, c.x + 26, c.y + 26] : [c.x - 45, c.y - 42, c.x + 45, c.y - 4]) as Box)
    for (const place of placeEls.current.values()) {
      if (place.el.style.visibility === 'hidden') continue
      const pp = proj.containerPointFromCoords(ll(place.pos))
      const pw = place.el.offsetWidth || 80, ph = place.el.offsetHeight || 22
      obstacles.push([pp.x - pw / 2, pp.y - ph * 1.3, pp.x + pw / 2, pp.y - ph * 0.3])
    }
    const placed: Box[] = []
    for (const gate of gateEls.current.values()) {
      const gp = proj.containerPointFromCoords(ll(gate.pos))
      const w = gate.el.offsetWidth || 90, h = gate.el.offsetHeight || 24
      const x0 = gate.west ? gp.x - w * 1.08 : gp.x + w * 0.08, y0 = gp.y - h / 2
      const side = gate.west ? 1 : -1 // 반대쪽으로 갈 때의 방향
      // 기본 자리 → 같은 쪽으로 조금 더 바깥(점 위의 묶음 원을 비켜 감) → 반대쪽 → 위 → 아래
      const moves: [number, number][] = [[0, 0], [-side * 34, 0], [side * w * 1.16, 0], [side * (w * 1.16 + 34), 0], [side * w * 0.58, -(h / 2 + 32)], [side * w * 0.58, h / 2 + 32]]
      let best = moves[0], bestHit = Infinity
      for (const [dx, dy] of moves) {
        const box: Box = [x0 + dx, y0 + dy, x0 + dx + w, y0 + dy + h]
        const hit = [...obstacles, ...placed].reduce((sum, o) => sum + overlap(box, o), 0)
        if (hit < bestHit) { best = [dx, dy]; bestHit = hit }
        if (hit === 0) break
      }
      gate.el.style.transform = best[0] || best[1] ? `translate(${Math.round(best[0])}px, ${Math.round(best[1])}px)` : ''
      placed.push([x0 + best[0], y0 + best[1], x0 + best[0] + w, y0 + best[1] + h])
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
        el.className = `dm-cluster ${worst}${picked ? ' picked' : ''}${openCluster === key ? ' open' : ''}${list.some(x => x.live) ? ' live' : ''}${showChanged && list.some(x => changedVehicles.has(x.vehicleId)) ? ' changed' : ''}`
        el.innerHTML = `<b>${list.length}</b><span>대</span>${at ? `<em class="cl-place">${at}</em>` : ''}`
        // 같은 자리(차고지 대기 등)에 모인 차량은 확대해도 갈라지지 않으므로 목록을 펼친다. 흩어져 있으면 확대한다.
        const spread = Math.max(...list.map(x => Math.hypot((x.pos!.lat - v.pos!.lat) * 111000, (x.pos!.lon - v.pos!.lon) * 91000)))
        const pop = document.createElement('div')
        pop.className = 'cl-list'
        for (const x of list) {
          const b = document.createElement('button')
          b.type = 'button'
          b.className = `cl-item ${x.gate ?? 'none'}${x.live ? ' live' : ''}`
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
      el.className = `dm-pin ${worst}${picked ? ' picked' : ''}${v.live ? ' live' : ''}${showChanged && changedVehicles.has(v.vehicleId) ? ' changed' : ''}`
      // 휴대폰 위치는 일정상 진행 방향과 무관하므로 트럭 방향을 돌리지 않는다.
      const heading = !v.live && v.from && v.to ? bearing(v.from, v.to) : 90
      const what = v.phase === 'to_gate' && v.gateEta ? `→ 게이트 ${kstTime(v.gateEta)}`
        : v.phase === 'to_origin' && v.jobId ? `→ ${placeName(snapshot.jobs.find(j => j.job_id === v.jobId)?.origin_id ?? '')}`
        : v.phase === 'returning' ? '→ 차고지'
        : PHASE_LABEL[v.phase]
      // 이름표는 짧게(번호판 뒤 4자리). 목적지·도착 시각은 고른 차량이거나 충분히 확대했을 때만.
      // 휴대폰 위치는 언제 받은 위치인지 항상 보여 준다.
      const liveText = v.live ? (() => { const m = Math.round((Date.now() - Date.parse(v.live!.captured_at)) / 60000); return `기사 위치, ${m < 1 ? '방금' : `${m}분 전`}` })() : null
      el.innerHTML = `${truckSvg(heading)}<b>${vehicleShort(v.vehicleId)}</b>${liveText ? `<span>${liveText}</span>` : picked || zoomedIn ? `<span>${what}</span>` : at ? `<span>${at}</span>` : ''}`
      el.setAttribute('aria-label', `${vehicleName(v.vehicleId)} ${PHASE_LABEL[v.phase]}`)
      el.onclick = () => { setPickedVehicle(v.vehicleId); onSelectJob(v.jobId) }
      pins.current.push(new maps.CustomOverlay({ map: kmap.current, position: ll(v.pos!), content: el, yAnchor: 1.25, zIndex: picked ? 9 : 6, clickable: true }))
    }
    // 지도 앱처럼 기사 실제 위치에 파란 점과 오차 범위 원을 그린다(묶음 안의 차량도). 이름표는 그 위에 떠 있다.
    for (const v of fleet) {
      if (!v.live || !v.pos) continue
      pins.current.push(new maps.Circle({ map: kmap.current, center: ll(v.pos), radius: Math.max(20, v.live.accuracy_m), strokeWeight: 1, strokeColor: '#2457E6', strokeOpacity: 0.5, fillColor: '#2457E6', fillOpacity: 0.12 }))
      const dot = document.createElement('div')
      dot.className = 'dm-live-dot'
      pins.current.push(new maps.CustomOverlay({ map: kmap.current, position: ll(v.pos), content: dot, zIndex: 5 }))
    }
    const a = selectedJob ? plan.find(x => x.job_id === selectedJob) : null
    const j = selectedJob ? snapshot.jobs.find(x => x.job_id === selectedJob) : null
    const from = j && pts.get(j.origin_id), to = j && pts.get(j.terminal_id)
    const road = j ? roadPath(j.origin_id, j.terminal_id) : null
    jobLine.current?.setPath(a && road ? road.map(ll) : a && from && to ? [ll(from), ll(to)] : [])
  }, [fleet, mapState.ok, selVehicle, selectedJob, plan, snapshot, pts, onSelectJob, viewTick, openCluster, showChanged, changedVehicles])

  // 지도 밖 표에서 차량을 고르면 지도도 그 차량을 고르고 그 자리로 옮긴다.
  useEffect(() => {
    if (pickedVehicleId === undefined || pickedVehicleId === pickedVehicle) return
    setPickedVehicleState(pickedVehicleId)
    const v = fleet.find(x => x.vehicleId === pickedVehicleId)
    const maps = window.kakao?.maps
    if (v?.pos && kmap.current && maps) kmap.current.panTo(new maps.LatLng(v.pos.lat, v.pos.lon))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedVehicleId])

  const sel = fleet.find(v => v.vehicleId === selVehicle) ?? null
  const selPlan =sel ? plan.filter(a => a.vehicle_id === sel.vehicleId).sort((x, y) => x.sequence - y.sequence) : []
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
          <p className="muted small"><b>{kstTime(new Date(now).toISOString())}</b> {ahead === 0 ? '현재' : '예상'}, {liveCount ? `기사 휴대폰 위치 ${liveCount}대, 나머지는 ${planLabel} 일정 기준` : `${planLabel} 일정 기준 위치`}{showChanged ? `, 원래 배차와 일정이 다른 차량 ${changedVehicles.size}대` : ''}</p>
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
          <div className="vm-play" role="group" aria-label="볼 시각">
            <button type="button" className="chip-toggle" aria-pressed={ahead === 0} onClick={() => setAhead(0)}>지금</button>
            <input className="vm-range" type="range" min={0} max={maxAhead} step={1} value={Math.min(ahead, maxAhead)} aria-label="볼 시각" onChange={(e) => { setAhead(Number(e.target.value)) }} />
            {cutAhead !== null && cutAhead <= maxAhead && (
              <button type="button" className="chip-toggle" aria-pressed={ahead === cutAhead} onClick={() => { setAhead(cutAhead) }}>반입 마감 {kstTime(new Date(cutoffAt).toISOString())}</button>
            )}
          </div>
          <LayerMenu sky={sky} onSky={setSky} traffic={traffic} onTraffic={setTraffic} disabled={!mapState.ok} />
        </div>
      </div>
      <div className="dm-body">
        <div className="vm-map-wrap">
          <div ref={box} className="dm-map" aria-label="차량 현황 지도" />
          {!mapState.ok && <p className="vm-map-msg muted small" role="status">{mapState.msg}</p>}
          {mapState.ok && (
            <div className="map-legend two-rows" aria-label="범례">
              <div className="lg-row">
                <span className="lg-group">트럭 색<small>반입 마감까지 남은 시간</small></span>
                <span><i className="lg ok-g" />넉넉함</span><span><i className="lg tight" />20분 미만</span><span><i className="lg late" />늦음</span><span><i className="lg idle" />작업 없음</span>{liveCount > 0 && <span><i className="lg live" />기사 휴대폰 위치</span>}{showChanged && <span><i className="lg chg" />일정 바뀐 차량</span>}
              </div>
              {traffic && (
                <div className="lg-row">
                  <span className="lg-group">도로 색<small>지금 막히는 정도</small></span>
                  <span><i className="lg-road ok" />원활</span><span><i className="lg-road slow" />서행</span><span><i className="lg-road jam" />정체</span>
                </div>
              )}
            </div>
          )}
          {mapState.ok && <p className="map-credit-line">{ROAD_ATTRIBUTION}</p>}
        </div>
        {!compact && <div className="dm-side">
        {sel ? (
          <div className="vm-info" aria-live="polite">
            <div className="vm-info-head"><b>{vehicleName(sel.vehicleId)}</b><span className={`dm-gate ${sel.gate ?? 'none'}`}>{PHASE_LABEL[sel.phase]}</span></div>
            {sel.jobId && <TripStepper phase={sel.phase} late={sel.gate === 'late'} />}
            <dl>
              {cur && curJob ? (
                <>
                  <div><dt>컨테이너</dt><dd>{jobName(cur.job_id)} ({curJob.equipment_type === 'DRY40' ? '40ft' : curJob.equipment_type === 'DRY20' ? '20ft' : curJob.equipment_type})</dd></div>
                  <div><dt>항차</dt><dd>{curJob.voyage_id}{curJob.cargo_owner ? `, ${curJob.cargo_owner}` : ''}{jobInfo(cur.job_id)?.booking ? `, 부킹 ${jobInfo(cur.job_id)!.booking}` : ''}</dd></div>
                  <div><dt>경로</dt><dd>{placeName(curJob.origin_id)} → {placeName(curJob.terminal_id)}</dd></div>
                  <div><dt>일정</dt><dd>상차지 출발 {kstTime(cur.pickup_departure_at)}, 게이트 도착 <b>{kstTime(cur.gate_arrival_at)}</b>, 복귀 {kstTime(cur.return_at)}</dd></div>
                  <div><dt>반입 마감</dt><dd>{kstTime(sel.cutoff)}{sel.marginMin !== null && (sel.gate === 'late' ? <b className="dm-late">, 마감 초과</b> : `, 여유 ${sel.marginMin}분`)}</dd></div>
                  <div><dt>다음 작업</dt><dd>{next ? `${jobName(next.job_id)}, ${kstTime(next.pickup_departure_at)} 출발` : '없음'}</dd></div>
                </>
              ) : <div><dt>작업</dt><dd>남은 작업 없음</dd></div>}
              <div><dt>위치</dt><dd className="muted">{sel.live ? `기사 휴대폰 위치, ${kstTime(sel.live.captured_at)} 측정(오차 약 ${Math.round(sel.live.accuracy_m)}m)${sel.live.offKm >= 2 ? `, 일정상 위치와 약 ${Math.round(sel.live.offKm)}km 떨어짐(기사에게 확인)` : ''}` : '배차 일정 기준 추정'}</dd></div>
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
                  {showChanged && changedVehicles.has(v.vehicleId) && <span className="st chg">일정 바뀜</span>}
                  {v.live && <span className="st live">기사 위치</span>}
                  {v.live && v.live.offKm >= 2 && <span className="st warn">일정상 위치와 약 {Math.round(v.live.offKm)}km 떨어짐</span>}
                  {v.gate && v.marginMin !== null && <span className={`st ${v.gate === 'late' ? 'bad' : v.gate === 'tight' ? 'warn' : 'ok'}`}>{v.gate === 'late' ? `${-v.marginMin}분 늦음` : `${v.marginMin}분 여유`}</span>}
                </span>
                {v.jobId && v.gateEta ? (
                  <span className="dmi-line"><BoxNo jobId={v.jobId} /> <span className="nowrap">게이트 <b>{kstTime(v.gateEta)}</b>, 마감 {kstTime(v.cutoff)}</span></span>
                ) : <span className="dmi-line">남은 작업 없음</span>}
              </button>
            </li>
          ))}
          {unassigned.length > 0 && <li className="dm-unassigned small">배정된 차량 없음: {unassigned.map(jobName).join(', ')}</li>}
        </ol>
        </div>}
      </div>
    </section>
  )
}
