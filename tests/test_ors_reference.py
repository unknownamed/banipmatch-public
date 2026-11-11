import copy
import json
import pytest
from backend.references.ors import collect_ors, MAX_BYTES
from backend.references.display import Road


def sample():
    return {'durations': [[0, 600, 1200], [660, 0, 900], [1260, 960, 0]],
            'distances': [[0, 7000, 21000], [7100, 0, 14000], [22000, 14100, 0]],
            'sources': [{'snapped_distance': 207.23}, {'snapped_distance': 3.62}, {'snapped_distance': 1.69}],
            'destinations': [{'snapped_distance': 208.5}, {}, {'snapped_distance': 1.69}]}


def collect(raw):
    return collect_ors('secret-value-for-test', lambda *_: (200, json.dumps(raw).encode(), None))


def test_actual_matrix_directions_units_and_missing_snap_are_preserved():
    result = collect(sample())
    assert result['status'] == 'received'
    assert result['cells'][1]['duration_seconds'] == 600
    assert result['cells'][3]['duration_seconds'] == 660
    assert result['cells'][1]['distance_meters'] == 7000
    assert result['points'][0]['source_snap_m'] == 207.23
    assert result['points'][0]['destination_snap_m'] == 208.5
    assert result['points'][1]['destination_snap_m'] is None
    assert Road.model_validate(result).approval_eligible is False


def test_missing_key_does_not_request_and_null_route_never_becomes_zero():
    assert collect_ors(None, lambda *_: pytest.fail('no request without key'))['status'] == 'key_missing'
    raw = sample(); raw['durations'][0][1] = None
    result = collect(raw)
    assert result['status'] == 'partial'
    assert result['cells'][1]['duration_seconds'] is None
    assert result['cells'][3]['duration_seconds'] == 660
    assert result['cells'][0]['duration_seconds'] == 0


@pytest.mark.parametrize('bad', [True, -1, float('inf'), float('nan'), '600'])
def test_invalid_numbers_are_not_guessed(bad):
    raw = sample(); raw['durations'][0][1] = bad
    result = collect(raw)
    assert result['status'] == 'invalid_response'
    assert result['cells'] == []


@pytest.mark.parametrize('code,expected', [(401,'auth_error'),(403,'auth_error'),(429,'rate_limited'),(503,'http_error'),(302,'http_error')])
def test_provider_errors_are_not_retried_echoed_or_replaced(code, expected):
    calls = []
    def transport(key, payload):
        calls.append(payload)
        return code, b'secret-value-for-test', '12'
    result = collect_ors('secret-value-for-test', transport)
    assert result['status'] == expected
    assert len(calls) == 1
    assert result['cells'] == []
    assert result['retry_after_seconds'] == (12 if code == 429 else None)
    assert 'secret-value-for-test' not in json.dumps(result)


def test_wrong_shape_oversize_secret_reflection_and_public_projection():
    raw = sample(); raw['distances'][0].pop()
    assert collect(raw)['status'] == 'invalid_response'
    for body in [b'x'*(MAX_BYTES+1), b'{"echo":"secret-value-for-test"}']:
        assert collect_ors('secret-value-for-test', lambda *_:(200,body,None))['status'] == 'invalid_response'
    result = collect(sample()); result['raw_key']='do-not-serve'
    assert 'do-not-serve' not in Road.model_validate(result).model_dump_json()
    forged=copy.deepcopy(result); forged['realtime_traffic']=True
    with pytest.raises(ValueError): Road.model_validate(forged)
