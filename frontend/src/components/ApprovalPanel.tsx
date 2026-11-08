import { useRef, useState } from 'react'
import type { ApiClient } from '../api/client'
import { ApiRequestError } from '../api/client'
import type { Approval, MethodResult, Run } from '../api/types'
import { acknowledgeIds, approvalErrorHint, approvalResponseMatches, approvalRetryAllowed, currentPlanWarning, type ApprovalGate } from '../lib/approval'
import { kstDateTime } from '../lib/time'

export type Status =
  | { state: 'idle' }
  | { state: 'sending' }
  | { state: 'done'; approval: Approval; planWarning: string | null }
  | { state: 'error'; error: unknown; retryable: boolean; uncertain: boolean }

/** 한 실행의 승인 진행 상태. 방법 탭을 바꿔도 사라지지 않도록 App이 보관한다(PR #9 리뷰). */
export type SharedApproval = { method: string; status: Status } | null

/**
 * 운송사 내부 계획 승인. 버튼은 approvalGate를 통과할 때만 열리고, 최종 판단은 서버가 다시 한다.
 * 미처리·고정 위험 작업을 확인해야 보낼 수 있다. 재시도는 같은 Idempotency-Key를 쓴다.
 */
export function ApprovalPanel({ gate, client, run, result, idempotencyKey, shared: sharedProp, onShared }: {
  gate: ApprovalGate; client: ApiClient; run: Run | null; result: MethodResult; idempotencyKey?: string
  shared?: SharedApproval; onShared?: (s: SharedApproval) => void
}) {
  const ack = acknowledgeIds(result)
  const [checked, setChecked] = useState(false)
  const [local, setLocal] = useState<SharedApproval>(null)
  const shared = sharedProp !== undefined ? sharedProp : local
  const publish = onShared ?? setLocal
  const method = result.method
  const setStatus = (status: Status) => publish({ method, status })
  // 다른 방법이 전송 중·승인됨·처리 여부 불명이면 이 방법은 보내지 않는다. 같은 계획을 두 번 승인하지 않기 위함.
  const otherBusy = shared !== null && shared.method !== method && (shared.status.state === 'sending' || shared.status.state === 'done' || (shared.status.state === 'error' && shared.status.uncertain))
  const status: Status = shared?.method === method ? shared.status : { state: 'idle' }
  const [fallbackKey] = useState(() => `approve-${crypto.randomUUID()}`)
  const sending = useRef(false)
  const attempt = useRef<{ planId: string; request: Parameters<NonNullable<ApiClient['approve']>>[1]; key: string } | null>(null)
  const canSend = !otherBusy && gate.allowed && !!client.approve && !!run && (ack.length === 0 || checked) && status.state !== 'sending' && status.state !== 'done' && (status.state !== 'error' || status.retryable)

  async function send() {
    if (!canSend || sending.current || !run || !client.approve) return
    sending.current = true // React의 다음 렌더 전에 들어오는 중복 클릭도 차단
    attempt.current ??= {
      planId: run.plan_id,
      request: { run_id: run.run_id, method: result.method, expected_version: run.base_plan_version, acknowledged_job_ids: [...ack] },
      key: idempotencyKey ?? fallbackKey,
    }
    const submitted = attempt.current
    setStatus({ state: 'sending' })
    try {
      const approval = await client.approve(
        submitted.planId,
        submitted.request,
        submitted.key,
      )
      if (!approvalResponseMatches(approval, run, result.method)) {
        setStatus({ state: 'error', error: new Error('승인 응답의 계획·실행·방법·버전 또는 외부 반영 상태가 요청과 맞지 않습니다. 현재 계획을 다시 확인하세요.'), retryable: false, uncertain: true })
        return
      }
      // 승인 응답과 별개로 서버의 현재 계획 버전을 다시 읽는다.
      const plan = await client.getPlan?.(run.plan_id).catch(() => null)
      setStatus({ state: 'done', approval, planWarning: currentPlanWarning(plan ?? null, approval, run.scenario_id) })
    } catch (error) {
      // 코드가 있는 503(유효기간·미확인 근거 등)은 서버의 확정 거절이다. 처리 여부를 모르는 건 재시도 대상뿐이다.
      const retryable = !(error instanceof ApiRequestError) || approvalRetryAllowed(error.status, error.body?.code)
      setStatus({ state: 'error', error, retryable, uncertain: retryable })
    } finally {
      sending.current = false
    }
  }

  const err = status.state === 'error' ? status.error : null
  const otherLabel = shared?.status.state === 'sending' ? '승인 요청 중입니다' : shared?.status.state === 'done' ? '승인되었습니다' : '승인 결과를 확인해야 합니다'
  return (
    <section className="card">
      <h2>운송사 내부 계획 승인</h2>
      <p className="muted">내부 배차 계획만 확정합니다. 터미널 방문예약 변경, 기존 TMS 반영, 기사 통보는 하지 않습니다.</p>
      {otherBusy && (
        <p className="warn" role="status">
          이 실행은 {shared!.method} 조정안이 {otherLabel}. {shared!.method} 탭에서 결과를 확인하세요. 다른 방법은 보낼 수 없습니다.
        </p>
      )}
      {ack.length > 0 && (
        <p>
          <label>
            <input type="checkbox" checked={checked} disabled={otherBusy || !gate.allowed || (status.state !== 'idle' && !(status.state === 'error' && status.retryable))} onChange={(e) => setChecked(e.target.checked)} />{' '}
            미처리·고정 위험 작업 <b>{ack.join(', ')}</b>을(를) 확인했습니다.
          </label>
        </p>
      )}
      <button type="button" disabled={!canSend} title={gate.reasons.join('\n')} onClick={send}>
        {status.state === 'sending' ? '승인 요청 중…' : status.state === 'error' && status.retryable ? '다시 시도' : `${result.method} 조정안 승인`}
      </button>
      {!gate.allowed && (
        <ul className="warn">
          {gate.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {status.state === 'done' && (
        <div role="status">
          <p className="ok">
            내부 계획 v{status.approval.version} 승인됨 · {kstDateTime(status.approval.approved_at)}
            {' '}· 외부 반영 없음
          </p>
          {status.planWarning && <p className="warn">{status.planWarning}</p>}
        </div>
      )}
      {err !== null && (
        <div className="warn" role="alert">
          <p>
            {status.state === 'error' && status.uncertain ? '승인 결과 확인 필요: ' : '승인 거절: '}
            {err instanceof ApiRequestError
              ? `HTTP ${err.status}${err.body ? ` ${err.body.code}` : ''} — ${err.message}`
              : err instanceof Error ? err.message : String(err)}
          </p>
          {status.state === 'error' && status.uncertain && status.retryable && <p>서버에서 이미 처리됐을 수 있습니다. 다시 시도하면 같은 요청 내용과 키로 결과를 확인합니다.</p>}
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
