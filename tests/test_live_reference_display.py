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
