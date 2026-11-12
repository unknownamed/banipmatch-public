from concurrent.futures import ThreadPoolExecutor

from test_workflow_api import ORIGIN, new_manager, seed, workflow


def test_twenty_visitors_behind_one_ip_remain_isolated_and_admission_is_bounded(workflow):
    client, _, _ = workflow
    visitors = [new_manager(client) for _ in range(20)]
    assert len({actor.info['session_id'] for actor in visitors}) == 20
    denied = client.post('/v2/session', headers={'Origin': ORIGIN, 'Cookie': ''})
    assert denied.status_code == 429 and denied.json()['code'] == 'RATE_LIMITED'
    snapshot = seed(visitors[0])
    path = '/v2/scenarios/' + snapshot['scenario_id']
    with ThreadPoolExecutor(max_workers=10) as workers:
        codes = list(workers.map(lambda actor: actor.get(path).status_code, visitors))
    assert codes == [200] + [404] * 19
    assert all(actor.get('/v2/session').status_code == 200 for actor in visitors)
