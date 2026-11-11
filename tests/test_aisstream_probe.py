import asyncio
import argparse
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools.probe_aisstream import Audit, BUSAN_TRIAL_BOX, ENDPOINT, main, parse_box, probe


class Socket:
    def __init__(self, events, host='stream.aisstream.io'):
        self.events = list(events)
        self.sent = []
        self.close_code = None
        self.request = SimpleNamespace(headers={'Host': host})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.close_code = 1000

    async def send(self, value):
        self.sent.append(json.loads(value))

    async def recv(self):
        if not self.events:
            raise TimeoutError
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return json.dumps(event).encode()


def position():
    return {'MessageType': 'PositionReport',
            'MetaData': {'MMSI': 123456789, 'time_utc': '2026-11-10T00:00:00Z', 'ShipName': 'not-for-output'},
            'Message': {'PositionReport': {'UserID': 123456789, 'Valid': True, 'Latitude': 35.07, 'Longitude': 128.80, 'Timestamp': 23}}}


def static():
    return {'MessageType': 'ShipStaticData', 'MetaData': {'MMSI': 123456789},
            'Message': {'ShipStaticData': {'UserID': 123456789, 'Valid': True}}}


def test_probe_is_bounded_closes_and_keeps_only_counts():
    sock = Socket([{'MessageType': 'SubscriptionConfirmation', 'Message': {'CompressionEnabled': True}},
                   position(), static()])
    calls = []
    def connect(url, **kwargs):
        calls.append((url, kwargs))
        return sock
    result = asyncio.run(probe('private-test-key', max_messages=3, connector=connect))
    assert len(calls) == 1 and calls[0][0] == ENDPOINT
    assert calls[0][1]['compression'] == 'deflate' and calls[0][1]['proxy'] is None
    assert len(sock.sent) == 1 and sock.sent[0]['APIKey'] == 'private-test-key'
    assert result['status'] == 'messages_received' and result['connection_closed']
    assert result['position_static_join_count'] == 1 and result['valid_position_events'] == 1
    assert result['subscription_confirmed'] and result['compression_confirmed']
    encoded = json.dumps(result)
    assert all(secret not in encoded for secret in ('private-test-key', '123456789', 'not-for-output', '35.07'))


@pytest.mark.parametrize('event', [{'error': 'private-test-key'}, RuntimeError('private-test-key'), {'MessageType': 'Error', 'detail': 'private-test-key'}])
def test_provider_failures_never_echo_key_and_always_close(event):
    sock = Socket([event])
    result = asyncio.run(probe('private-test-key', connector=lambda *a, **k: sock))
    assert result['status'] in {'provider_error', 'connection_or_payload_error'}
    assert result['connection_closed']
    assert 'private-test-key' not in json.dumps(result)


def test_redirected_connection_never_receives_key():
    sock = Socket([], host='other.example')
    result = asyncio.run(probe('private-test-key', connector=lambda *a, **k: sock))
    assert not sock.sent
    assert result['status'] == 'connection_or_payload_error' and result['connection_closed']


def test_zero_messages_is_not_proof_of_no_ships_or_successful_subscription():
    sock = Socket([])
    result = asyncio.run(probe('test-key', connector=lambda *a, **k: sock))
    assert result['status'] == 'no_messages' and not result['subscription_confirmed']
    assert result['message_counts'] == {} and result['connection_closed']


def test_position_validation_and_ambiguous_time_are_not_filled():
    audit = Audit(BUSAN_TRIAL_BOX)
    event = position()
    event['Message']['PositionReport']['Latitude'] = 91
    event['MetaData'].pop('time_utc')
    audit.consume(event, datetime.now(timezone.utc))
    assert audit.summary()['invalid_position_events'] == 1
    assert audit.summary()['provider_time_missing'] == 1
    assert audit.summary()['provider_time_age_seconds_min'] is None


@pytest.mark.parametrize('field,value', [('UserID', 987654321), ('UserID', None),
                                       ('UserID', True), ('Valid', False), ('Latitude', 91)])
def test_invalid_position_never_counts_as_a_joined_ship(field, value):
    audit = Audit(BUSAN_TRIAL_BOX)
    event = position()
    event['Message']['PositionReport'][field] = value
    audit.consume(event, datetime.now(timezone.utc))
    audit.consume(static(), datetime.now(timezone.utc))
    result = audit.summary()
    assert result['valid_position_events'] == 0
    assert result['invalid_position_events'] == 1
    assert result['unique_position_mmsi_count'] == 0
    assert result['position_static_join_count'] == 0


@pytest.mark.parametrize('change', ['mismatch', 'missing_body', 'invalid'])
def test_invalid_static_never_proves_a_position_static_join(change):
    audit = Audit(BUSAN_TRIAL_BOX)
    event = static()
    if change == 'missing_body':
        event.pop('Message')
    elif change == 'mismatch':
        event['Message']['ShipStaticData']['UserID'] = 987654321
    else:
        event['Message']['ShipStaticData']['Valid'] = False
    audit.consume(position(), datetime.now(timezone.utc))
    audit.consume(event, datetime.now(timezone.utc))
    result = audit.summary()
    assert result['valid_position_events'] == 1
    assert result['position_static_join_count'] == 0
    assert result['invalid_static_events'] == 1


@pytest.mark.parametrize('box', ['nan,128,35,129', '35,128,34,129', '0,0,60,60'])
def test_large_or_invalid_boxes_rejected(box):
    with pytest.raises(argparse.ArgumentTypeError):
        parse_box(box)


def test_key_missing_never_connects(monkeypatch):
    monkeypatch.delenv('AISSTREAM_API_KEY', raising=False)
    with patch('tools.probe_aisstream.probe') as connect:
        assert main([]) == 2
        connect.assert_not_called()


def test_existing_output_preserved_before_connect(tmp_path, monkeypatch):
    output = tmp_path / 'summary.json'
    output.write_text('original', encoding='utf-8')
    monkeypatch.setenv('AISSTREAM_API_KEY', 'private-test-key')
    with patch('tools.probe_aisstream.probe') as connect:
        assert main(['--output', str(output)]) == 1
        connect.assert_not_called()
    assert output.read_text(encoding='utf-8') == 'original'


def test_prompt_never_falls_back_to_echoing_key(monkeypatch):
    monkeypatch.delenv('AISSTREAM_API_KEY', raising=False)
    with patch('tools.probe_aisstream.sys.stdin.isatty', return_value=False), patch('tools.probe_aisstream.getpass.getpass') as prompt:
        assert main(['--prompt-key']) == 1
        prompt.assert_not_called()
