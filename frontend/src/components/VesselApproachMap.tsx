// 배차 담당자용 입항 선박 지도: 대상 터미널(HJNC) 항차가 언제 들어오는지와, 그 항차의 반입 마감을 한 화면에서 본다.
// 모든 선박·항차·속력·마감은 모의다. 도착은 추정이며 반입 마감을 바꾸지 않는다.
import { useEffect, useMemo, useRef, useState } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Ship } from 'lucide-react'
import { BUOYS, TERMINALS, VESSELS, fleetAt, formatDuration, routeLengthNm, type LatLon, type VesselView } from '../lib/vesselApproach'
import { keepLaidOut, loadKakaoMaps, type MapType } from '../lib/kakaoMaps'
import { Icon } from './Icon'
import { LayerMenu } from './LayerMenu'
import { demoAnchor } from '../lib/shift'
import { useMapStyle } from '../lib/mapStyle'
import { SeaWeatherLine } from './LiveReference'
import type { Snapshot } from '../api/types'

export type ScenarioLink = { snapshot: Snapshot; reviewHref: string }
type Cutoff = { min: number | null; prevMin: number | null; linked: boolean; confirmed: boolean }

const SHOW_BUOYS = false
const MAX_MIN = 480
const STATUS_LABEL = { underway: '입항 중', anchored: '묘박 대기', berthed: '접안', stale: '위치 끊김', offshore: '외해 항해' } as const

const kst = (d: Date) => d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Seoul' })
const at = (base: Date, min: number) => new Date(base.getTime() + min * 60000)

// 위에서 내려다본 컨테이너선(선수가 위). 진행 방향으로 회전한다.
// 지도 위 선박 표식: 동그란 표식 안에 배 아이콘, 바깥 화살촉으로 진행 방향을 보인다(선박 관제 화면의 표식 방식).
const SHIP_ICON = renderToStaticMarkup(<Ship size={15} strokeWidth={2.2} aria-hidden="true" />)
function shipMark(heading: number | null) {
  return `<div class="vm-mark">${heading === null ? '' : `<i class="vm-dir" style="transform:rotate(${heading}deg)"></i>`}<b>${SHIP_ICON}</b></div>`
}

