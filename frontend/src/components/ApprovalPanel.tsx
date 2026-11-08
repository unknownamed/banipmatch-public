import { useState } from 'react'
import type { ApiClient } from '../api/client'
import { ApiRequestError } from '../api/client'
import type { Approval, MethodResult, Run } from '../api/types'
import { acknowledgeIds, approvalErrorHint, type ApprovalGate } from '../lib/approval'
import { kstDateTime } from '../lib/time'

type Status =
  | { state: 'idle' }
  | { state: 'sending' }
  | { state: 'done'; approval: Approval; planVersion: number | null }
  | { state: 'error'; error: unknown }

/**
 * 운송사 내부 계획 승인. 버튼은 approvalGate를 통과할 때만 열리고, 최종 판단은 서버가 다시 한다.
 * 미처리·고정 위험 작업을 확인해야 보낼 수 있다. 재시도는 같은 Idempotency-Key를 쓴다.
 */
export function ApprovalPanel({ gate, client, run, result }: { gate: ApprovalGate; client: ApiClient; run: Run | null; result: MethodResult }) {
  const ack = acknowledgeIds(result)
  const [checked, setChecked] = useState(false)
  const [status, setStatus] = useState<Status>({ state: 'idle' })
  const [key] = useState(() => `approve-${crypto.randomUUID()}`) // App이 run+method마다 새로 마운트한다
  const canSend = gate.allowed && !!client.approve && !!run && (ack.length === 0 || checked) && status.state !== 'sending' && status.state !== 'done'

  async function send() {
    if (!run || !client.approve) return
    setStatus({ state: 'sending' })
    try {
      const approval = await client.approve(
        run.plan_id,
        { run_id: run.run_id, method: result.method, expected_version: run.base_plan_version, acknowledged_job_ids: ack },
        key,
      )
      // 승인 응답과 별개로 서버의 현재 계획 버전을 다시 읽는다.
      const plan = await client.getPlan?.(run.plan_id).catch(() => null)
      setStatus({ state: 'done', approval, planVersion: plan?.version ?? null })
    } catch (error) {
      setStatus({ state: 'error', error })
    }
  }

  const err = status.state === 'error' ? status.error : null
  return (
    <section className="card">
      <h2>운송사 내부 계획 승인</h2>
      <p className="muted">내부 배차 계획만 확정합니다. 터미널 방문예약 변경, 기존 TMS 반영, 기사 통보는 하지 않습니다.</p>
      {ack.length > 0 && (
        <p>
          <label>
            <input type="checkbox" checked={checked} disabled={!gate.allowed || status.state === 'done'} onChange={(e) => setChecked(e.target.checked)} />{' '}
            미처리·고정 위험 작업 <b>{ack.join(', ')}</b>을(를) 확인했습니다.
          </label>
        </p>
      )}
      <button type="button" disabled={!canSend} title={gate.reasons.join('\n')} onClick={send}>
        {status.state === 'sending' ? '승인 요청 중…' : status.state === 'error' ? '다시 시도' : `${result.method} 조정안 승인`}
      </button>
      {!gate.allowed && (
        <ul className="warn">
          {gate.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {status.state === 'done' && (
        <p className="ok" role="status">
          내부 계획 v{status.approval.version} 승인됨 · {kstDateTime(status.approval.approved_at)}
          {status.planVersion !== null && status.planVersion !== status.approval.version && ` (서버 현재 계획 v${status.planVersion})`} · 외부 반영{' '}
          {status.approval.external_actions_performed ? '있음' : '없음'}
        </p>
      )}
      {err !== null && (
        <div className="warn" role="alert">
          <p>
            승인 실패:{' '}
            {err instanceof ApiRequestError
              ? `HTTP ${err.status}${err.body ? ` ${err.body.code}` : ''} — ${err.message}`
              : `서버에 연결하지 못했습니다(${err instanceof Error ? err.message : String(err)}).`}
          </p>
          {err instanceof ApiRequestError && approvalErrorHint(err.status, err.body?.code) && <p>{approvalErrorHint(err.status, err.body?.code)}</p>}
          {err instanceof ApiRequestError &&
            err.body?.details?.map((d) => (
              <p key={d.path} className="small">
                <code>{d.path}</code> {d.reason}
              </p>
            ))}
        </div>
      )}
    </section>
  )
}
