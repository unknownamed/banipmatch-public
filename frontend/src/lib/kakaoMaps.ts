// 카카오맵 Web SDK를 한 번만 불러온다. 키가 없거나 실패하면 이유를 돌려주고 화면은 지도 없이 동작한다.
declare global {
  interface Window {
    kakao?: any // SDK 타입 패키지를 추가하지 않음
  }
}

let pending: Promise<any> | null = null

export function kakaoKey(): string | undefined {
  return import.meta.env.VITE_KAKAO_MAP_KEY as string | undefined
}

export function loadKakaoMaps(): Promise<any> {
  if (window.kakao?.maps?.Map) return Promise.resolve(window.kakao.maps)
  if (pending) return pending
  const key = kakaoKey()
  if (!key) return Promise.reject(new Error('지도 연결 설정이 아직 준비되지 않았습니다.'))
  pending = new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false`
    s.onload = () => {
      if (!window.kakao?.maps) { pending = null; reject(new Error('지도 응답을 확인하지 못했습니다.')); return }
      window.kakao.maps.load(() => resolve(window.kakao.maps))
    }
    s.onerror = () => { pending = null; s.remove(); reject(new Error('지도 서버에 연결하지 못했습니다.')) }
    document.head.appendChild(s)
  })
  return pending
}

export const MAP_TYPES = [
  ['ROADMAP', '일반'],
  ['SKYVIEW', '위성'],
  ['HYBRID', '위성+지명'],
] as const
export type MapType = (typeof MAP_TYPES)[number][0]

/** 지도 상자의 크기가 바뀌면(화면 회전·창 크기·레이아웃 변화) 타일을 다시 깔아 빈 회색 영역이 남지 않게 한다. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function keepLaidOut(map: any, el: HTMLElement, refit?: () => void): () => void {
  if (typeof ResizeObserver === 'undefined') return () => {}
  const ro = new ResizeObserver(() => {
    const c = map.getCenter()
    map.relayout()
    // 범위를 다시 맞출 함수가 있으면(차량·터미널 전체 보기) 새 크기에 맞춰 다시 맞춘다.
    if (refit) refit()
    else map.setCenter(c)
  })
  ro.observe(el)
  return () => ro.disconnect()
}
