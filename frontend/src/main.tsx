import { StrictMode, Suspense, lazy, useMemo } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import { createHttpClient } from './api/client'
import { createFixtureClient, FIXTURE_IDS } from './api/fixtureClient'
import { createV2Client } from './api/v2'
import { AppBar } from './components/AppBar'
const MapCheck = lazy(() => import('./components/MapCheck').then(m => ({ default: m.MapCheck })))
import { StartRunPanel } from './components/StartRunPanel'
import { RecipientApp } from './components/RecipientApp'
import { createRecipientClient } from './api/recipient'
import { createDemoRecipientClient } from './api/recipientDemo'
import { takeFragment } from './lib/recipient'
import { ReferencePanel } from './components/ReferencePanel'
import './styles.css'
import './styles/v3.css'

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

// 수신자(시험 기사) 화면은 담당자 화면과 분리한다. 담당자 메뉴·API를 싣지 않는다.
const recipient = location.pathname.replace(/\/+$/, '') === '/recipient'
if (recipient) {
  // 홈 화면 추가(iPhone 웹 푸시 조건)는 수신자 화면에서만 제공한다.
  for (const [tag, attrs] of [
    ['link', { rel: 'manifest', href: '/manifest.webmanifest' }],
    ['link', { rel: 'apple-touch-icon', href: '/icon-180.png' }],
    ['meta', { name: 'apple-mobile-web-app-capable', content: 'yes' }],
    ['meta', { name: 'theme-color', content: '#d23a06' }],
  ] as const)
    document.head.append(Object.assign(document.createElement(tag), attrs))
  document.title = '반입맞춤 · 기사 알림'
}
// React(StrictMode는 초기화를 두 번 실행)보다 먼저 한 번만 읽고 지운다.
const recipientBoot = recipient ? takeFragment() : null
// ?demo=1: 서버 없이 수신자 화면을 보는 모의 링크(가짜 초대가 미리 들어 있음).
const recipientDemo = recipient && params.get('demo') === '1'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {recipient ? (
      recipientDemo ? (
        <RecipientApp client={createDemoRecipientClient()} boot={{ invite: 'demo-invite', notification: null }} demo />
      ) : (
        <RecipientApp client={createRecipientClient()} boot={recipientBoot!} />
      )
    ) : (
      <>
        <AppBar mode={mode} />
        <Suspense fallback={<main><p role="status">지도 불러오는 중…</p></main>}>{params.get('view') === 'map' ? <MapCheck /> : params.get('view') === 'reference' ? <ReferencePanel /> : <Root />}</Suspense>
      </>
    )}
  </StrictMode>,
)
