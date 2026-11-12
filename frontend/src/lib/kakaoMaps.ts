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
