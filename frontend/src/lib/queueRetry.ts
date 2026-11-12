// 서버 계산 대기열이 잠깐 찼을 때(429 QUEUE_FULL) 사용자에게 오류를 보이지 않고 잠시 기다렸다 다시 요청한다.
// 같은 요청은 같은 멱등키로 보내므로 중복 실행되지 않는다.
import { ApiRequestError } from '../api/client'

export async function withQueueRetry<T>(call: () => Promise<T>, onWait?: (attempt: number) => void, tries = 20, delayMs = 2000): Promise<T> {
  for (let attempt = 1; ; attempt++) {
    try {
      return await call()
    } catch (e) {
      const busy = e instanceof ApiRequestError && ((e.status === 429 && e.body?.code === 'QUEUE_FULL') || (e.status === 503 && e.body?.code === 'REQUEST_CAPACITY'))
      if (!busy || attempt >= tries) throw e
      onWait?.(attempt)
      await new Promise(r => setTimeout(r, delayMs))
    }
  }
}
