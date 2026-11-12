// ?view=map — 입항 선박 지도(카카오 일반·위성·위성+지명). 예전 AIS 수신 형식 재생 화면은 보조로 남긴다.
// 계산한 시나리오가 있으면(?scenario=&run=) 같은 항차의 반입 마감을 그 시나리오 값으로 보여 준다.
import { useEffect, useState } from 'react'
import { FleetMap } from './FleetMap'
import { VesselApproachMap, type ScenarioLink } from './VesselApproachMap'
import { createV2Client } from '../api/v2'

export function MapCheck() {
  const [aisReplay, setAisReplay] = useState(false)
  const [link, setLink] = useState<ScenarioLink | null>(null)
  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const scenario = params.get('scenario')
    if (import.meta.env.VITE_API_MODE !== 'v2' || !scenario) return
    const review = new URLSearchParams(params)
    review.delete('view')
    const ctl = new AbortController()
    createV2Client().getScenario(scenario, ctl.signal)
      .then(snapshot => setLink({ snapshot, reviewHref: `?${review.toString()}` }))
      .catch(() => setLink(null))
    return () => ctl.abort()
  }, [])
  return (
    <>
      {aisReplay ? <FleetMap /> : <VesselApproachMap link={link} />}
      <div className="map-choice">
        <button className="secondary" onClick={() => setAisReplay(!aisReplay)}>
          {aisReplay ? '입항 선박 지도로 돌아가기' : 'AIS 수신 형식 재생(시험 화면) 보기'}
        </button>
      </div>
    </>
  )
}
