// ?view=map — 입항 선박 지도(카카오 일반·위성·위성+지명). 예전 AIS 수신 형식 재생 화면은 보조로 남긴다.
import { useState } from 'react'
import { FleetMap } from './FleetMap'
import { VesselApproachMap } from './VesselApproachMap'

export function MapCheck() {
  const [aisReplay, setAisReplay] = useState(false)
  return (
    <>
      {aisReplay ? <FleetMap /> : <VesselApproachMap />}
      <div className="map-choice">
        <button className="secondary" onClick={() => setAisReplay(!aisReplay)}>
          {aisReplay ? '입항 선박 지도로 돌아가기' : 'AIS 수신 형식 재생(시험 화면) 보기'}
        </button>
      </div>
    </>
  )
}