export function VesselApproachMap({ link = null }: { link?: ScenarioLink | null }) {
  // 화면을 연 시각이 모의 상황의 시작점이다. 기본은 실제 시간과 같은 속도로 흐른다(상황판).
  const base = useMemo(() => demoAnchor(), [])
  // 실제 흐르는 시각(분) + 담당자가 고른 미리보기 간격. '3시간 뒤'를 누르면 그때 모선 위치를 본다.
  const [rt, setRt] = useState(() => Math.min(MAX_MIN, (Date.now() - base.getTime()) / 60000))
  // 지금부터 몇 분 뒤의 위치를 볼지(시간 막대). 0이면 실시간.
  const [ahead, setAhead] = useState(0)
  const t = Math.min(MAX_MIN, rt + ahead)
  const [picked, setPicked] = useState<string>('BM-01')
  const [scope, setScope] = useState<'HJNC' | 'all'>('HJNC')
  const [vq, setVq] = useState('')
  const [style, setStyle] = useMapStyle('vessel', 'sky')
  const mapType: MapType = style === 'sky' ? 'HYBRID' : 'ROADMAP'
  const [zoomTick, setZoomTick] = useState(0)
  const [mapState, setMapState] = useState<{ ok: boolean; msg: string }>({ ok: false, msg: '지도 불러오는 중…' })
  const fleet = useMemo(() => fleetAt(t), [t])
  const inboundHjnc = fleet.filter(v => v.vessel.terminal === 'HJNC' && !v.vessel.outbound && v.status !== 'berthed').length
  // 시간 막대의 '다음 반입 마감' 버튼은 지금 기준으로 고정한다(막대를 움직여도 같은 항차).
  const cutFromNow = VESSELS.filter(v => v.terminal === 'HJNC' && v.cutoffMin !== null && v.cutoffMin > rt).sort((a, b) => a.cutoffMin! - b.cutoffMin!)[0]
  const nextCut = fleet.filter(v => v.vessel.terminal === 'HJNC' && v.vessel.cutoffMin !== null && v.vessel.cutoffMin > t).sort((a, b) => a.vessel.cutoffMin! - b.vessel.cutoffMin!)[0]
  const sel = fleet.find(v => v.vessel.id === picked) ?? fleet[0]
  // 계산한 시나리오에 같은 항차·터미널 반입 시간창이 있으면 그 값을 쓴다(지도 전용 모의 값보다 우선).
  const cutoffOf = (voyage: string, terminal: string, fallback: number | null): Cutoff => {
    const toMin = (iso: string | null) => (iso ? (Date.parse(iso) - base.getTime()) / 60000 : null)
    const w = link?.snapshot.windows.find(x => x.voyage_id === voyage && x.terminal_id === terminal)
    if (!w) return { min: fallback, prevMin: null, linked: false, confirmed: false }
    const ch = link!.snapshot.change
    const changed = ch && ch.voyage_id === voyage && ch.terminal_id === terminal
    return { min: toMin(w.closes_at), prevMin: changed ? toMin(ch.previous_closes_at) : null, linked: true, confirmed: w.verification === 'confirmed' }
  }

  const box = useRef<HTMLDivElement>(null)
  const kmap = useRef<any>(null)
  const marks = useRef(new Map<string, { overlay: any; el: HTMLDivElement }>())
  const paths = useRef<{ passed: any; ahead: any } | null>(null)

  useEffect(() => {
    const id = setInterval(() => setRt(x => Math.min(MAX_MIN, x + 1 / 60)), 1000)
    return () => clearInterval(id)
  }, [])

  // 지도와 고정 요소(항로·부표·터미널)는 한 번만 그린다.
  useEffect(() => {
    let alive = true
    let unobserve = () => {}
    loadKakaoMaps().then(maps => {
      if (!alive || !box.current) return
      const m = new maps.Map(box.current, { center: new maps.LatLng(34.99, 128.8), level: 9 })
      kmap.current = m
      unobserve = keepLaidOut(m, box.current)
      // 넓게 볼 때는 대상 터미널·선택 선박 이름만 남겨 겹침을 줄인다.
      const zoomClass = () => box.current?.classList.toggle('vm-far', m.getLevel() >= 8)
      maps.event.addListener(m, 'zoom_changed', zoomClass)
      maps.event.addListener(m, 'idle', () => setZoomTick(x => x + 1))
      zoomClass()
      const ll = (p: LatLon) => new maps.LatLng(p.lat, p.lon)
      const seen = new Set<string>()
      for (const v of VESSELS) {
        if (v.route.length < 2) continue
        const key = v.route.map(p => `${p.lat},${p.lon}`).join('|')
        if (seen.has(key)) continue
        seen.add(key)
        new maps.Polyline({ map: m, path: v.route.map(ll), strokeWeight: 2, strokeColor: '#9aa6ad', strokeOpacity: 0.8, strokeStyle: 'shortdash' })
      }
      // 항로 부표는 그리지 않는다(담당자에게 데이터 점처럼 보여 헷갈린다). 항로선만 남긴다.
      for (const b of SHOW_BUOYS ? BUOYS : []) {
        const el = document.createElement('div')
        el.className = `vm-buoy ${b.side}`
        el.title = `${b.name} (OSM 해상 표지)`
        new maps.CustomOverlay({ map: m, position: ll(b), content: el, zIndex: 1 })
      }
      for (const term of TERMINALS) {
        const el = document.createElement('div')
        el.className = `vm-term${term.target ? ' target' : ''}`
        el.textContent = term.id
        new maps.CustomOverlay({ map: m, position: ll(term), content: el, yAnchor: 1.2, zIndex: 2 })
      }
      paths.current = {
        passed: new maps.Polyline({ map: m, path: [], strokeWeight: 4, strokeColor: '#2457E6', strokeOpacity: 0.9 }),
        ahead: new maps.Polyline({ map: m, path: [], strokeWeight: 4, strokeColor: '#2457E6', strokeOpacity: 0.9, strokeStyle: 'dash' }),
      }
      for (const v of VESSELS) {
        const el = document.createElement('div')
        el.className = 'vm-ship'
        el.setAttribute('role', 'button')
        // 다른 터미널 배를 누르면 목록에도 보이도록 '신항 전체'로 넓힌다.
        el.addEventListener('click', () => { setPicked(v.id); if (v.terminal !== 'HJNC') setScope('all') })
        const overlay = new maps.CustomOverlay({ map: m, position: ll(v.route[0]), content: el, zIndex: 5, clickable: true })
        marks.current.set(v.id, { overlay, el })
      }
      setMapState({ ok: true, msg: '' })
    }).catch((e: Error) => alive && setMapState({ ok: false, msg: `${e.message} 선박 목록과 남은 시간은 지도 없이 확인할 수 있습니다.` }))
    return () => { alive = false; unobserve(); marks.current.clear(); paths.current = null; kmap.current = null }
  }, [])

  useEffect(() => {
    if (mapState.ok) kmap.current?.setMapTypeId(window.kakao.maps.MapTypeId[mapType])
  }, [mapState.ok, mapType])

  // 시각이 바뀔 때마다 선박 위치·표시와 선택 선박의 경로만 갱신한다.
  useEffect(() => {
    const maps = window.kakao?.maps
    if (!mapState.ok || !maps) return
    const ll = (p: LatLon) => new maps.LatLng(p.lat, p.lon)
    const shown = new Set(fleet.filter(v => v.status !== 'offshore').map(v => v.vessel.id))
    const level = kmap.current?.getLevel() ?? 8
    const proj = kmap.current?.getProjection()
    // 이름표는 고른 배 → HJNC로 들어오는 배 → 나머지 순으로, 이미 붙은 이름표와 겹치면 숨긴다.
    const placed: { x: number; y: number; w: number }[] = []
    const priority = (v: VesselView) => (v.vessel.id === sel.vessel.id ? 0 : v.vessel.terminal === 'HJNC' && !v.vessel.outbound && v.status === 'underway' ? 1 : 2)
    const labelOn = new Set<string>()
    for (const v of [...fleet].filter(x => shown.has(x.vessel.id)).sort((a, b) => priority(a) - priority(b))) {
      if (priority(v) === 2 && level >= 7) continue
      if (!proj) { labelOn.add(v.vessel.id); continue }
      const pt = proj.containerPointFromCoords(ll(v.pos))
      const w = 14 + (v.vessel.name?.length ?? 6) * 12
      const hit = placed.some(b => Math.abs(b.y - pt.y) < 22 && pt.x < b.x + b.w && pt.x + w > b.x)
      if (hit && priority(v) !== 0) continue
      placed.push({ x: pt.x, y: pt.y, w })
      labelOn.add(v.vessel.id)
    }
    // 화면에서 26px 안에 겹치는 배(부두에 나란히 댄 배 등)는 하나만 그리고 척수를 붙인다. 고른 배는 항상 보인다.
    const hidden = new Set<string>()
    const extra = new Map<string, number>()
    if (proj) {
      const drawn: { id: string; x: number; y: number }[] = []
      for (const v of [...fleet].filter(x => shown.has(x.vessel.id)).sort((a, b) => priority(a) - priority(b))) {
        const pt = proj.containerPointFromCoords(ll(v.pos))
        const near = drawn.find(d => Math.hypot(d.x - pt.x, d.y - pt.y) < 26)
        if (near && v.vessel.id !== sel.vessel.id) { hidden.add(v.vessel.id); extra.set(near.id, (extra.get(near.id) ?? 1) + 1); labelOn.delete(v.vessel.id); continue }
        drawn.push({ id: v.vessel.id, x: pt.x, y: pt.y })
      }
    }
    for (const [id, mk] of marks.current) mk.overlay.setMap(shown.has(id) && !hidden.has(id) ? kmap.current : null)
    for (const v of fleet) {
      const mk = marks.current.get(v.vessel.id)
      if (!mk) continue
      mk.overlay.setPosition(ll(v.pos))
      mk.overlay.setZIndex(v.vessel.id === sel.vessel.id ? 9 : v.vessel.terminal === 'HJNC' ? 6 : 5)
      mk.el.className = `vm-ship ${v.status}${v.vessel.terminal === 'HJNC' ? ' target' : ''}${v.vessel.id === sel.vessel.id ? ' picked' : ''}${scope === 'HJNC' && v.vessel.terminal !== 'HJNC' && v.vessel.id !== sel.vessel.id ? ' dim' : ''}`
      const name = v.vessel.name ?? '이름 미수신'
      const tail = v.vessel.outbound ? `${v.vessel.port}행 출항` : v.etaMin !== null ? `${formatDuration(v.etaMin - t)} 후 도착` : STATUS_LABEL[v.status]
      const label = v.vessel.id === sel.vessel.id ? `${name} <small>${tail}</small>` : name
      const count = extra.get(v.vessel.id)
      mk.el.innerHTML = `${shipMark(v.status === 'underway' ? v.heading : null)}${count ? `<em class="vm-count">${count}척</em>` : ''}${labelOn.has(v.vessel.id) ? `<span>${label}</span>` : ''}`
    }
    if (paths.current) {
      paths.current.passed.setPath(sel.passed.length > 1 ? sel.passed.map(ll) : [])
      paths.current.ahead.setPath(sel.status === 'underway' && sel.ahead.length > 1 ? sel.ahead.map(ll) : [])
    }
  }, [fleet, sel, mapState.ok, t, zoomTick, scope])

  // 지도에서 배를 누르면 목록의 같은 배를 강조하고, 화면 밖이면 보이는 곳까지만 굴린다(처음 열 때는 굴리지 않는다).
  const firstPick = useRef(true)
  useEffect(() => {
    if (firstPick.current) { firstPick.current = false; return }
    // 범위가 '신항 전체'로 바뀌어 목록이 다시 그려진 뒤에 굴린다.
    const id = requestAnimationFrame(() => document.querySelector<HTMLElement>('.vm-item.picked')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }))
    return () => cancelAnimationFrame(id)
  }, [picked])

  const focus = (v: VesselView) => {
    setPicked(v.vessel.id)
    const maps = window.kakao?.maps
    if (kmap.current && maps) kmap.current.panTo(new maps.LatLng(v.pos.lat, v.pos.lon))
  }

  const row = (v: VesselView) => {
    const total = routeLengthNm(v.vessel.route)
    const progress = total > 0 && v.remainingNm !== null ? 1 - v.remainingNm / total : v.status === 'berthed' ? 1 : 0
    const label = v.vessel.outbound ? '출항 중' : STATUS_LABEL[v.status]
    return (
      <li key={v.vessel.id}>
        <button type="button" className={`vm-item${v.vessel.id === sel.vessel.id ? ' picked' : ''}`} aria-pressed={v.vessel.id === sel.vessel.id} onClick={() => focus(v)}>
          <span className="vm-item-top">
            <b>{v.vessel.name ?? '이름 미수신'}</b>
            <span className="muted">{v.vessel.voyage}, {v.vessel.terminal}</span>
            <span className={`vm-chip ${v.vessel.outbound ? 'out' : v.status}`}>{label}</span>
          </span>
          <span className="vm-eta">
            {v.vessel.outbound ? <span className="muted">{v.vessel.port} 향발{v.etaMin !== null ? `, 외해까지 ${formatDuration(v.etaMin - t)}` : ''}</span>
              : v.etaMin !== null ? <><b>{formatDuration(v.etaMin - t)}</b> 후 도착 추정 <span className="muted">({kst(at(base, v.etaMin))})</span></>
              : <span className="muted">{v.etaNote}</span>}
          </span>
          {!v.vessel.outbound && <span className="vm-bar" aria-hidden="true"><span style={{ width: `${Math.round(progress * 100)}%` }} /></span>}
        </button>
      </li>
    )
  }

  return (
    <main className="vessel-view">
      <section className="card">
        <div className="vm-head">
          <div>
            <h2>입항 모선</h2>
          </div>
        </div>
        {nextCut && (
          <div className="vm-brief">
            <span><b>HJNC로 오는 모선 {inboundHjnc}척</b></span>
            <span>다음 반입 마감 <b>{nextCut.vessel.voyage}</b> {kst(at(base, nextCut.vessel.cutoffMin!))}, <b className="vm-left">{formatDuration(nextCut.vessel.cutoffMin! - t)} 남음</b></span>
            <SeaWeatherLine />
          </div>
        )}
        {link ? (
          <p className="vm-linked small"><a href={link.reviewHref}>점검 결과로 돌아가기</a></p>
        ) : (
          <p className="vm-linked small muted">받은 변경을 점검하면 같은 항차의 반입 마감이 이 지도에 함께 표시됩니다. <a href="?">받은 변경 보기</a></p>
        )}

        <div className="vm-toolbar">
          <div className="vm-play">
            <span className="vm-clock"><span className="vm-live" aria-hidden="true" /><b>{kst(at(base, t))}</b> <span className="muted">{ahead === 0 ? '현재' : '예상'}</span></span>
            <button type="button" className="chip-toggle" aria-pressed={ahead === 0} onClick={() => setAhead(0)}>지금</button>
            <input className="vm-range" type="range" min={0} max={Math.max(0, Math.floor(MAX_MIN - rt))} step={10} value={ahead} aria-label="볼 시각" onChange={(e) => setAhead(Number(e.target.value))} />
            {cutFromNow && (
              <button type="button" className="chip-toggle" aria-pressed={ahead > 0 && Math.abs(rt + ahead - cutFromNow.cutoffMin!) < 1}
                onClick={() => setAhead(Math.max(0, Math.round(cutFromNow.cutoffMin! - rt)))}>
                다음 반입 마감 {kst(at(base, cutFromNow.cutoffMin!))}
              </button>
            )}
          </div>
          <LayerMenu sky={style === 'sky'} onSky={(on) => setStyle(on ? 'sky' : 'map')} disabled={!mapState.ok} />
        </div>

        <div className="vm-body">
          <div className="vm-map-wrap">
            <div ref={box} className="vm-map" aria-label="부산신항 입항 선박 지도" />
            {!mapState.ok && <p className="vm-map-msg muted small" role="status">{mapState.msg}</p>}
            {mapState.ok && (
              <div className="map-legend" aria-label="범례">
                <span><i className="lg hjnc" />HJNC로 오는 배</span><span><i className="lg other" />다른 터미널로 가는 배</span><span><i className="lg berth" />부두에 댄 배</span><span><i className="lg route" />고른 배의 남은 뱃길</span>
              </div>
            )}
          </div>

          <div className="vm-side">
            <InfoCard v={sel} t={t} base={base} cut={cutoffOf(sel.vessel.voyage, sel.vessel.terminal, sel.vessel.cutoffMin)} link={link} />
            <div className="toolbar vm-tools">
              <div className="seg" role="group" aria-label="터미널 범위">
                <button type="button" aria-pressed={scope === 'HJNC'} onClick={() => setScope('HJNC')}>HJNC<span className="n">{fleet.filter(v => v.vessel.terminal === 'HJNC').length}척</span></button>
                <button type="button" aria-pressed={scope === 'all'} onClick={() => setScope('all')}>신항 전체<span className="n">{fleet.length}척</span></button>
              </div>
              <label className="search">
                <Icon name="search" size={15} />
                <input type="search" value={vq} onChange={(e) => setVq(e.target.value)} placeholder="선박명·항차 검색" aria-label="선박 검색" />
              </label>
            </div>
            {(() => {
              const q = vq.trim().toLowerCase().replace(/\s/g, '')
              const list = fleet.filter(v => (scope === 'all' || v.vessel.terminal === 'HJNC') && (!q || `${v.vessel.name ?? ''}${v.vessel.voyage}${v.vessel.terminal}`.toLowerCase().replace(/\s/g, '').includes(q)))
              return list.length ? <ol className="vm-list" aria-label="선박 도착 추정 순">{list.map(v => row(v))}</ol> : <p className="ib-empty">조건에 맞는 선박이 없습니다.</p>
            })()}
          </div>
        </div>

      </section>
    </main>
  )
}

