// AP-04 확인용: 카카오맵 Web SDK가 이 도메인·키로 뜨는지만 본다. ?view=map 으로 연다.
// 지도는 배경이며 차량 GPS·선박 위치를 표시하지 않는다.
import { useEffect, useRef, useState } from 'react'

declare global {
  interface Window {
    kakao?: any // SDK 타입 패키지를 추가하지 않음
  }
}

// 부산항 신항 부근(배경 중심점일 뿐, 터미널 좌표 자료가 아님)
const CENTER = { lat: 35.075, lng: 128.81 }

export function MapCheck() {
  const box = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState('지도 SDK 불러오는 중…')
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
        new maps.Map(box.current, { center: new maps.LatLng(CENTER.lat, CENTER.lng), level: 7 })
        setStatus(`지도 표시 성공 · ${location.origin}`)
      })
    }
    s.onerror = () =>
      setStatus(`SDK 로드 실패. JavaScript SDK 도메인에 ${location.origin} 이 등록됐는지, 키가 JavaScript 키인지 확인하세요.`)
    document.head.appendChild(s)
    return () => s.remove()
  }, [key])

  return (
    <main>
      <section className="card">
        <h2>카카오맵 연결 확인 (AP-04)</h2>
        <p className={status.startsWith('지도 표시 성공') ? 'ok' : 'muted'} data-testid="map-status">
          {status}
        </p>
        <p className="muted small">배경 지도만 표시합니다. 차량·선박 위치나 경로 자료가 아닙니다.</p>
        <div ref={box} style={{ width: '100%', height: 420, borderRadius: 6, background: '#eef1f4' }} />
      </section>
    </main>
  )
}
