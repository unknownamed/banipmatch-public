"""AISstream 1회·소량 수신 시험. 키·선박 식별자·위치 원본을 출력/저장하지 않음."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
import getpass
import math
import os
import sys
from pathlib import Path

ENDPOINT = "wss://stream.aisstream.io/v0/stream"
MESSAGE_TYPES = ("PositionReport", "ShipStaticData", "StaticDataReport")
# 수신 시험용 사각형이며 공식 항계·수신 커버리지의 증거가 아님.
BUSAN_TRIAL_BOX = (35.00, 128.72, 35.13, 128.90)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_box(value):
    try:
        south, west, north, east = map(float, value.split(','))
        if not all(math.isfinite(v) for v in (south, west, north, east)):
            raise ValueError
        if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
            raise ValueError
        if north - south > 0.5 or east - west > 0.5:
            raise ValueError
        return south, west, north, east
    except ValueError:
        raise argparse.ArgumentTypeError("bbox는 작은 해역의 south,west,north,east여야 함") from None


class Audit:
    def __init__(self, box):
        self.box = box
        self.counts = Counter()
        self.positions, self.statics = set(), set()
        self.valid_mmsi = self.invalid_mmsi = 0
        self.valid_positions = self.invalid_positions = self.outside = 0
        self.invalid_identity = self.invalid_statics = 0
        self.provider_time_missing = self.provider_time_invalid = 0
        self.provider_age = []
        self.compression_confirmed = None
        self.subscription_confirmed = False

    def consume(self, event, received_at):
        if not isinstance(event, dict):
            raise ValueError("invalid envelope")
        if 'error' in event or 'Error' in event or event.get('MessageType') in {'Error', 'error'}:
            return False
        kind = event.get('MessageType')
        if kind == 'SubscriptionConfirmation':
            self.subscription_confirmed = True
            message = event.get('Message', {})
            if isinstance(message, dict):
                enabled = message.get('CompressionEnabled')
                self.compression_confirmed = enabled if isinstance(enabled, bool) else None
            return True
        if kind not in MESSAGE_TYPES:
            self.counts['other'] += 1
            return True
        self.counts[kind] += 1
        meta = event.get('MetaData') or {}
        payload = event.get('Message') or {}
        if not isinstance(meta, dict) or not isinstance(payload, dict):
            raise ValueError("invalid envelope")
        mmsi = str(meta.get('MMSI', ''))
        valid_id = len(mmsi) == 9 and mmsi.isascii() and mmsi.isdigit()
        if valid_id:
            self.valid_mmsi += 1
        else:
            self.invalid_mmsi += 1
        body = payload.get(kind) or {}
        if not isinstance(body, dict):
            raise ValueError("invalid message body")
        identity_matches = (valid_id and type(body.get('UserID')) is int
                            and body['UserID'] == int(mmsi))
        if not identity_matches:
            self.invalid_identity += 1
        if kind != 'PositionReport':
            if identity_matches and body.get('Valid') is True:
                self.statics.add(mmsi)
            else:
                self.invalid_statics += 1
            return True
        position = body
        lat, lon = position.get('Latitude'), position.get('Longitude')
        numeric = lambda x: type(x) in (float, int) and math.isfinite(x)
        if not identity_matches or position.get('Valid') is not True or not numeric(lat) or not numeric(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            self.invalid_positions += 1
        else:
            self.valid_positions += 1
            self.positions.add(mmsi)
            south, west, north, east = self.box
            self.outside += not (south <= lat <= north and west <= lon <= east)
        # AIS Timestamp는 분 안의 초 값이므로 날짜·전체 관측시각을 추정하지 않음.
        supplied = meta.get('time_utc')
        if not supplied:
            self.provider_time_missing += 1
        else:
            try:
                moment = datetime.fromisoformat(str(supplied).removesuffix(' UTC').replace('Z', '+00:00'))
                if moment.tzinfo is None:
                    raise ValueError
                self.provider_age.append((received_at - moment).total_seconds())
            except (ValueError, TypeError):
                self.provider_time_invalid += 1
        return True

    def summary(self):
        ages = self.provider_age
        return {'message_counts': dict(self.counts), 'valid_mmsi_events': self.valid_mmsi,
                'invalid_mmsi_events': self.invalid_mmsi, 'unique_position_mmsi_count': len(self.positions),
                'position_static_join_count': len(self.positions & self.statics),
                'valid_position_events': self.valid_positions, 'invalid_position_events': self.invalid_positions,
                'invalid_identity_events': self.invalid_identity, 'invalid_static_events': self.invalid_statics,
                'outside_trial_box_events': self.outside,
                'provider_time_missing': self.provider_time_missing, 'provider_time_invalid': self.provider_time_invalid,
                'provider_time_age_seconds_min': min(ages) if ages else None,
                'provider_time_age_seconds_max': max(ages) if ages else None,
                'provider_time_future_events': sum(age < 0 for age in ages),
                'subscription_confirmed': self.subscription_confirmed,
                'compression_confirmed': self.compression_confirmed}


async def probe(key, *, box=BUSAN_TRIAL_BOX, seconds=45, max_messages=50, connector=None):
    if not key or not key.strip() or not 1 <= seconds <= 120 or not 1 <= max_messages <= 100:
        raise ValueError("key or bounds missing")
    parse_box(','.join(map(str, box)))
    if connector is None:
        from websockets.asyncio.client import connect
        connector = connect
    audit = Audit(box)
    summary = {'source': 'aisstream.io', 'started_at': utc_now(), 'trial_bbox': list(box),
               'max_seconds': seconds, 'max_messages': max_messages, 'connection_attempts': 1,
               'status': 'not_connected', 'connection_closed': False,
               'provider_time_semantics': 'MetaData.time_utc 의미 미확인. 관측시각으로 확정하지 않음',
               'voyage_link_verified': False, 'raw_events_saved': False, 'usage_rights': '미확인'}
    socket = None
    try:
        async with connector(ENDPOINT, compression='deflate', proxy=None, open_timeout=10,
                             close_timeout=3, max_size=65536, max_queue=16) as socket:
            if socket.request is None or socket.request.headers.get('Host') != 'stream.aisstream.io':
                raise ValueError('unexpected subscription destination')
            south, west, north, east = box
            await asyncio.wait_for(socket.send(json.dumps({'APIKey': key.strip(),
                'BoundingBoxes': [[[south, west], [north, east]]], 'FilterMessageTypes': list(MESSAGE_TYPES)})), timeout=2)
            summary['status'] = 'no_messages'
            deadline = asyncio.get_running_loop().time() + seconds
            for _ in range(max_messages):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
                except TimeoutError:
                    break
                if not audit.consume(json.loads(raw), datetime.now(timezone.utc)):
                    summary['status'] = 'provider_error'
                    break
                if sum(audit.counts.values()):
                    summary['status'] = 'messages_received'
    except Exception as error:
        # 제공사 오류·종료 사유가 키를 반사할 수 있으므로 원문을 남기지 않음.
        summary['status'] = 'connection_or_payload_error'
        summary['error_type'] = type(error).__name__
    finally:
        summary['connection_closed'] = socket is not None and socket.close_code is not None
        summary['finished_at'] = utc_now()
        summary.update(audit.summary())
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-file', type=Path, help='Git 제외된 로컬 키 파일. 키 값 자체를 인수로 전달하지 않음')
    parser.add_argument('--prompt-key', action='store_true', help='터미널에서 키를 숨겨 입력. 명령행·파일에 저장하지 않음')
    parser.add_argument('--seconds', type=int, choices=range(1, 121), default=45)
    parser.add_argument('--max-messages', type=int, choices=range(1, 101), default=50)
    parser.add_argument('--bbox', type=parse_box, default=BUSAN_TRIAL_BOX)
    parser.add_argument('--output', type=Path, help='집계만 저장할 새 로컬 JSON')
    args = parser.parse_args(argv)
    stream = None
    try:
        key = args.key_file.read_text(encoding='utf-8-sig').strip() if args.key_file else os.getenv('AISSTREAM_API_KEY', '').strip()
        if args.prompt_key:
            if not sys.stdin.isatty():
                raise ValueError('interactive terminal required')
            key = getpass.getpass('AIS API key (hidden): ').strip()
        if not key:
            print(json.dumps({'status': 'key_missing', 'connection_attempts': 0}))
            return 2
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            stream = args.output.open('x', encoding='utf-8')
        result = asyncio.run(probe(key, box=args.bbox, seconds=args.seconds, max_messages=args.max_messages))
        encoded = json.dumps(result, ensure_ascii=True, indent=2)
        if stream:
            stream.write(encoded + '\n')
        print(encoded)
        confirmed = result['subscription_confirmed'] or any(result['message_counts'].get(kind) for kind in MESSAGE_TYPES)
        return 0 if result['status'] in {'messages_received', 'no_messages'} and result['connection_closed'] and confirmed else 1
    except Exception as error:
        print(json.dumps({'status': 'local_setup_failed', 'error_type': type(error).__name__}))
        return 1
    finally:
        if stream:
            stream.close()


if __name__ == '__main__':
    raise SystemExit(main())
