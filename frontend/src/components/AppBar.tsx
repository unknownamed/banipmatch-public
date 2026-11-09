/** 왼쪽 사이드바: 서비스 이름과 화면 이동. 화면 전환은 기존 쿼리 규칙(?run=, ?view=map)을 그대로 쓴다. */
export function AppBar({ mode }: { mode: 'http' | 'fixture' }) {
  const params = new URLSearchParams(location.search)
  const current = params.get('view') === 'map' ? 'map' : mode === 'http' && !params.get('run') ? 'start' : 'review'
  const reviewParams = new URLSearchParams(params)
  reviewParams.delete('view')
  const mapParams = new URLSearchParams(reviewParams)
  mapParams.set('view', 'map')
  const link = (id: string, label: string, href: string, className?: string) => (
    <a key={id} className={className} href={href} aria-current={id === current ? 'page' : undefined}>
      {label}
    </a>
  )
  return (
    <header className="appbar">
      <a className="brand" href="?">
        <span className="brand-mark" aria-hidden="true">반</span>
        반입맞춤
      </a>
      <nav className="side-nav" aria-label="화면">
        {mode === 'http' && link('start', '계산 요청', '?', 'nav-cta')}
        <p className="nav-group">배차 점검</p>
        {link('review', '비교 · 승인', `?${reviewParams.toString()}`)}
        <p className="nav-group">확인</p>
        {link('map', '지도 확인', `?${mapParams.toString()}`)}
      </nav>
      <span className="appbar-note">{mode === 'http' ? '로컬 모의 API' : '공통 예제'}</span>
    </header>
  )
}
