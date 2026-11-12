// 지도 배경(일반·위성)과 겹쳐 볼 정보를 고르는 메뉴. 지도 앱처럼 미리보기 그림을 눌러 고르고, 겹쳐 보기는 스위치로 켠다.
import { useEffect, useRef, useState } from 'react'
import { Icon } from './Icon'

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
              <span className="lp-thumb road" aria-hidden="true" />일반
            </button>
            <button type="button" className={`lp-tile${sky ? ' on' : ''}`} aria-pressed={sky} onClick={() => onSky(true)}>
              <span className="lp-thumb sky" aria-hidden="true" />위성
            </button>
          </div>
          {onTraffic && (
            <label className="lp-switch">
              <span>실시간 교통</span>
              <input type="checkbox" role="switch" checked={!!traffic} onChange={(e) => onTraffic(e.target.checked)} />
              <i aria-hidden="true" />
            </label>
          )}
        </div>
      )}
    </div>
  )
}
