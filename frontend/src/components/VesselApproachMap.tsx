// 배차 담당자용 입항 선박 지도: 대상 터미널(HJNC) 항차가 언제 들어오는지와, 그 항차의 반입 마감을 한 화면에서 본다.
// 모든 선박·항차·속력·마감은 모의다. 도착은 추정이며 반입 마감을 바꾸지 않는다.
import { useEffect, useMemo, useRef, useState } from 'react'
import { BUOYS, SOURCES, TERMINALS, VESSELS, fleetAt, formatDuration, routeLengthNm, type LatLon, type VesselView } from '../lib/vesselApproach'
import { MAP_TYPES, loadKakaoMaps, type MapType } from '../lib/kakaoMaps'
import type { Snapshot } from '../api/types'

export type ScenarioLink = { snapshot: Snapshot; reviewHref: string }
type Cutoff = { min: number | null; prevMin: number | null; linked: boolean; confirmed: boolean }

const MAX_MIN = 480
const STATUS_LABEL = { underway: '입항 중', anchored: '묘박 대기', berthed: '접안', stale: '위치 끊김' } as const

const kst = (d: Date) => d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Seoul' })
const at = (base: Date, min: number) => new Date(base.getTime() + min * 60000)

// 위에서 내려다본 컨테이너선(선수가 위). 진행 방향으로 회전한다.
function shipSvg(heading: number) {
  const rows = [10, 15, 20, 25].map(y => `<rect x="4" y="${y}" width="8" height="4" rx="0.6" class="box"/>`).join('')
  return `<svg class="hull" viewBox="0 0 16 42" width="16" height="42" style="transform:rotate(${heading}deg)" aria-hidden="true">`
    + `<path class="body" d="M8 0.8 C11.6 5 13.6 9 13.6 13 L13.6 37.5 Q13.6 41 10.6 41 L5.4 41 Q2.4 41 2.4 37.5 L2.4 13 C2.4 9 4.4 5 8 0.8 Z"/>`
    + rows + `<rect x="4.2" y="31" width="7.6" height="5" rx="1" class="bridge"/></svg>`
}

