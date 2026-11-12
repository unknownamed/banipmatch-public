// 반입맞춤 수신자 Service Worker: 웹 푸시 표시와 알림 클릭만 한다(오프라인 캐시 없음).
// 잠금 화면에는 서버가 보낸 일반 문구만 쓴다. 일정·차량·기사·항차 정보는 화면에서 권한 확인 후 조회한다.

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

const GENERIC = { title: '반입맞춤 변경 알림', body: '변경 내용을 확인해 주세요.' }

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = {}
  }
  const id = typeof data.notification_id === 'string' ? data.notification_id : null
  // 같은 출처의 /recipient 경로만 연다(다른 주소로 보내지 않음).
  const url = id ? `/recipient#notification=${encodeURIComponent(id)}` : '/recipient'
  event.waitUntil(
    self.registration.showNotification(GENERIC.title, {
      body: GENERIC.body,
      icon: '/icon-192.png?v=navy1',
      tag: id || 'banipmatch',
      data: { url, notification_id: id },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const { url, notification_id } = event.notification.data || {}
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      const open = windows.find((w) => new URL(w.url).pathname === '/recipient')
      if (open) {
        await open.focus()
        if (notification_id) open.postMessage({ notification_id })
        return
      }
      await self.clients.openWindow(url || '/recipient')
    })(),
  )
})
