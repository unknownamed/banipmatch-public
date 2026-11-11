import { afterEach, expect, it, vi } from 'vitest'
import { createRecipientClient } from './recipient'
afterEach(() => vi.unstubAllGlobals())
it('브라우저 구독 만료시각을 서버에 그대로 전달하고 미제공만 null로 보낸다', async () => {
  const bodies: unknown[] = []
  vi.stubGlobal('fetch', async (_: string, init: RequestInit) => {
    bodies.push(JSON.parse(init.body as string))
    return new Response(JSON.stringify({ subscription_status: 'active' }))
  })
  const c = createRecipientClient()
  await c.subscribe({ endpoint: 'https://push.example.test/push', expirationTime: 1794410000000, keys: { auth: 'example', p256dh: 'example' } })
  await c.subscribe({ endpoint: 'https://push.example.test/push' })
  expect(bodies[0]).toMatchObject({ subscription: { expirationTime: 1794410000000 } })
  expect(bodies[1]).toMatchObject({ subscription: { expirationTime: null } })
})