export function VesselApproachMap({ link = null }: { link?: ScenarioLink | null }) {
  // 화면을 연 시각이 모의 상황의 시작점이다. 기본은 실제 시간과 같은 속도로 흐른다(상황판).
  const base = useMemo(() => new Date(), [])
  const [t, setT] = useState(0)
  const [speed, setSpeed] = useState<1 | 10 | 60>(1)
  const [picked, setPicked] = useState<string>('SIM-01')
  const [mapType, setMapType] = useState<MapType>('HYBRID')
  const [mapState, setMapState] = useState<{ ok: boolean; msg: string }>({ ok: false, msg: '지도 불러오는 중…' })
  const fleet = useMemo(() => fleetAt(t), [t])
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
    const id = setInterval(() => setT(x => Math.min(MAX_MIN, x + speed / 60)), 1000)
    return () => clearInterval(id)
  }, [speed])

  // 지도와 고정 요소(항로·부표·터미널)는 한 번만 그린다.
  useEffect(() => {
    let alive = true
    loadKakaoMaps().then(maps => {
      if (!alive || !box.current) return
      const m = new maps.Map(box.current, { center: new maps.LatLng(34.99, 128.8), level: 9 })
      kmap.current = m
      // 넓게 볼 때는 대상 터미널·선택 선박 이름만 남겨 겹침을 줄인다.
      const zoomClass = () => box.current?.classList.toggle('vm-far', m.getLevel() >= 8)
      maps.event.addListener(m, 'zoom_changed', zoomClass)
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
      for (const b of BUOYS) {
        const el = document.createElement('div')
        el.className = `vm-buoy ${b.side}`
        el.title = `${b.name} (OSM 해상 표지)`
        new maps.CustomOverlay({ map: m, position: ll(b), content: el, zIndex: 1 })
      }
      for (const term of TERMINALS) {
        const el = document.createElement('div')
        el.className = `vm-term${term.target ? ' target' : ''}`
        el.textContent = term.target ? `${term.id} · 대상 터미널` : term.id
        el.title = `${term.name} (대표 좌표, 선석 위치 아님)`
        new maps.CustomOverlay({ map: m, position: ll(term), content: el, yAnchor: 1.2, zIndex: 2 })
      }
      paths.current = {
        passed: new maps.Polyline({ map: m, path: [], strokeWeight: 4, strokeColor: '#ff3c00', strokeOpacity: 0.9 }),
        ahead: new maps.Polyline({ map: m, path: [], strokeWeight: 4, strokeColor: '#ff3c00', strokeOpacity: 0.9, strokeStyle: 'dash' }),
      }
      for (const v of VESSELS) {
        const el = document.createElement('div')
        el.className = 'vm-ship'
        el.setAttribute('role', 'button')
        el.addEventListener('click', () => setPicked(v.id))
        const overlay = new maps.CustomOverlay({ map: m, position: ll(v.route[0]), content: el, zIndex: 5, clickable: true })
        marks.current.set(v.id, { overlay, el })
      }
      setMapState({ ok: true, msg: '' })
    }).catch((e: Error) => alive && setMapState({ ok: false, msg: `${e.message} 선박 목록과 남은 시간은 지도 없이 확인할 수 있습니다.` }))
    return () => { alive = false; marks.current.clear(); paths.current = null; kmap.current = null }
  }, [])

  useEffect(() => {
    if (mapState.ok) kmap.current?.setMapTypeId(window.kakao.maps.MapTypeId[mapType])
  }, [mapState.ok, mapType])

  // 시각이 바뀔 때마다 선박 위치·표시와 선택 선박의 경로만 갱신한다.
  useEffect(() => {
    const maps = window.kakao?.maps
    if (!mapState.ok || !maps) return
    const ll = (p: LatLon) => new maps.LatLng(p.lat, p.lon)
    const shown = new Set(fleet.map(v => v.vessel.id))
    for (const [id, mk] of marks.current) mk.overlay.setMap(shown.has(id) ? kmap.current : null)
    for (const v of fleet) {
      const mk = marks.current.get(v.vessel.id)
      if (!mk) continue
      mk.overlay.setPosition(ll(v.pos))
      mk.overlay.setZIndex(v.vessel.id === sel.vessel.id ? 9 : v.vessel.terminal === 'HJNC' ? 6 : 5)
      mk.el.className = `vm-ship ${v.status}${v.vessel.terminal === 'HJNC' ? ' target' : ''}${v.vessel.id === sel.vessel.id ? ' picked' : ''}`
      const name = v.vessel.name ?? '이름 미수신'
      const tail = v.vessel.outbound ? `출항 · ${v.vessel.port}행` : v.etaMin !== null ? `${formatDuration(v.etaMin - t)} 후 도착` : STATUS_LABEL[v.status]
      mk.el.innerHTML = `${shipSvg(v.status === 'anchored' ? 20 : v.heading)}<span>${name} · ${tail}</span>`
    }
    if (paths.current) {
      paths.current.passed.setPath(sel.passed.length > 1 ? sel.passed.map(ll) : [])
      paths.current.ahead.setPath(sel.status === 'underway' && sel.ahead.length > 1 ? sel.ahead.map(ll) : [])
    }
  }, [fleet, sel, mapState.ok, t])

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
            <span className="muted">{v.vessel.voyage} · {v.vessel.terminal}</span>
            <span className={`vm-chip ${v.vessel.outbound ? 'out' : v.status}`}>{label}</span>
          </span>
          <span className="vm-eta">
            {v.vessel.outbound ? <span className="muted">{v.vessel.port} 향발{v.etaMin !== null ? ` · 외해까지 ${formatDuration(v.etaMin - t)}` : ''}</span>
              : v.etaMin !== null ? <><b>{formatDuration(v.etaMin - t)}</b> 후 도착 추정 <span className="muted">· {kst(at(base, v.etaMin))}</span></>
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
            <h2>입항 선박 · 반입 마감</h2>
            <p className="muted small">대상 터미널 HJNC 항차가 언제 도착할지(추정)와 그 항차의 반입 마감을 함께 봅니다.</p>
          </div>
        </div>
        {link ? (
          <p className="vm-linked small">지금 점검 중인 배차의 항차별 반입 마감을 함께 표시합니다. <a href={link.reviewHref}>배차 점검으로 돌아가기</a></p>
        ) : (
          <p className="vm-linked small muted">배차 점검을 시작하면 같은 항차의 반입 마감이 이 지도에 연결됩니다. <a href="?">새 점검</a></p>
        )}

        <div className="vm-toolbar">
          <div className="vm-seg" role="radiogroup" aria-label="지도 종류">
            {MAP_TYPES.map(([id, label]) => (
              <button key={id} type="button" role="radio" aria-checked={mapType === id} disabled={!mapState.ok} onClick={() => setMapType(id)}>{label}</button>
            ))}
          </div>
          <div className="vm-play">
            <span className="vm-clock"><span className="vm-live" aria-hidden="true" /><b>{kst(at(base, t))}</b> <span className="muted">{speed === 1 ? '현재 시각' : `시연 ${speed}배속`}</span></span>
            <label className="vm-speed small">시연 속도
              <select value={speed} onChange={e => setSpeed(Number(e.target.value) as 1 | 10 | 60)}>
                <option value={1}>실시간</option>
                <option value={10}>10배</option>
                <option value={60}>60배</option>
              </select>
            </label>
            {t >= MAX_MIN && <button type="button" className="secondary" onClick={() => setT(0)}>모의 상황 다시 시작</button>}
          </div>
        </div>

        <div className="vm-body">
          <div className="vm-map-wrap">
            <div ref={box} className="vm-map" aria-label="부산신항 입항 선박 지도" />
            {!mapState.ok && <p className="vm-map-msg muted small" role="status">{mapState.msg}</p>}
            {mapState.ok && (
              <div className="map-legend" aria-label="범례">
                <span><i className="lg hjnc" />HJNC 입항</span><span><i className="lg other" />다른 터미널</span><span><i className="lg berth" />접안 중</span><span><i className="lg route" />선택 선박 남은 항로</span>
              </div>
            )}
          </div>

          <div className="vm-side">
            <InfoCard v={sel} t={t} base={base} cut={cutoffOf(sel.vessel.voyage, sel.vessel.terminal, sel.vessel.cutoffMin)} link={link} />
            <h3 className="vm-group">HJNC(대상 터미널) 선박 {fleet.filter(v => v.vessel.terminal === 'HJNC').length}척</h3>
            <ol className="vm-list" aria-label="HJNC 선박 도착 추정 순">
              {fleet.filter(v => v.vessel.terminal === 'HJNC').map(v => row(v))}
            </ol>
            <details className="vm-others">
              <summary>다른 신항 터미널 선박 {fleet.filter(v => v.vessel.terminal !== 'HJNC').length}척</summary>
              <ol className="vm-list">{fleet.filter(v => v.vessel.terminal !== 'HJNC').map(v => row(v))}</ol>
            </details>
          </div>
        </div>

        <details className="vm-notes small">
          <summary>자료 설명</summary>
          <ul>
            <li>선박·항차·속력·반입 마감은 시연용 모의 자료입니다. 실제 AIS가 연결되면 같은 형식으로 대체됩니다.</li>
            <li>도착 추정 = 남은 항로 길이 ÷ 현재 속력. 조류·감속·도선·선석 대기는 반영하지 않습니다.</li>
            <li>속력이 0인 묘박 선박과 위치가 끊긴 선박은 도착 시각을 만들지 않습니다(마지막 위치에서 멈춤).</li>
            <li>반입 마감은 터미널이 정하는 항차별 시간입니다. 선박 도착 추정이 바뀌어도 자동으로 바뀌지 않습니다.</li>
            <li>항로선은 부표 위치를 참고해 그린 설명용 선이며 공식 항로·도선 경로가 아닙니다. 부표: {SOURCES.seamark}</li>
            <li>터미널 표시는 대표 좌표이며 선석 위치가 아닙니다: {SOURCES.places}</li>
            <li>위성 사진은 촬영 시점의 배경이며 실시간 영상이 아닙니다.</li>
          </ul>
          <p className="vm-legend"><span className="vm-buoy port" /> 좌현 표지 <span className="vm-buoy starboard" /> 우현 표지 <span className="vm-buoy safe" /> 안전수역 표지</p>
        </details>
      </section>
    </main>
  )
}

