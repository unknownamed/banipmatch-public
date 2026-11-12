// ?view=map — 입항 선박 지도(카카오 일반·위성·위성+지명).
// 계산한 시나리오가 있으면(?scenario=&run=) 같은 항차의 반입 마감을 그 시나리오 값으로 보여 준다.
import { useEffect, useState } from 'react'
import { VesselApproachMap, type ScenarioLink } from './VesselApproachMap'
import { createV2Client } from '../api/v2'

export function MapCheck() {
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
      <VesselApproachMap link={link} />
    </>
  )
}
