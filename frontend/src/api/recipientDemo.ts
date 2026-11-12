// 수신자 화면 모의 연결(?demo=1). 서버·네트워크·푸시를 쓰지 않고 이 탭의 메모리에서만 동작한다.
// 화면 확인·발표 캡처용이며 실제 수신·응답 기록이 아니다. 초대 수락만 하면 바로 연결된 상태가 된다.
import { demoAnchor } from '../lib/shift'
import type { RecipientClient, RecipientNotification, RecipientSession } from './recipient'

// 홈·결과 화면과 같은 기준시각(10분 경계)에서 몇 분 뒤인지. 일정은 '오늘 저녁 배차'의 최소 변경안 계산 결과(부산 92바 5520)와 같다.
const at = (minutes: number) => new Date(demoAnchor().getTime() + minutes * 60000).toISOString().replace('.000Z', 'Z')
// 알림 받은 시각은 실제 지금 기준(방금 받은 알림처럼 보이게).
const ago = (minutes: number) => new Date(Math.floor(Date.now() / 60000) * 60000 - minutes * 60000).toISOString().replace('.000Z', 'Z')

export function createDemoRecipientClient(): RecipientClient {
  let session: RecipientSession | null = null
  const notifications: RecipientNotification[] = [
    {
      notification_id: 'N-DEMO-2', delivery_status: 'accepted', created_at: ago(2), opened_at: null, response: 'none', responded_at: null,
      is_current: true, vehicle_ids: ['T5'], response_history: [],
      payload: {
        plan_version: 2, data_mode: 'simulated',
        vehicle_changes: [{
          vehicle_id: 'T5', plate_no: '부산 92바 5520',
          changes: [
            { job_id: 'J07', kind: 'schedule_changed', before: { vehicle_id: 'T5', pickup_departure_at: at(156), gate_arrival_at: at(171) }, after: { vehicle_id: 'T5', pickup_departure_at: at(40), gate_arrival_at: at(55) },
              display: { container_no: 'BNJU1002078', cargo_owner: '가람정밀(주)', origin_name: '녹산산단 상차지', terminal_id: 'HJNC', voyage_id: 'BHMN-2026-0045', size: '20ft' }, instruction: '' },
            { job_id: 'J18', kind: 'reassigned', before: null, before_outside_scope: true, after: { vehicle_id: 'T5', pickup_departure_at: at(148), gate_arrival_at: at(195) },
              display: { container_no: 'BNJU1002186', cargo_owner: '누리화학(주)', origin_name: '김해 안동공단', terminal_id: 'PNIT', voyage_id: 'BE221E', size: '40ft' }, instruction: '' },
            { job_id: 'J06', kind: 'reassigned', before: { vehicle_id: 'T5', pickup_departure_at: at(60), gate_arrival_at: at(90) }, after: { vehicle_id: 'T8', pickup_departure_at: at(50), gate_arrival_at: at(80) },
              display: { container_no: 'BNJU1002062', cargo_owner: '새벽식품(주)', origin_name: '장유 상차지', terminal_id: 'HJNC', voyage_id: 'BHMN-2026-0045', size: '40ft' }, instruction: '' },
          ],
        }],
      },
    },
    {
      notification_id: 'N-DEMO-1', delivery_status: 'superseded', created_at: ago(40), opened_at: ago(38), response: 'none', responded_at: null,
      is_current: false, vehicle_ids: ['T5'], response_history: [], payload: null,
    },
  ]
  const find = (id: string) => {
    const n = notifications.find((x) => x.notification_id === id)
    if (!n) throw new Error('모의 알림 없음')
    return n
  }
  const copy = <T,>(v: T): T => structuredClone(v)

  return {
    restore: async () => {
      if (!session) throw new Error('모의: 아직 연결 전')
      return copy(session)
    },
    claim: async () => (session = { recipient_id: 'demo-recipient', vehicle_ids: ['T5'], expires_at: ago(-24 * 60), csrf_token: 'demo', subscription_status: 'missing', data_mode: 'simulated' }),
    leave: async () => ((session = null), { revoked: true }),
    pushConfig: async () => ({ configured: false, application_server_key: null }),
    subscribe: async () => ({ subscription_status: 'missing' }),
    unsubscribe: async () => ({ subscription_status: 'missing' }),
    shareLocation: async (p) => ({ location_shared: true, captured_at: p.captured_at }),
    stopLocation: async () => ({ location_shared: false, captured_at: null }),
    inbox: async () => ({ notifications: copy(notifications) }),
    notification: async (id) => copy(find(id)),
    opened: async (id) => {
      const n = find(id)
      n.opened_at ??= new Date().toISOString()
      return copy(n)
    },
    respond: async (id, response, note) => {
      const n = find(id)
      if (!n.is_current) throw new Error('이전 계획에는 응답할 수 없습니다(모의).')
      const now = new Date().toISOString()
      Object.assign(n, { response, responded_at: now })
      n.response_history.push({ response, note, created_at: now })
      return copy(n)
    },
  }
}