function InfoCard({ v, t, base, cut, link }: { v: VesselView; t: number; base: Date; cut: Cutoff; link: ScenarioLink | null }) {
  const name = v.vessel.name ?? '이름 미수신 선박'
  const cutLeft = cut.min === null ? null : cut.min - t
  const rows: [string, React.ReactNode][] = [
    ['선박', `컨테이너선 · ${v.vessel.teu.toLocaleString()}TEU`],
    [v.vessel.outbound ? '다음 기항' : '출발항', v.vessel.port],
    ['터미널 · 항차', `${v.vessel.terminal} · ${v.vessel.voyage}`],
  ]
  if (v.status === 'underway' && !v.vessel.outbound && v.etaMin !== null) {
    rows.push(['도착 추정', <><b>{kst(at(base, v.etaMin))}</b> ({formatDuration(v.etaMin - t)} 후)</>])
    rows.push(['남은 항로', `${v.remainingNm!.toFixed(1)}해리 · ${v.vessel.speedKn}노트`])
  } else if (v.vessel.outbound) rows.push(['상태', `출항 중 · ${v.vessel.speedKn}노트`])
  else rows.push(['상태', v.etaNote])
  if (v.vessel.terminal === 'HJNC' && !v.vessel.outbound && cut.min !== null && cutLeft !== null)
    rows.push(['반입 마감', <>{kst(at(base, cut.min))} · {cutLeft < 0 ? `${formatDuration(-cutLeft)} 지남` : `${formatDuration(cutLeft)} 남음`}{cut.prevMin !== null && <span className="vm-changed"> (변경 전 {kst(at(base, cut.prevMin))})</span>}</>])
  return (
    <div className="vm-info" aria-live="polite">
      <div className="vm-info-head"><b>{name}</b>{v.vessel.terminal === 'HJNC' && <span className="vm-chip underway">대상 터미널</span>}</div>
      <dl>{rows.map(([k, val]) => <div key={k}><dt>{k}</dt><dd>{val}</dd></div>)}</dl>
      {cut.linked && link && v.vessel.terminal === 'HJNC' && !v.vessel.outbound && <a className="vm-go" href={link.reviewHref}>{v.vessel.voyage} 항차 배차 점검 →</a>}
    </div>
  )
}
