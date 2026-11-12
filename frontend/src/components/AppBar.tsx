import { Icon } from './Icon'

/** 왼쪽 사이드바: 서비스 이름과 화면 이동. 화면 전환은 기존 쿼리 규칙(?run=, ?view=map)을 그대로 쓴다. */
export function AppBar({ mode }: { mode: 'http' | 'fixture' }) {
  const params = new URLSearchParams(location.search)
  const view = params.get('view')
  const current = view === 'map' ? 'map' : view === 'reference' ? 'reference' : mode === 'http' && !params.get('run') ? 'start' : 'review'
  const reviewParams = new URLSearchParams(params)
  reviewParams.delete('view')
  const mapParams = new URLSearchParams(reviewParams)
  mapParams.set('view', 'map')
  const refParams = new URLSearchParams(reviewParams)
  refParams.set('view', 'reference')
  const link = (id: string, label: string, href: string, icon: Parameters<typeof Icon>[0]['name'], className?: string) => (
    <a key={id} className={className} href={href} aria-current={id === current ? 'page' : undefined}>
      <Icon name={icon} size={16} />
      {label}
    </a>
  )
  return (
    <header className="appbar">
      <a className="brand" href="?">
        <span className="brand-mark" aria-hidden="true">반</span>
        반입맞춤
        {mode === 'http' && <span className="demo-pill">시연 데이터</span>}
      </a>
      <nav className="side-nav" aria-label="화면">
        {mode === 'http' && link('start', '새 점검', '?', 'plus', 'nav-cta')}
        <p className="nav-group">배차 점검</p>
        {link('review', '배차 점검', `?${reviewParams.toString()}`, 'grid')}
        <p className="nav-group">상황 확인</p>
        {link('map', '입항 선박', `?${mapParams.toString()}`, 'map')}
        {link('reference', '터미널 일정', `?${refParams.toString()}`, 'clock')}
      </nav>
    </header>
  )
}
