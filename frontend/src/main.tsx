import { StrictMode, useMemo } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { createHttpClient } from './api/client'
import { createFixtureClient, FIXTURE_IDS } from './api/fixtureClient'
import { createV2Client } from './api/v2'
import { AppBar } from './components/AppBar'
import { MapCheck } from './components/MapCheck'
import { StartRunPanel } from './components/StartRunPanel'
import './styles.css'

// VITE_API_MODE=http 이면 /v1, v2 이면 담당자 대응 API(/v2, 세션 쿠키)에 연결한다. 기본은 공통 예제(fixture).
const apiMode = import.meta.env.VITE_API_MODE
const mode = apiMode === 'http' || apiMode === 'v2' ? 'http' : 'fixture'
const params = new URLSearchParams(location.search)

function Root() {
  const client = useMemo(
    () => (apiMode === 'v2' ? createV2Client() : mode === 'http' ? createHttpClient('', import.meta.env.VITE_API_TOKEN) : createFixtureClient()),
    [],
  )
  // 서버 run_id는 서버가 만든다. http 모드에서 run이 없으면 계산 요청부터 시작한다.
  if (mode === 'http' && !params.get('run')) return <StartRunPanel client={client} />
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
    <AppBar mode={mode} />
    {params.get('view') === 'map' ? <MapCheck /> : <Root />}
  </StrictMode>,
)
