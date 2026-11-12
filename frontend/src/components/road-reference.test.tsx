// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { expect, it } from 'vitest'
import { RoadReference, type RoadData } from './RoadReference'

it('실제 경로 수치의 단위·방향·누락과 호출 실패를 구분한다', async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  const box=document.createElement('div'); const root=createRoot(box)
  const road: RoadData={status:'partial',received_at:'2026-11-11T10:00:00Z',http_status:200,retry_after_seconds:null,
    points:['A','B'].map(label=>({label,longitude:128.8,latitude:35.1,source_snap_m:207.23,destination_snap_m:null})),
    cells:[{origin:0,destination:0,duration_seconds:0,distance_meters:0},{origin:0,destination:1,duration_seconds:600,distance_meters:7000},
      {origin:1,destination:0,duration_seconds:660,distance_meters:7100},{origin:1,destination:1,duration_seconds:null,distance_meters:null}]}
  await act(async()=>root.render(<RoadReference road={road}/>))
  expect(box.textContent).toContain('10분 7.0km')
  expect(box.textContent).toContain('11분 7.1km')
  expect(box.textContent).toContain('자료 없음')
  expect(box.textContent).toContain('실시간 교통 미반영')
  expect(box.textContent).toContain('207.2m / 도착 미확인')
  await act(async()=>root.render(<RoadReference road={{...road,status:'rate_limited',http_status:429,retry_after_seconds:12,cells:[],points:[]}}/>))
  expect(box.textContent).toContain('서버 안내 대기 12초')
  expect(box.textContent).not.toContain('10분 7.0km')
  await act(async()=>root.unmount())
})
