/** 상단 바: 서비스 이름과 화면 이동 탭. 화면 전환은 기존 쿼리 규칙(?run=, ?view=map)을 그대로 쓴다. */
export function AppBar({ mode }: { mode: 'http' | 'fixture' }) {
  const params = new URLSearchParams(location.search)
  const current = params.get('view') === 'map' ? 'map' : mode === 'http' && !params.get('run') ? 'start' : 'review'
  const links = [
    ...(mode === 'http' ? [{ id: 'start', label: '계산 요청', href: '?' }] : []),
    { id: 'review', label: '비교 · 승인', href: mode === 'http' ? location.search.replace(/[?&]view=map/, '') || '?' : '?' },
    { id: 'map', label: '지도 확인', href: '?view=map' },
  ]
  return (
    <header className="appbar">
      <a className="brand" href="?">
        <span className="brand-mark" aria-hidden="true">반</span>
        반입맞춤
      </a>
      <nav className="pill-nav" aria-label="화면">
        {links.map((l) => (
          <a key={l.id} href={l.href} aria-current={l.id === current ? 'page' : undefined}>
            {l.label}
          </a>
        ))}
      </nav>
      <span className="appbar-note">{mode === 'http' ? '로컬 모의 API' : '공통 예제'}</span>
    </header>
  )
}
