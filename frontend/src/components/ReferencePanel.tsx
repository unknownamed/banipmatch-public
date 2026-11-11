import { useState } from 'react'
import fixture from '../fixtures/reference-preview.synthetic.json'
import { BLOCKER_LABEL, KIND_LABEL, display, type ReferenceView } from '../lib/reference'
import { kstDateTime } from '../lib/time'

type Source = 'live' | 'replay' | 'mock'
const cases = fixture.cases as unknown as { id: string; label: string; view: ReferenceView }[]

/**
 * #32 실제·재생·모의 자료 구분 화면. 사용자가 자료 종류를 직접 고르며, 실패해도 다른 종류로 자동 전환하지 않는다.
 * 지금은 서버 읽기 경로가 없어(PR #42는 내부 모듈) 실제 조회·재생은 '연결 전'으로만 보여준다.
 */
export function ReferencePanel() {
  const [source, setSource] = useState<Source>('mock')
  const [caseId, setCaseId] = useState(cases[0].id)
  const picked = cases.find((c) => c.id === caseId)!

  return (
    <main>
      <section className="card reference" aria-labelledby="ref-title">
        <h2 id="ref-title">참고 자료 · HJNC 항차 반입 일정</h2>
        <p className="small muted">
          항차별 반입 시작·마감과 접안 예정(ETB)을 참고로 보여줍니다. 참고 자료는 배차 계산 입력이 아니며, 접안 예정 변화를 반입 마감 변경으로 바꾸지 않습니다.
        </p>
        <div className="tabs" role="radiogroup" aria-label="자료 종류">
          {([['live', '실제 현재 조회'], ['replay', '저장 자료 재생'], ['mock', '모의 시연']] as const).map(([id, label]) => (
            <button key={id} type="button" role="radio" aria-checked={source === id} aria-selected={source === id} onClick={() => setSource(id)}>{label}</button>
          ))}
        </div>

        {source !== 'mock' ? (
          <p className="warn small" role="status">
            {source === 'live' ? '실제 조회는' : '저장 자료 재생은'} 아직 연결되지 않았습니다. 서버의 읽기 경로가 생기기 전에는 결과를 보여주지 않으며, 모의 자료로 대신 채우지 않습니다.
          </p>
        ) : (
          <>
            <div className="banner fixture" role="note">모의(합성) 예제입니다. 실제 HJNC 응답이나 수신 기록이 아닙니다. 상태별 화면 표시를 확인하는 용도입니다.</div>
            <label className="small">
              모의 상태{' '}
              <select value={caseId} onChange={(e) => setCaseId(e.target.value)}>
                {cases.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
              </select>
            </label>
            <ReferenceStatus view={picked.view} />
          </>
        )}
      </section>
    </main>
  )
}

export function ReferenceStatus({ view: v }: { view: ReferenceView }) {
  const d = display(v)
  return (
    <div className="ref-status">
      <p className={`ref-headline tone-${d.tone}`} role="status">
        <span className="badge mode-simulated">{KIND_LABEL[v.kind]}</span> {d.headline}
      </p>
      <dl className="ref-meta small">
        <div><dt>최근 시도</dt><dd>{v.last_attempt ? `${kstDateTime(v.last_attempt.at)} · ${v.last_attempt.attempts}회` : '없음'}</dd></div>
        <div><dt>최근 성공 수신</dt><dd>{v.last_success ? `${kstDateTime(v.last_success.received_at)} · ${v.last_success.row_count}행` : '없음'}</dd></div>
        <div><dt>신선도 판단 시각</dt><dd>{kstDateTime(v.checked_at)}</dd></div>
      </dl>

      {d.sample && (
        <>
          {d.sample.status === 'partial' && (
            <p className="warn small">
              제공자가 알린 {d.sample.reported_count ?? '?'}건 중 {d.sample.row_count}건만 읽었습니다(제외 {d.sample.excluded_rows}건). 읽은 행만 참고로 표시합니다.
            </p>
          )}
          {d.sample.items.length ? (
            <table className="grid small">
              <caption className="small muted">
                {d.sampleIsPrevious ? '이전 수신 표본' : '이번 조회 표본'} · 수신 {kstDateTime(d.sample.received_at)} · 시각은 원문 그대로(시간대 미확인)
              </caption>
              <thead><tr><th scope="col">항차</th><th scope="col">반입 시작</th><th scope="col">반입 마감</th><th scope="col">접안 예정(ETB)</th><th scope="col">자료</th></tr></thead>
              <tbody>
                {d.sample.items.map((it, i) => (
                  <tr key={`${it.values.VOY_NO}:${i}`}>
                    <td>{it.values.VOY_NO}</td>
                    <td>{it.values.YARD_OPEN}</td>
                    <td>{it.values.YARD_CLOSE}</td>
                    <td>{it.values.ETB}</td>
                    <td>{KIND_LABEL[it.provenance.kind]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="small">제공자가 정상 응답으로 0건을 보냈습니다. 이전 자료를 대신 보여주지 않습니다.</p>
          )}
          {d.sample.blockers.length > 0 && (
            <ul className="small muted ref-blockers">
              {d.sample.blockers.map((b) => <li key={b}>{BLOCKER_LABEL[b] ?? b}</li>)}
            </ul>
          )}
        </>
      )}
      <p className="small muted">
        배차 계산 입력 변환: {v.engine_conversion === 'blocked' ? '막힘' : v.engine_conversion} · 승인 근거로 사용: {v.approval_eligible ? '가능' : '불가'} · 실패 시 모의 자동 전환: {v.automatic_mock_fallback ? '있음' : '없음'}
      </p>
    </div>
  )
}
