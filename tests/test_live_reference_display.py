from datetime import datetime, timedelta, timezone
import json
import pytest
from backend.references.display import read_display
from backend.api.contracts import ApiError
from tools.collect_live_reference import collect
from tools.build_fleet_replay import build


def test_live_failure_is_preserved_and_credentials_not_projected(tmp_path):
    calls = []
    def transport(url):
        calls.append(url)
        if 'hjnc' in url: return 503, b''
        return 403, b'provider error'
    result = collect('test-key-not-real', transport)
    assert len(calls) == 3
    result['api_key'] = 'must-not-be-served'
    result['weather'][0]['report']['raw_url'] = 'must-not-be-served'
    p = tmp_path/'snapshot.json'
    p.write_text(json.dumps(result), encoding='utf-8')
    public = read_display(p).model_dump_json()
    assert 'must-not-be-served' not in public
    assert 'test-key-not-real' not in public
    assert read_display(p).hjnc.last_attempt.status == 'failed'
    assert all(w.status == 'http_error' for w in read_display(p).weather)
    with pytest.raises(ApiError): read_display(None)


def test_actual_reference_schema_does_not_allow_synthetic_disguised_as_actual(tmp_path):
    result = collect(None, lambda _: (503,b''))
    result['kind'] = 'simulated'
    p=tmp_path/'snapshot.json'; p.write_text(json.dumps(result),encoding='utf-8')
    with pytest.raises(ApiError): read_display(p)


def test_busans_synthetic_fleet_wire_replay_is_reproducible_and_stale_stops():
    view, wire = build()
    assert (view,wire) == build()
    assert len(view['frames'])==61
    assert len(view['frames'][-1]['ships'])==12
    assert len(wire)==671
    last=view['frames'][-1]
    assert last['rejected']==0
    assert sum(s['position_status']=='stale' for s in last['ships'])==2
    assert sum(s['name'] is None for s in last['ships'])==1
    for s in last['ships']:
        assert s['position']['latitude']>=35 and s['position']['latitude']<=35.13
        assert 128.72 <= s['position']['longitude'] <=128.90
        if s['position_status']=='stale':
            at_loss=next(x for x in view['frames'][24]['ships'] if x['mmsi']==s['mmsi'])
            assert s['position']==at_loss['position']


def test_failed_collection_keeps_last_good_reference_for_demo(tmp_path):
    good = collect(None, lambda _: (503, b''))
    # 직전 수집이 성공했다고 가정한 자료(HJNC 표본 1건, 해상 관측 정상)를 만든다.
    raw = json.dumps({"stringContent": json.dumps([{"VOY_NO": "TEST-2026-0001", "YARD_OPEN": "2026-11-10 00:00",
                      "YARD_CLOSE": "2026-11-13 01:00", "ETB": "2026-11-13 11:00"}]), "totalElements": 1, "hasNext": False}).encode()
    previous = collect(None, lambda url: (200, raw) if 'hjnc' in url else (503, b''))
    assert previous['hjnc']['last_attempt']['status'] == 'received'
    previous['weather'] = [{'source': '기상청 API허브', 'kind': 'sea', 'source_ref': 'x', 'status': 'sample_received',
                            'received_at': '2026-11-12T15:26:41Z', 'http_status': 200, 'report': None}]
    calls = []
    def down(url):
        calls.append(url)
        return 0, b''  # 연결 실패
    after = collect('test-key-not-real', down, previous=previous)
    assert after['hjnc']['current'] == previous['hjnc']['current']       # 일정 유지
    assert after['hjnc']['last_attempt']['status'] == 'failed'           # 실패 시도는 기록
    sea = next(w for w in after['weather'] if w['kind'] == 'sea')
    assert sea['status'] == 'sample_received' and sea['failure'] == 'network'
    warning = next(w for w in after['weather'] if w['kind'] == 'warning')
    assert warning['failure'] == 'network' and warning['http_status'] is None
    p = tmp_path / 'snapshot.json'
    p.write_text(json.dumps(after), encoding='utf-8')
    assert read_display(p).hjnc.current is not None


def test_only_kma_does_not_call_hjnc_and_keeps_schedule():
    raw = json.dumps({"stringContent": json.dumps([{"VOY_NO": "TEST-2026-0001", "YARD_OPEN": "2026-11-10 00:00",
                      "YARD_CLOSE": "2026-11-13 01:00", "ETB": "2026-11-13 11:00"}]), "totalElements": 1, "hasNext": False}).encode()
    previous = collect(None, lambda url: (200, raw) if 'hjnc' in url else (503, b''))
    calls = []
    def transport(url):
        calls.append(url)
        return 503, b''
    after = collect('test-key-not-real', transport, only='kma', previous=previous)
    assert not any('hjnc' in u for u in calls) and len(calls) == 2
    assert after['hjnc'] == previous['hjnc']
