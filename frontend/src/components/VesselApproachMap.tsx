// 배차 담당자용 입항 선박 지도: 대상 터미널(HJNC) 항차가 언제 들어오는지와, 그 항차의 반입 마감을 한 화면에서 본다.
// 모든 선박·항차·속력·마감은 모의다. 도착은 추정이며 반입 마감을 바꾸지 않는다.
import { useEffect, useMemo, useRef, useState } from 'react'
import { BUOYS, SOURCES, TERMINALS, VESSELS, fleetAt, formatDuration, routeLengthNm, type LatLon, type VesselView } from '../lib/vesselApproach'
import { MAP_TYPES, loadKakaoMaps, type MapType } from '../lib/kakaoMaps'

const MAX_MIN = 240
const STATUS_LABEL = { underway: '입항 중', anchored: '묘박 대기', berthed: '접안', stale: '위치 끊김' } as const

const kst = (d: Date) => d.toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Seoul' })
const at = (base: Date, min: number) => new Date(base.getTime() + min * 60000)

function arrowSvg(heading: number) {
  return `<svg viewBox="0 0 24 24" width="22" height="22" style="transform:rotate(${heading}deg)" aria-hidden="true"><path d="M12 2 L19 21 L12 17 L5 21 Z"/></svg>`
}

export function VesselApproachMap() {
  const base = useMemo(() => { const d = new Date(); d.setSeconds(0, 0); d.setMinutes(d.getMinutes() - (d.getMinutes() % 5)); return d }, [])
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [picked, setPicked] = useState<string>('SIM-01')
  const [mapType, setMapType] = useState<MapType>('HYBRID')
  const [mapState, setMapState] = useState<{ ok: boolean; msg: string }>({ ok: false, msg: '지도 불러오는 중…' })
  const fleet = useMemo(() => fleetAt(t), [t])
  const sel = fleet.find(v => v.vessel.id === picked) ?? fleet[0]

  const box = useRef<HTMLDivElement>(null)
  const kmap = useRef<any>(null)
  const marks = useRef(new Map<string, { overlay: any; el: HTMLDivElement }>())
  const paths = useRef<{ passed: any; ahead: any } | null>(null)

  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => setT(x => (x >= MAX_MIN ? x : x + 1)), 100)
    return () => clearInterval(id)
  }, [playing])
  useEffect(() => { if (t >= MAX_MIN) setPlaying(false) }, [t])

  // 지도와 고정 요소(항로·부표·터미널)는 한 번만 그린다.
  useEffect(() => {
    let alive = true
    loadKakaoMaps().then(maps => {
      if (!alive || !box.current) return
      const m = new maps.Map(box.current, { center: new maps.LatLng(34.99, 128.8), level: 9 })
      kmap.current = m
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
    for (const v of fleet) {
      const mk = marks.current.get(v.vessel.id)
      if (!mk) continue
      mk.overlay.setPosition(ll(v.pos))
      mk.overlay.setZIndex(v.vessel.id === sel.vessel.id ? 9 : v.vessel.terminal === 'HJNC' ? 6 : 5)
      mk.el.className = `vm-ship ${v.status}${v.vessel.terminal === 'HJNC' ? ' target' : ''}${v.vessel.id === sel.vessel.id ? ' picked' : ''}`
      const name = v.vessel.name ?? '이름 미수신'
      const tail = v.etaMin !== null ? formatDuration(v.etaMin - t) : STATUS_LABEL[v.status]
      mk.el.innerHTML = `${arrowSvg(v.status === 'anchored' || v.status === 'berthed' ? 0 : v.heading)}<span>${name} · ${tail}</span>`
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

  return (
    <main className="vessel-view">
      <section className="card">
        <div className="vm-head">
          <div>
            <h2>입항 선박 · 반입 마감</h2>
            <p className="muted small">대상 터미널 HJNC 항차가 언제 도착할지(추정)와 그 항차의 반입 마감을 함께 봅니다.</p>
          </div>
          <span className="badge fixture">모의 자료</span>
        </div>
        <div className="banner fixture">선박·항차·속력·반입 마감은 모두 모의입니다. 도착 시각은 추정이며 반입 마감을 바꾸지 않습니다.</div>

        <div className="vm-toolbar">
          <div className="vm-seg" role="radiogroup" aria-label="지도 종류">
            {MAP_TYPES.map(([id, label]) => (
              <button key={id} type="button" role="radio" aria-checked={mapType === id} disabled={!mapState.ok} onClick={() => setMapType(id)}>{label}</button>
            ))}
          </div>
          <div className="vm-play">
            <button type="button" className="vm-play-btn" onClick={() => setPlaying(!playing)} disabled={t >= MAX_MIN}>{playing ? '일시 정지' : '재생'}</button>
            <button type="button" className="secondary" onClick={() => { setPlaying(false); setT(0) }}>처음</button>
            <span className="vm-clock"><b>{kst(at(base, t))}</b> <span className="muted">모의 시각 · +{formatDuration(t)}</span></span>
          </div>
          <input className="vm-range" aria-label="모의 시각" type="range" min={0} max={MAX_MIN} value={t} onChange={e => { setPlaying(false); setT(Number(e.target.value)) }} />
        </div>

        <div className="vm-body">
          <div className="vm-map-wrap">
            <div ref={box} className="vm-map" aria-label="부산신항 입항 선박 지도" />
            {!mapState.ok && <p className="vm-map-msg muted small" role="status">{mapState.msg}</p>}
            {mapType !== 'ROADMAP' && mapState.ok && <p className="vm-map-note">위성 사진은 촬영 시점 배경입니다(실시간 아님)</p>}
          </div>

          <ol className="vm-list" aria-label="도착 추정 순 선박">
            {fleet.map(v => {
              const total = routeLengthNm(v.vessel.route)
              const progress = total > 0 && v.remainingNm !== null ? 1 - v.remainingNm / total : v.status === 'berthed' ? 1 : 0
              const cutLeft = v.vessel.cutoffMin - t
              return (
                <li key={v.vessel.id}>
                  <button type="button" className={`vm-item${v.vessel.id === sel.vessel.id ? ' picked' : ''}`} aria-pressed={v.vessel.id === sel.vessel.id} onClick={() => focus(v)}>
                    <span className="vm-item-top">
                      <b>{v.vessel.name ?? '이름 미수신'}</b>
                      <span className="muted">{v.vessel.voyage} · {v.vessel.terminal}{v.vessel.terminal === 'HJNC' ? ' (대상)' : ''}</span>
                      <span className={`vm-chip ${v.status}`}>{STATUS_LABEL[v.status]}</span>
                    </span>
                    <span className="vm-eta">
                      {v.etaMin !== null
                        ? <><b>{formatDuration(v.etaMin - t)}</b> 후 도착 추정 <span className="muted">· {kst(at(base, v.etaMin))}</span></>
                        : <span className="muted">{v.etaNote}</span>}
                    </span>
                    <span className="vm-bar" aria-hidden="true"><span style={{ width: `${Math.round(progress * 100)}%` }} /></span>
                    <span className="vm-meta small">
                      {v.remainingNm !== null && v.status !== 'berthed' && <span>남은 {v.remainingNm.toFixed(1)}해리</span>}
                      {v.status === 'underway' && <span>{v.vessel.speedKn}노트</span>}
                      {v.status === 'stale' && <span className="warn">마지막 위치 {Math.round(v.positionAgeMin)}분 전</span>}
                    </span>
                    <span className={`vm-cutoff small${cutLeft < 0 ? ' past' : cutLeft <= 60 ? ' soon' : ''}`}>
                      반입 마감 {kst(at(base, v.vessel.cutoffMin))} · {cutLeft < 0 ? `${formatDuration(-cutLeft)} 지남` : `${formatDuration(cutLeft)} 남음`}
                      <span className="muted"> (터미널 공지·모의)</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ol>
        </div>

        <details className="vm-notes small">
          <summary>계산 방법과 출처</summary>
          <ul>
            <li>도착 추정 = 남은 항로 길이 ÷ 현재 속력. 조류·감속·도선·선석 대기는 반영하지 않습니다.</li>
            <li>속력이 0인 묘박 선박과 위치가 끊긴 선박은 도착 시각을 만들지 않습니다(마지막 위치에서 멈춤).</li>
            <li>반입 마감은 터미널이 정하는 항차별 시간입니다. 선박 도착 추정이 바뀌어도 자동으로 바뀌지 않습니다.</li>
            <li>항로선은 부표 위치를 참고해 그린 설명용 선이며 공식 항로·도선 경로가 아닙니다. 부표: {SOURCES.seamark}</li>
            <li>터미널 표시는 대표 좌표이며 선석 위치가 아닙니다: {SOURCES.places}</li>
          </ul>
          <p className="vm-legend"><span className="vm-buoy port" /> 좌현 표지 <span className="vm-buoy starboard" /> 우현 표지 <span className="vm-buoy safe" /> 안전수역 표지</p>
        </details>
      </section>
    </main>
  )
}
