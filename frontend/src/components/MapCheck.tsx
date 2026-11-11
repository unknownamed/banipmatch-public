// AP-04 확인용: 카카오맵 Web SDK가 이 도메인·키로 뜨는지만 본다. ?view=map 으로 연다.
// 지도는 배경이며 차량 GPS·선박 위치를 표시하지 않는다.
import { tokens } from '../styles/tokens'
import { useEffect, useRef, useState } from 'react'
import { FleetMap } from './FleetMap'

declare global {
  interface Window {
    kakao?: any // SDK 타입 패키지를 추가하지 않음
  }
}

// 부산항 신항 부근(배경 중심점일 뿐, 터미널 좌표 자료가 아님)
const CENTER = { lat: 35.075, lng: 128.81 }

// 같은 지도 객체의 종류만 바꾼다. 새로 만들지 않으므로 보던 중심·확대 수준이 그대로 유지된다.
const MAP_TYPES = [
  ['ROADMAP', '일반 지도'],
  ['SKYVIEW', '위성'],
  ['HYBRID', '위성 + 지명'],
] as const
type MapType = (typeof MAP_TYPES)[number][0]

export function MapCheck() {
  const [satellite, setSatellite] = useState(false)
  return <><div className="map-choice"><button className="secondary" onClick={()=>setSatellite(!satellite)}>{satellite?'모의 선박 지도':'카카오 일반·위성 지도 연결'}</button></div>{satellite?<KakaoMapCheck/>:<FleetMap/>}</>
}

function KakaoMapCheck() {
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<any>(null)
  const [status, setStatus] = useState('지도 SDK 불러오는 중…')
  const [mapType, setMapType] = useState<MapType>('ROADMAP')
  const [ready, setReady] = useState(false)
  const key = import.meta.env.VITE_KAKAO_MAP_KEY as string | undefined

  useEffect(() => {
    if (!key) {
      setStatus('VITE_KAKAO_MAP_KEY가 없습니다. frontend/.env.local 을 확인하고 개발 서버를 다시 시작하세요.')
      return
    }
    const s = document.createElement('script')
    s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false`
    s.onload = () => {
      if (!window.kakao?.maps) {
        setStatus('SDK 응답은 왔지만 kakao.maps가 없습니다. 키 종류(JavaScript 키)와 카카오맵 사용 설정을 확인하세요.')
        return
      }
      window.kakao.maps.load(() => {
        const { maps } = window.kakao
        map.current = new maps.Map(box.current, { center: new maps.LatLng(CENTER.lat, CENTER.lng), level: 7 })
        setReady(true)
        setStatus(`지도 표시 성공 · ${location.origin}`)
      })
    }
    s.onerror = () =>
      setStatus(`SDK 로드 실패. JavaScript SDK 도메인에 ${location.origin} 이 등록됐는지, 키가 JavaScript 키인지 확인하세요.`)
    document.head.appendChild(s)
    return () => s.remove()
  }, [key])

  useEffect(() => {
    if (ready) map.current?.setMapTypeId(window.kakao.maps.MapTypeId[mapType])
  }, [ready, mapType])

  return (
    <main>
      <section className="card">
        <h2>카카오맵 연결 확인 (AP-04)</h2>
        <p className={status.startsWith('지도 표시 성공') ? 'ok' : 'muted'} data-testid="map-status">
          {status}
        </p>
        <p className="muted small">배경 지도만 표시합니다. 차량·선박 위치나 경로 자료가 아닙니다.</p>
        <div className="tabs" role="radiogroup" aria-label="지도 종류">
          {MAP_TYPES.map(([id, label]) => (
            <button key={id} type="button" role="radio" aria-checked={mapType === id} aria-selected={mapType === id} disabled={!ready} onClick={() => setMapType(id)}>{label}</button>
          ))}
        </div>
        {mapType !== 'ROADMAP' && <p className="muted small">위성 사진은 촬영 시점의 배경이며 실시간 영상이 아닙니다. 현재 선박·차량·야드 상태를 보여주지 않습니다.</p>}
        <div ref={box} style={{ width: '100%', height: 420, borderRadius: tokens.radius.md, background: tokens.color.hover }} />
      </section>
    </main>
  )
}
