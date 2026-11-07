import { StrictMode, useMemo } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { createHttpClient } from './api/client'
import { createFixtureClient, FIXTURE_IDS } from './api/fixtureClient'
import { MapCheck } from './components/MapCheck'
import './styles.css'

// VITE_API_MODE=http 이면 /v1 백엔드에 연결한다. 기본은 공통 예제(fixture).
const mode = import.meta.env.VITE_API_MODE === 'http' ? 'http' : 'fixture'
const params = new URLSearchParams(location.search)

function Root() {
  const client = useMemo(() => (mode === 'http' ? createHttpClient() : createFixtureClient()), [])
  return (
    <App
      client={client}
      scenarioId={params.get('scenario') ?? FIXTURE_IDS.scenarioId}
      runId={params.get('run') ?? FIXTURE_IDS.runId}
    />
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {params.get('view') === 'map' ? <MapCheck /> : <Root />}
  </StrictMode>,
)