function InfoCard({ v, t, base, cut, link }: { v: VesselView; t: number; base: Date; cut: Cutoff; link: ScenarioLink | null }) {
  const name = v.vessel.name ?? '이름 미수신 선박'
  const cutLeft = cut.min === null ? null : cut.min - t
  const rows: [string, React.ReactNode][] = [
    ['선박', `컨테이너선, ${v.vessel.teu.toLocaleString()}TEU`],
    [v.vessel.outbound ? '다음 기항' : '출발항', v.vessel.port],
    ['터미널', v.vessel.terminal], ['항차', v.vessel.voyage],
  ]
  if (v.status === 'underway' && !v.vessel.outbound && v.etaMin !== null) {
    rows.push(['도착 추정', <><b>{kst(at(base, v.etaMin))}</b> ({formatDuration(v.etaMin - t)} 후)</>])
    rows.push(['남은 항로', `${v.remainingNm!.toFixed(1)}해리, ${v.vessel.speedKn}노트`])
  } else if (v.status === 'offshore' && v.etaMin !== null) rows.push(['접안 예정', <><b>{kst(at(base, v.etaMin))}</b> ({formatDuration(v.etaMin - t)} 후, 외해 항해 중, 지도 범위 밖)</>])
  else if (v.vessel.outbound) rows.push(['상태', `출항 중, ${v.vessel.speedKn}노트`])
  else rows.push(['상태', v.etaNote])
  if (v.vessel.terminal === 'HJNC' && !v.vessel.outbound && cut.min !== null && cutLeft !== null)
    rows.push(['반입 마감', <>{kst(at(base, cut.min))}, {cutLeft < 0 ? `${formatDuration(-cutLeft)} 지남` : `${formatDuration(cutLeft)} 남음`}{cut.prevMin !== null && <span className="vm-changed"> (변경 전 {kst(at(base, cut.prevMin))})</span>}</>])
  return (
    <div className="vm-info" aria-live="polite">
      <div className="vm-info-head"><b>{name}</b>{v.vessel.terminal === 'HJNC' && <span className="vm-chip underway">대상 터미널</span>}</div>
      <dl>{rows.map(([k, val]) => <div key={k}><dt>{k}</dt><dd>{val}</dd></div>)}</dl>
      {cut.linked && link && v.vessel.terminal === 'HJNC' && !v.vessel.outbound && <a className="vm-go" href={link.reviewHref}>{v.vessel.voyage} 항차 배차 점검 →</a>}
    </div>
  )
}
