from concurrent.futures import ThreadPoolExecutor

from test_workflow_api import ORIGIN, new_manager, seed, workflow


def test_sixty_visitors_behind_one_ip_remain_isolated_and_admission_is_bounded(workflow):
    client, _, _ = workflow
    visitors = [new_manager(client) for _ in range(60)]
    assert len({actor.info['session_id'] for actor in visitors}) == 60
    denied = client.post('/v2/session', headers={'Origin': ORIGIN, 'Cookie': ''})
    assert denied.status_code == 429 and denied.json()['code'] == 'RATE_LIMITED'
    snapshot = seed(visitors[0])
    path = '/v2/scenarios/' + snapshot['scenario_id']
    with ThreadPoolExecutor(max_workers=10) as workers:
        codes = list(workers.map(lambda actor: actor.get(path).status_code, visitors))
    assert codes == [200] + [404] * 59
    assert all(actor.get('/v2/session').status_code == 200 for actor in visitors)


def _fill_registry(config, count, *, expired):
    import sqlite3
    from datetime import datetime, timedelta, timezone
    at = datetime.now(timezone.utc) + (timedelta(hours=-2) if expired else timedelta(hours=20))
    stamp = at.strftime('%Y-%m-%dT%H:%M:%SZ')
    with sqlite3.connect(config.workflow_dir / 'registry.sqlite3') as conn:
        conn.executemany(
            "INSERT INTO sessions(session_id,token_hash,created_at,expires_at,ready,revoked) VALUES(?,?,?,?,1,?)",
            [(f'{i + (10**6 if expired else 0):032x}', f'h{expired}{i}', stamp, stamp, 1 if expired else 0) for i in range(count)])


def test_expired_sessions_kept_for_retention_do_not_block_new_visitors(workflow):
    # 만료 세션은 기록 보존을 위해 7일 남는다. 그 수가 많아도 새 방문자는 들어와야 한다.
    client, _, config = workflow
    new_manager(client)
    _fill_registry(config, 250, expired=True)
    assert new_manager(client).info['session_id']


def test_active_sessions_are_still_capped(workflow):
    client, _, config = workflow
    new_manager(client)
    _fill_registry(config, 200, expired=False)
    denied = client.post('/v2/session', headers={'Origin': ORIGIN, 'Cookie': ''})
    assert denied.status_code == 429 and denied.json()['code'] == 'SESSION_LIMIT'
