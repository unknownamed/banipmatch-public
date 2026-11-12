// 지도 배경(일반/위성) 선택을 화면별로 기억한다. 저장소를 못 쓰는 환경(사생활 보호 창 등)에서는 기본값으로 동작한다.
import { useState } from 'react'

export type MapStyle = 'map' | 'sky'

export function useMapStyle(screen: 'dispatch' | 'vessel', fallback: MapStyle): [MapStyle, (next: MapStyle) => void] {
  const key = `banipmatch.mapStyle.${screen}`
  const [style, setStyle] = useState<MapStyle>(() => {
    try {
      const saved = window.localStorage.getItem(key)
      return saved === 'map' || saved === 'sky' ? saved : fallback
    } catch {
      return fallback
    }
  })
  const update = (next: MapStyle) => {
    setStyle(next)
    try { window.localStorage.setItem(key, next) } catch { /* 기억만 못 할 뿐 화면은 바뀐다 */ }
  }
  return [style, update]
}
