"""재시험 전용 실행기. 현재 실행 결과만 기록하며 업무 코드는 바꾸지 않는다."""
import asyncio
import importlib.util
import json
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx

sys.path.insert(0, '/app')
spec = importlib.util.spec_from_file_location('base', '/tests/full-e2e.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


async def section(name, action):
    try:
        await action()
    except Exception as exc:
        # 후속 독립 시험은 계속하되 이 구간이 완료되지 않았음을 결과에 남긴다.
        b.record('시험 구간 중단 ' + name, False, type(exc).__name__ + ': ' + str(exc)[:180])


async def financial(users):
    sender, receiver, _ = users
    before = (await b.CLIENT.get('http://fault-proxy:18081/__control')).json()['transfer_posts']
    retry = await b.transfer(sender, receiver, 'e2e-first')
    after = (await b.CLIENT.get('http://fault-proxy:18081/__control')).json()['transfer_posts']
    b.record('완료 거래 재요청 Mock 호출 추가 없음', retry[0] == 200 and retry[1]['transferId'] == sender['transfer'] and before == after,
             f'Mock POST 횟수 before={before}, after={after}')
    before = after
    results = await asyncio.gather(*(b.transfer(sender, receiver, 'race-verified', 1) for _ in range(12)))
    after = (await b.CLIENT.get('http://fault-proxy:18081/__control')).json()['transfer_posts']
    rows = await b.query('banking', "select transfer_id,status from banking_transfer where idempotency_key='race-verified'")
    b.record('같은 키 동시 12건 DB 1행·Mock 1회', len(rows) == 1 and after - before == 1 and
             all(r[0] == 200 and r[1].get('transferId') == str(rows[0]['transfer_id']) for r in results),
             f'DB행={len(rows)}, Mock POST 증가={after-before}, HTTP상태={[r[0] for r in results]}')
    changed = await b.request('POST', '/api/v1/banking/transfers', sender, {
        'withdrawalAccountId': sender['account'], 'depositBankCode': '001',
        'depositAccountNumber': 'different-test-destination', 'amount': 10000}, {'Idempotency-Key': 'e2e-first'})
    b.record('같은 키 다른 수취계좌 거절', changed[0] == 409, f'HTTP={changed[0]}')
    txs = await b.query('banking', 'select status,principal_id from banking_transfer')
    b.record('JWT sub가 모든 거래 principal_id로 저장', bool(txs) and all(str(t['principal_id']) == sender['id'] for t in txs),
             f'금융거래 행={len(txs)}; body 사용자 ID는 인증 근거로 사용하지 않음')


async def rpc(users):
    import grpc
    from app.grpc.asset_client import AssetClient, BalanceStatus, load_channel_credentials
    from app.grpc import asset_service_pb2 as pb, asset_service_pb2_grpc as stubs
    for user in users[:2]:
        await b.account_detail(user, True)
        expected = Decimal(str((await b.account_detail(user))[1]['balance']))
        result = await AssetClient().get_current_balance(int(user['id']))
        b.record('실제 mTLS 잔액 RPC ' + user['id'], result.status == BalanceStatus.OK and result.amount == expected,
                 f'RPC잔액={result.amount}, HTTP잔액={expected}')
    async with grpc.aio.secure_channel('asset:9090', load_channel_credentials()) as channel:
        stub = stubs.AssetServiceStub(channel)
        for uid, wanted in [('', grpc.StatusCode.INVALID_ARGUMENT), (users[2]['id'], grpc.StatusCode.FAILED_PRECONDITION)]:
            try:
                await stub.GetCurrentBalance(pb.GetCurrentBalanceRequest(user_id=uid), timeout=5)
                b.record('잔액 RPC 예외 ' + (uid or '빈ID'), False, '예외 없이 응답')
            except grpc.aio.AioRpcError as exc:
                b.record('잔액 RPC 예외 ' + (uid or '빈ID'), exc.code() == wanted, exc.code().name)
        r = await stub.GetDailyCashflow(pb.GetDailyCashflowRequest(user_id=users[0]['id'],
            days_until_next_payday=10, snapshot_date=str(date.today())), timeout=5)
        expected = Decimal(str((await b.account_detail(users[0]))[1]['balance']))
        b.record('일별 계산 RPC 잔액 일치', Decimal(r.current_balance.amount) == expected,
                 f'current_balance={r.current_balance.amount}, daily_limit={r.daily_limit.amount}')
    await b.call('Auth 타인 계좌 토큰 생성 차단', 'POST', '/api/v1/auth/account-token', users[0],
        {'user_id': int(users[1]['id']), 'account_number': 'E2E-OTHER-FAKE'}, want=403)


async def replay(users):
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
    from app.grpc.events import asset_events_pb2 as events
    sender = users[0]
    producer = AIOKafkaProducer(bootstrap_servers='kafka:29092')
    reader = AIOKafkaConsumer(bootstrap_servers='kafka:29092', group_id=None, enable_auto_commit=False)
    await producer.start()
    await reader.start()
    async def committed(metadata, group):
        monitor = AIOKafkaConsumer(bootstrap_servers='kafka:29092', group_id=group, enable_auto_commit=False)
        await monitor.start()
        try:
            until = time.monotonic() + 45
            while time.monotonic() < until:
                offset = await monitor.committed(TopicPartition(metadata.topic, metadata.partition))
                if offset is not None and offset > metadata.offset:
                    return
                await asyncio.sleep(.25)
            raise TimeoutError('Consumer offset 대기 만료: ' + group)
        finally:
            await monitor.stop()
    try:
        # Banking DB의 실제 Outbox 본문을 재발행한다. 가상의 성공 거래를 만들지 않는다.
        row = (await b.query('banking', 'select event_id,payload,topic,message_key from banking_outbox where aggregate_id=%s',
                            (str(sender['transfer']),)))[0]
        before = await b.query('asset', 'select balance from account where id=%s', (sender['account'],))
        metadata = await producer.send_and_wait(row['topic'], value=row['payload'], key=row['message_key'].encode())
        await committed(metadata, 'moaje-asset')
        # 공통 계약에서 생성한 Python 클래스로 실제 본문을 읽고 eventId만 변경한다.
        sys.path.insert(0, '/tmp/e2e-gen')
        from events.banking_events_pb2 import BankingTransferCompletedEvent
        banking_event = BankingTransferCompletedEvent.FromString(row['payload'])
        banking_event.event_id = 'E2E-BANKING-CHANGED-ID'
        changed = banking_event.SerializeToString()
        metadata = await producer.send_and_wait(row['topic'], value=changed, key=row['message_key'].encode())
        await committed(metadata, 'moaje-asset')
        after = await b.query('asset', 'select balance from account where id=%s', (sender['account'],))
        history = await b.query('asset', 'select count(*) n from transaction_history where banking_transfer_id=%s and account_id=%s',
                                (sender['transfer'], sender['account']))
        b.record('Asset 동일·다른 eventId 중복 소비', before == after and history[0]['n'] == 1,
                 f'잔액 before={before}, after={after}; 내부 거래 연결 행={history[0]["n"]}; 소비 offset 확인')
        topic = 'transaction_succeeded_events'
        reader.assign([TopicPartition(topic, p) for p in reader.partitions_for_topic(topic)])
        await reader.seek_to_beginning()
        batch = await reader.getmany(timeout_ms=2000, max_records=1000)
        messages = [m for records in batch.values() for m in records]
        original_record = next(m for m in messages if events.TransactionSucceededEvent.FromString(m.value).user_id == sender['id'])
        count_before = (await b.query('work', 'select count(*) n from fds_inference_log where user_id=%s', (sender['id'],)))[0]['n']
        await producer.send_and_wait(topic, value=original_record.value, key=original_record.key)
        event = events.TransactionSucceededEvent.FromString(original_record.value)
        event.event_id = 'E2E-RERUN-CHANGED-ID'
        metadata = await producer.send_and_wait(topic, value=event.SerializeToString(), key=original_record.key)
        await committed(metadata, 'moaje-work')
        count_after = (await b.query('work', 'select count(*) n from fds_inference_log where user_id=%s', (sender['id'],)))[0]['n']
        b.record('Work 동일·다른 eventId 중복 소비', count_before == count_after,
                 f'처리행 before={count_before}, after={count_after}; 소비 offset 확인')
        # 현재 집계 revision보다 낮은 수정 이벤트를 보내도 최신 집계는 유지되어야 한다.
        rows = await b.query('work', 'select `year_month`,revision,total_expense from monthly_cashflow where user_id=%s and revision>1', (sender['id'],))
        if rows:
            r = rows[0]
            event = events.MonthlyCashflowAggregatedEvent(event_id='E2E-RERUN-OLD-REV', user_id=sender['id'],
                year_month=r['year_month'], revision=r['revision']-1, calculated_at='2026-10-10T00:00:00Z')
            metadata = await producer.send_and_wait('moaje.asset.monthly-cashflow-aggregated', value=event.SerializeToString(), key=sender['id'].encode())
            await committed(metadata, 'moaje-work')
            after = await b.query('work', 'select `year_month`,revision,total_expense from monthly_cashflow where user_id=%s and year_month=%s', (sender['id'], r['year_month']))
            b.record('Work 낮은 revision 무시', after == [r], str(after))
    finally:
        await reader.stop()
        await producer.stop()


async def outage(users, verify=False):
    sender, receiver, _ = users
    if not verify:
        code, result = await b.transfer(sender, receiver, 'e2e-kafka-down', 7)
        sender['outageTransfer'] = result['transferId']
        b.STATE.write_text(json.dumps(users), encoding='utf-8')
        b.record('Kafka 중단 중 금융 성공', code == 200 and result['status'] == 'COMPLETED', f'HTTP={code}, status={result.get("status")}')
        rows = await b.poll(lambda: b.query('banking', 'select status,event_id,attempt_count,next_attempt_at from banking_outbox where aggregate_id=%s',
            (str(result['transferId']),)), lambda x: x and x[0]['attempt_count'] >= 1, 35)
        b.record('Kafka 중단 Outbox 보존·재시도 기록', rows and rows[0]['status'] == 'PENDING' and rows[0]['attempt_count'] >= 1 and rows[0]['next_attempt_at'], str(rows))
        sender['outageEvent'] = rows[0]['event_id']
        b.STATE.write_text(json.dumps(users), encoding='utf-8')
    else:
        rows = await b.poll(lambda: b.query('banking', 'select status,event_id,attempt_count from banking_outbox where aggregate_id=%s',
            (str(sender['outageTransfer']),)), lambda x: x and x[0]['status'] == 'PUBLISHED', 80)
        b.record('Kafka 복구 같은 eventId 발행', rows and rows[0]['status'] == 'PUBLISHED' and rows[0]['event_id'] == sender['outageEvent'], str(rows))
        rows = await b.poll(lambda: b.query('asset', 'select count(*) n from transaction_history where banking_transfer_id=%s and account_id=%s',
            (sender['outageTransfer'], sender['account'])), lambda x: x[0]['n'] == 1, 60)
        b.record('Kafka 복구 Asset 반영 1건', rows and rows[0]['n'] == 1, str(rows))


async def final(users):
    from app.grpc.asset_client import AssetClient, BalanceStatus
    sender, receiver, _ = users
    status, _ = await b.mock('DELETE', '/api/accounts/' + receiver['number'], receiver)
    b.record('Mock 계좌 해지', status == 200, f'HTTP={status}')
    await b.account_detail(receiver, True)
    balance = await AssetClient().get_current_balance(int(receiver['id']))
    b.record('CLOSED 계좌 잔액 합산 제외', balance.status == BalanceStatus.NOT_LINKED, balance.status.name)
    await b.call('CLOSED 계좌 일별 계산 거절', 'POST', '/api/v1/assets/cashflow/daily-limit', receiver,
        {'expectedIncome': 0, 'fixedExpenses': 0, 'eventBuffer': 0, 'daysUntilNextPayday': 10, 'snapshotDate': str(date.today())}, want=409)
    await b.auth_end(users)


async def dlt(users):
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
    sender = users[0]
    topic = 'moaje.banking.transfer-completed'
    reader = AIOKafkaConsumer(topic + '.DLT', bootstrap_servers='kafka:29092', group_id=None,
                              auto_offset_reset='earliest', enable_auto_commit=False)
    producer = AIOKafkaProducer(bootstrap_servers='kafka:29092')
    await producer.start()
    await reader.start()
    try:
        before = await b.query('asset', 'select balance from account where id=%s', (sender['account'],))
        metadata = await producer.send_and_wait(topic, value=b'\xff\xff\xff', key=str(sender['account']).encode(),
            headers=[('moaje-event-id', b'E2E-MALFORMED'), ('moaje-aggregate-id', str(sender['transfer']).encode()),
                     ('moaje-account-id', str(sender['account']).encode())])
        found = []
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            batch = await reader.getmany(timeout_ms=1000, max_records=100)
            found += [m for records in batch.values() for m in records if
                      dict(m.headers).get('moaje-event-id') == b'E2E-MALFORMED' and
                      int.from_bytes(dict(m.headers).get('kafka_dlt-original-offset', b''), 'big') == metadata.offset]
            if found:
                break
        headers = dict(found[0].headers) if found else {}
        b.record('손상 Protobuf DLT 적재·원본 추적', len(found) == 1 and
                 headers.get('kafka_dlt-original-topic') == topic.encode() and
                 'kafka_dlt-original-offset' in headers and 'kafka_dlt-exception-fqcn' in headers,
                 f'DLT 확인 건수={len(found)}, 원본 offset={metadata.offset}, 헤더={list(headers)}')
        async def routed_count():
            metric = await b.CLIENT.get('http://asset:8082/actuator/metrics/asset.consumer.dlt.reconciliation.routed')
            metric.raise_for_status()
            return sum(m['value'] for m in metric.json()['measurements'])
        count = await b.poll(routed_count, lambda x: x >= 1, 15)
        b.record('DLT 계좌 복구 대상 지정 지표', count >= 1, f'routed={count}; SYNC_REQUIRED 순간은 별도 직접 관찰하지 않음')
        await b.account_detail(sender, True)
        after = await b.query('asset', 'select balance,sync_status from account where id=%s', (sender['account'],))
        b.record('DLT 이후 스냅샷 복구·잔액 유지', before[0]['balance'] == after[0]['balance'] and after[0]['sync_status'] == 'SYNCED', str(after))
    finally:
        await reader.stop()
        await producer.stop()


async def crash(users, verify=False):
    sender, receiver, _ = users
    if not verify:
        await b.CLIENT.post('http://fault-proxy:18081/__control', json={'delay_once': True, 'forwarded': False, 'ready_to_kill': False})
        sending = asyncio.create_task(b.transfer(sender, receiver, 'e2e-crash-before-save', 11))
        async def control():
            return (await b.CLIENT.get('http://fault-proxy:18081/__control')).json()
        first = await b.poll(control, lambda x: x['forwarded'], 10)
        code, duplicate = await b.transfer(sender, receiver, 'e2e-crash-before-save', 11)
        latest = await control()
        rows = await b.query('banking', "select status,reconciliation_attempt_count from banking_transfer where idempotency_key='e2e-crash-before-save'")
        b.record('진행 중 재요청 PROCESSING·Mock 추가 호출 없음', code == 200 and duplicate.get('status') == 'PROCESSING' and
                 latest['transfer_posts'] == first['transfer_posts'], f'HTTP={code}, API상태={duplicate.get("status")}, Mock POST={latest["transfer_posts"]}')
        b.record('정상 호출 대기 중 대사 미선점', rows and rows[0]['status'] == 'PROCESSING' and rows[0]['reconciliation_attempt_count'] == 0, str(rows))
        await b.CLIENT.post('http://fault-proxy:18081/__control', json={'ready_to_kill': True})
        code, _ = await sending
        b.record('송금 중 Banking 강제 종료 응답', code in (500, 502, 503, 504), f'HTTP={code}; 서버 종료이므로 성공 응답을 기대하지 않음')
    else:
        rows = await b.poll(lambda: b.query('banking', "select transfer_id,status,reconciliation_attempt_count from banking_transfer where idempotency_key='e2e-crash-before-save'"),
                            lambda x: x and x[0]['status'] == 'SUCCEEDED', 170)
        ok = rows and rows[0]['status'] == 'SUCCEEDED' and rows[0]['reconciliation_attempt_count'] >= 1
        b.record('서버 종료 후 오래된 PROCESSING 대사 복구', ok, str(rows))
        if ok:
            tid = rows[0]['transfer_id']
            lookup = await b.CLIENT.get('http://fault-proxy:18081/__control')
            before = lookup.json()['transfer_posts']
            code, result = await b.transfer(sender, receiver, 'e2e-crash-before-save', 11)
            after = (await b.CLIENT.get('http://fault-proxy:18081/__control')).json()['transfer_posts']
            b.record('복구 거래 재요청 외부 재송금 없음', code == 200 and result.get('transferId') == str(tid) and before == after,
                     f'Mock POST before={before}, after={after}')
            outbox = await b.poll(lambda: b.query('banking', 'select status from banking_outbox where aggregate_id=%s', (str(tid),)),
                                  lambda x: x and x[0]['status'] == 'PUBLISHED', 45)
            history = await b.poll(lambda: b.query('asset', 'select count(*) n from transaction_history where banking_transfer_id=%s', (tid,)),
                                   lambda x: x[0]['n'] == 1, 45)
            b.record('서버 종료 복구 Outbox·Asset 연결 1건', outbox and outbox[0]['status'] == 'PUBLISHED' and history and history[0]['n'] == 1,
                     f'Outbox={outbox}, Asset={history}')


async def timeout_audit(users):
    sender = users[0]
    rows = await b.query('banking', "select transfer_id,status,failure_reason,reconciliation_required from banking_transfer where idempotency_key='e2e-timeout'")
    status, external = await b.mock('GET', '/api/transfers/' + str(rows[0]['transfer_id']), sender)
    b.record('Timeout 원거래와 Banking 상태 일치', status == 200 and external.get('status') == rows[0]['status'],
             f'Mock HTTP={status}, Mock 상태={external.get("status")}, Banking={rows[0]}; 외부 응답 원문은 기록하지 않음')
    outbox = await b.query('banking', 'select status,topic from banking_outbox where aggregate_id=%s', (str(rows[0]['transfer_id']),))
    b.record('Timeout 실제 성공 이벤트 복구 여부', any(r['topic'] == 'moaje.banking.transfer-completed' and r['status'] == 'PUBLISHED' for r in outbox), str(outbox))


async def fresh_profile(users):
    from redis.asyncio import Redis
    registration = b.registration_body(5)
    r = await b.call('신규 0원 사용자 가입', 'POST', '/api/v1/auth/register', body=registration, want=201)
    login = await b.call('신규 0원 사용자 로그인', 'POST', '/api/v1/auth/login', body={'phone_number': registration['phone_number'], 'pin': '123456'})
    user = {'id': str(r['data']['user_id']), 'token': login['data']['access_token'], 'ci': 'E2E-PROFILE-CI'}
    account = await b.call('신규 ACTIVE 0원 계좌 개설', 'POST', '/api/v1/banking/accounts', user,
        {'ci': user['ci'], 'userName': '테스트 사용자', 'phoneNumber': '01000000000', 'bankCode': '001', 'bankName': '테스트 은행', 'productName': 'E2E-PROFILE', 'initialBalance': 0}, want=201)
    user['account'] = account['accountId']
    await b.poll(lambda: b.account_detail(user), lambda x: x[0] == 200)
    await b.call('정상 ACTIVE 0원 일별 계산', 'POST', '/api/v1/assets/cashflow/daily-limit', user,
        {'expectedIncome': 0, 'fixedExpenses': 0, 'eventBuffer': 0, 'daysUntilNextPayday': 10, 'snapshotDate': str(date.today())})
    redis = Redis(host='mock-redis', decode_responses=True)
    try:
        async for key in redis.scan_iter(match='{banking}:account:*'):
            if await redis.type(key) == 'hash' and (await redis.hgetall(key)).get('ownerCi') == user['ci']:
                user['number'] = key.rsplit(':', 1)[-1]
    finally:
        await redis.aclose()
    code, result = await b.transfer(users[0], user, 'e2e-profile-first', 1)
    b.record('신규 사용자 첫 수취 송금', code == 200 and result.get('status') == 'COMPLETED', f'HTTP={code}')
    await b.account_detail(user, True)
    consumed = await b.poll(lambda: b.query('work', 'select count(*) n from fds_inference_log where user_id=%s', (user['id'],)), lambda x: x[0]['n'] >= 1)
    b.record('신규 사용자 실제 성공 이벤트 소비', consumed and consumed[0]['n'] >= 1, str(consumed))
    await b.call('집계 전 신규 사용자 소비 프로필', 'GET', '/api/v1/work/spending/' + user['id'] + '/profile', user)


async def fixes(users):
    sender, receiver, _ = users
    transaction = (await b.query('asset', 'select id from transaction_history where account_id=%s and visible_to_user=1 limit 1',
                                  (sender['account'],)))[0]['id']
    cases = [
        ('타인 계좌 상세 ProblemDetail', 'GET', f"/api/v1/assets/accounts/{sender['account']}/detail", receiver, 400, 'DUPLICATE_AUTH'),
        ('타인 계좌 refresh ProblemDetail', 'POST', f"/api/v1/assets/accounts/{sender['account']}/refresh", receiver, 400, 'DUPLICATE_AUTH'),
        ('타인 계좌 목록 ProblemDetail', 'GET', f"/api/v1/assets/accounts/{sender['account']}/transactions", receiver, 403, 'DUPLICATE_AUTH'),
        ('다른 계좌 거래 ProblemDetail', 'GET', f"/api/v1/assets/accounts/{receiver['account']}/{transaction}/transaction", receiver, 404, 'NOT_FOUND_ACCOUNT_TRANSFER_HISTORY'),
        ('없는 계좌 상세 ProblemDetail', 'GET', '/api/v1/assets/accounts/999999999/detail', sender, 404, 'ACCOUNT_NOT_FOUND'),
    ]
    for name, method, path, user, wanted, code in cases:
        status, body = await b.request(method, path, user)
        b.record(name, status == wanted and body.get('status') == wanted and body.get('title') == code and bool(body.get('detail')),
                 f'HTTP={status}, ProblemDetail status={body.get("status")}, title={body.get("title")}')
    rows = await b.query('banking', "select transfer_id,status,reconciliation_attempt_count from banking_transfer where idempotency_key='e2e-timeout'")
    tid = rows[0]['transfer_id']
    logs = await b.query('banking', 'select status from kftc_api_log where transfer_id=%s', (tid,))
    outbox = await b.query('banking', 'select topic,status from banking_outbox where aggregate_id=%s', (str(tid),))
    b.record('응답 추출 오류 기록 후 대사 성공', rows[0]['status'] == 'SUCCEEDED' and
             any(x['status'] in ('UNREADABLE_RESPONSE', 'TIMEOUT') for x in logs) and any(x['status'] == 'SUCCESS' for x in logs),
             f'거래={rows}, 감사 상태={logs}')
    b.record('불명확 응답에서 실패 이벤트 미생성', not any(x['topic'] == 'moaje.banking.transfer-failed' for x in outbox) and
             any(x['topic'] == 'moaje.banking.transfer-completed' and x['status'] == 'PUBLISHED' for x in outbox), str(outbox))
    history = await b.poll(lambda: b.query('asset', 'select count(*) n from transaction_history where banking_transfer_id=%s and account_id=%s',
                                         (tid, sender['account'])), lambda x: x[0]['n'] == 1, 45)
    b.record('Timeout 복구 Asset 거래 1건', history and history[0]['n'] == 1, str(history))


async def audit(users):
    sender, receiver, _ = users
    code, result = await b.request('POST', '/api/v1/banking/transfers', sender,
        {'requesterUserId': receiver['id'], 'withdrawalAccountId': sender['account'], 'depositBankCode': '001',
         'depositAccountNumber': receiver['number'], 'amount': 10000, 'currency': 'KRW'}, {'Idempotency-Key': 'e2e-first'})
    stored = await b.query('banking', 'select principal_id from banking_transfer where transfer_id=%s', (sender['transfer'],))
    b.record('본문 사용자 ID 변조가 JWT 사용자에 영향 없음', code == 200 and result.get('transferId') == sender['transfer'] and stored[0]['principal_id'] == sender['id'],
             f'HTTP={code}, 기존 거래 ID 유지, DB principal_id=JWT sub')
    for path in ['/docs/swagger-ui.html', '/docs/auth/openapi.json', '/docs/asset/v3/api-docs',
                 '/docs/banking/v3/api-docs', '/docs/work/openapi.json', '/docs/asset/swagger-ui/swagger-ui-bundle.js']:
        response = await b.CLIENT.get(b.GATEWAY + path)
        b.record('Gateway Swagger 라우팅 ' + path, response.status_code == 200 and bool(response.content), f'HTTP={response.status_code}')
    for db in ['banking', 'asset']:
        rows = await b.query(db, 'select version,success from flyway_schema_history order by installed_rank')
        b.record('빈 MySQL Flyway 검증 ' + db, bool(rows) and all(r['success'] == 1 for r in rows), str(rows))
    # Mock 응답의 개인정보는 버리고 잔액·상태만 비교한다.
    for user in users[:2]:
        await b.account_detail(user, True)
        _, detail = await b.account_detail(user)
        status, source = await b.mock('GET', '/api/accounts/' + user['number'], user)
        b.record('최종 Mock·Asset 잔액 일치 ' + user['id'], status == 200 and Decimal(str(source['balance'])) == Decimal(str(detail['balance'])),
                 f'Mock={source.get("balance")}, Asset={detail.get("balance")}; 금융 상태의 일치는 별도 판정')


async def main():
    phase = sys.argv[1]
    if b.REPORT.exists():
        b.ROWS = json.loads(b.REPORT.read_text())
    start = len(b.ROWS)
    async with httpx.AsyncClient(timeout=75) as client:
        b.CLIENT = client
        if phase == 'core':
            users = await b.setup()
            await section('정상 송금·Asset 기능', lambda: b.normal(users))
            await section('금융 멱등성', lambda: financial(users))
            await section('Work HTTP', lambda: b.work_apis(users))
            await section('RPC·Auth 소유권', lambda: rpc(users))
        else:
            users = json.loads(b.STATE.read_text())
            actions = {'timeout': b.timeout, 'timeout-recheck': lambda u: b.timeout(u, 'e2e-timeout-recheck'), 'multimonth': b.multimonth, 'replay': replay,
                       'outage': outage, 'recovered': lambda u: outage(u, True), 'final': final,
                       'dlt': dlt, 'crash': crash, 'crash-recovered': lambda u: crash(u, True), 'timeout-audit': timeout_audit,
                       'fresh-profile': fresh_profile, 'audit': audit, 'fixes': fixes}
            await section(phase, lambda: actions[phase](users))
    return int(any(r['status'] == 'FAIL' for r in b.ROWS[start:]))


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
