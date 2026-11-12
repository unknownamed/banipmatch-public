// 지도 배경(일반·위성)과 겹쳐 볼 정보를 고르는 메뉴. 지도 앱처럼 미리보기 그림을 눌러 고르고, 겹쳐 보기는 스위치로 켠다.
import { useEffect, useRef, useState } from 'react'
import { Icon } from './Icon'

// 미리보기는 지금 보는 부산신항 일대의 실제 카카오 지도 타일(일반·위성·실시간 교통)을 쓴다.
const TILE = { x: 28, y: 48, level: 8 }
const ROAD = `https://mts.kakaocdn.net/api/v1/tile/PNG02/v27_pps0b/latest/${TILE.level}/${TILE.x}/${TILE.y}.png`
const SKY = `https://map.kakaocdn.net/map_skyview_hd/L${TILE.level}/${TILE.x}/${TILE.y}.jpg`
const TRAFFIC = `https://ctt-image.kakaocdn.net/mapserver/file/realtimeroad_hd/L${TILE.level}/${TILE.x}/${TILE.y}.png`

export function LayerMenu({ sky, onSky, traffic, onTraffic, disabled }: {
  sky: boolean
  onSky: (sky: boolean) => void
  traffic?: boolean
  onTraffic?: (on: boolean) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  // 메뉴 밖을 누르거나 Esc를 누르면 닫는다.
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey) }
  }, [open])
  return (
    <div className="layers" ref={box}>
      <button type="button" className="chip-toggle" aria-expanded={open} disabled={disabled} onClick={() => setOpen(!open)}>
        <Icon name="map" size={14} /> 레이어
      </button>
      {open && (
        <div className="layers-pop" role="dialog" aria-label="지도 레이어">
          <div className="lp-tiles" role="group" aria-label="지도 종류">
            <button type="button" className={`lp-tile${!sky ? ' on' : ''}`} aria-pressed={!sky} onClick={() => onSky(false)}>
              <span className="lp-thumb" style={{ backgroundImage: `url(${ROAD})` }} aria-hidden="true" />일반
            </button>
            <button type="button" className={`lp-tile${sky ? ' on' : ''}`} aria-pressed={sky} onClick={() => onSky(true)}>
              <span className="lp-thumb" style={{ backgroundImage: `url(${SKY})` }} aria-hidden="true" />위성
            </button>
          </div>
          {onTraffic && (
            <label className="lp-switch">
              <span className="lp-mini" style={{ backgroundImage: `url(${TRAFFIC}), url(${sky ? SKY : ROAD})` }} aria-hidden="true" />
              <span className="lp-name">실시간 교통</span>
              <input type="checkbox" role="switch" checked={!!traffic} onChange={(e) => onTraffic(e.target.checked)} />
              <i aria-hidden="true" />
            </label>
          )}
        </div>
      )}
    </div>
  )
}
