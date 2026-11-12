import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import replay from '../fixtures/ais-fleet.synthetic.json'

export function FleetMap() {
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const markers = useRef(new Map<number,L.CircleMarker>())
  const [step, setStep] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [picked, setPicked] = useState<number | null>(null)
  const [tileError, setTileError] = useState(false)
  const frame = replay.frames[step]
  const selected = frame.ships.find(s => s.mmsi === picked)
  useEffect(() => {
    if (!box.current) return
    const m = L.map(box.current).setView([35.065,128.79],12)
    map.current = m
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 18,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
    }).on('tileerror', () => setTileError(true)).addTo(m)
    return () => { m.remove(); map.current=null; markers.current.clear() }
  }, [])
  useEffect(() => {
    if (!map.current) return
    for (const ship of frame.ships) {
      if (!ship.position) continue
      let marker = markers.current.get(ship.mmsi)
      if (!marker) {
        marker = L.circleMarker([ship.position.latitude,ship.position.longitude], { radius:8,weight:2,fillOpacity:.85 }).addTo(map.current)
        const label=document.createElement('span'); label.textContent=ship.name || `모의 선박 ${ship.mmsi}`
        marker.bindTooltip(label).on('click', () => setPicked(ship.mmsi))
        markers.current.set(ship.mmsi,marker)
      }
      marker.setLatLng([ship.position.latitude,ship.position.longitude])
      marker.setStyle({color: ship.position_status==='stale'?'#777':'#d23a06',fillOpacity:ship.position_status==='stale'?.3:.85})
    }
  },[frame])
  useEffect(() => {
    if(!playing) return
    const t=setInterval(()=>setStep(s=> { if(s>=replay.frames.length-1) return s; return s+1 }),500)
    return()=>clearInterval(t)
  },[playing])
  useEffect(()=> { if(step===replay.frames.length-1) setPlaying(false) },[step])
  return <main><section className="card">
    <h2>부산 신항 · 선박 위치 모의 재생</h2>
    <div className="banner fixture">지도 배경은 OpenStreetMap, 움직이는 선박은 모두 합성입니다. 실제 부산 선박·항차·차량 GPS가 아닙니다.</div>
    <p className="small muted">AISstream 형식의 메시지 {replay.wire_event_count}건을 읽어 선박 {replay.vessel_count}척의 10분 흐름을 재생합니다. 위치 갱신 중단 2척·선박 이름 누락 1척을 포함합니다. 이 좌표로 반입 마감이나 지연 원인을 결정하지 않습니다.</p>
    <div className="fleet-controls">
      <button onClick={()=>setPlaying(!playing)} disabled={step===replay.frames.length-1}>{playing?'일시 정지':'재생 (20배속)'}</button>
      <button className="secondary" onClick={()=>{setPlaying(false);setStep(0)}}>처음으로</button>
      <label>재생 시각 {Math.floor(frame.second/60)}분 {frame.second%60}초 <input aria-label="재생 시각" type="range" min="0" max={replay.frames.length-1} value={step} onChange={e=>{setPlaying(false);setStep(Number(e.target.value))}}/></label>
    </div>
    {tileError && <p role="alert" className="warn small">지도 배경 일부를 받지 못했습니다. 선박 표시는 합성 좌표이며 지도 실패를 실제 자료로 대체하지 않습니다.</p>}
    <div ref={box} className="fleet-map" aria-label="부산 신항 배경 지도와 모의 선박 위치" />
    <p className="small">주황: 최근 모의 위치 · 회색: 90초 이상 위치 갱신 없음(이후 위치 추정 안 함). 점을 누르면 식별자·시각을 확인합니다.</p>
    {selected && <p className="card small"><b>{selected.name ?? '이름 수신 안 됨'}</b> · 가상 MMSI {selected.mmsi}<br/>위도 {selected.position?.latitude} · 경도 {selected.position?.longitude} · 위치 나이 {selected.age_seconds}초 · {selected.position_status==='stale'?'오래된 위치':'모의 위치 갱신'}<br/>가상 식별자는 실제 선박에 연결하지 않습니다.</p>}
    <details><summary>선박별 수신 상태</summary><table className="grid small"><thead><tr><th>모의 선박</th><th>가상 MMSI</th><th>위치 상태</th><th>나이</th></tr></thead><tbody>{frame.ships.map(s=><tr key={s.mmsi}><td>{s.name??'이름 누락'}</td><td>{s.mmsi}</td><td>{s.position_status==='stale'?'오래됨':'갱신'}</td><td>{s.age_seconds}초</td></tr>)}</tbody></table></details>
    <p className="small muted">공식 형식: <a href={replay.format_source} target="_blank" rel="noreferrer">AISstream</a> · 직선 이동은 설명용이며 실제 항행 가능한 항로 검증을 하지 않았습니다. 실제 수신 결과는 ‘참고 자료’에서 별도로 확인합니다.</p>
  </section></main>
}
