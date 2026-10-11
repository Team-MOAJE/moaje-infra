"""격리 Compose 전용. 원장은 API로 준비하고 DB는 결과 확인에만 사용한다."""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, unquote

import aiomysql
import httpx

ROWS = []
STATE = Path('/tmp/moaje-e2e-state.json')
REPORT = Path('/tmp/moaje-e2e-results.json')
GATEWAY = 'http://gateway:8080'
CLIENT = None


def record(name, ok, detail):
    row = {'name': name, 'status': 'PASS' if ok else 'FAIL', 'detail': str(detail)}
    ROWS.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)
    REPORT.write_text(json.dumps(ROWS, ensure_ascii=False, indent=2), encoding='utf-8')


async def request(method, path, user=None, body=None, headers=None, base=GATEWAY):
    hdr = dict(headers or {})
    if user:
        hdr['Authorization'] = 'Bearer ' + user['token']
    r = await CLIENT.request(method, base + path, json=body, headers=hdr)
    try:
        value = r.json()
    except ValueError:
        value = {'nonJson': True}
    return r.status_code, value


async def call(name, method, path, user=None, body=None, want=200, headers=None):
    status, value = await request(method, path, user, body, headers)
    record(name, status == want, f'HTTP actual={status}, expected={want}')
    return value


async def query(db, sql, args=()):
    from app.core.config import settings
    work_password = unquote(urlsplit(settings.DATABASE_URL).password or '')
    creds = {'asset': ('moaje_asset', 'moaje_asset', 'moaje_asset'),
             'banking': ('moaje_banking', 'moaje_banking', 'moaje_banking'),
             'work': ('moaje_work', work_password, 'work_db')}
    user, password, database = creds[db]
    conn = await aiomysql.connect(host=db + '-mysql', user=user, password=password, db=database)
    try:
        async with conn.cursor(aiomysql.DictCursor) as cursor:
            # MySQL YEAR_MONTH는 예약어이므로 실제 테이블의 동명 컬럼을 인용한다.
            await cursor.execute(sql.replace('year_month=', '`year_month`='), args)
            return await cursor.fetchall()
    finally:
        conn.close()


async def poll(fn, condition, seconds=50):
    deadline = time.monotonic() + seconds
    value = None
    while time.monotonic() < deadline:
        try:
            value = await fn()
            if condition(value):
                return value
        except httpx.HTTPError:
            pass
        await asyncio.sleep(.5)
    return value


async def mock(method, path, user, body=None):
    raw = json.dumps(body, separators=(',', ':'), ensure_ascii=False).encode() if body is not None else b''
    signature = hmac.new(os.environ.get('MOCK_HMAC', 'Moaje-banking-secret').encode(), raw, hashlib.sha256).hexdigest()
    r = await CLIENT.request(method, 'http://mock-banking:8081' + path, content=raw,
                             headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + user['mockToken'],
                                      'X-Signature': signature})
    return r.status_code, r.json()


async def account_detail(user, refresh=False):
    return await request('POST' if refresh else 'GET', f"/api/v1/assets/accounts/{user['account']}/" +
                         ('refresh' if refresh else 'detail'), user)


async def transfer(user, receiver, key, amount=10000):
    return await request('POST', '/api/v1/banking/transfers', user,
                         {'withdrawalAccountId': user['account'], 'depositBankCode': '001',
                          'depositAccountNumber': receiver['number'], 'amount': amount, 'currency': 'KRW'},
                         {'Idempotency-Key': key})


async def setup():
    users = []
    for i in range(3):
        # 최신 Auth는 SMS 대신 휴대폰 번호와 PIN, 약관 동의를 받는다.
        # 아래 번호는 문자 발송에 사용하지 않는 격리 환경의 합성 테스트 입력이다.
        registration = registration_body(i)
        registered = await call(f'가입 {i}', 'POST', '/api/v1/auth/register', body=registration, want=201)
        login = await call(f'로그인 {i}', 'POST', '/api/v1/auth/login', body={'phone_number': registration['phone_number'], 'pin': '123456'})
        user = {'id': str(registered['data']['user_id']), 'token': login['data']['access_token'],
                'refresh': login['data']['refresh_token'], 'ci': f'E2E-CI-{i}'}
        users.append(user)
    sender, receiver, empty = users
    await call('중복 가입', 'POST', '/api/v1/auth/register', body=registration_body(0), want=409)
    await call('잘못된 PIN 길이', 'POST', '/api/v1/auth/register', body={**registration_body(9), 'pin': '12345'}, want=400)
    await call('필수 약관 거부', 'POST', '/api/v1/auth/register', body={**registration_body(9), 'terms_agreed': False}, want=400)
    await call('PIN 확인 불일치', 'POST', '/api/v1/auth/register', body={**registration_body(9), 'pin_confirm': '654321'}, want=400)
    await call('잘못된 PIN 로그인', 'POST', '/api/v1/auth/login', body={'phone_number': registration_body(0)['phone_number'], 'pin': '654321'}, want=422)
    await call('무인증 Asset 차단', 'GET', '/api/v1/assets/accounts/1/detail', want=401)
    await call('위조 사용자 헤더 차단', 'GET', '/api/v1/assets/accounts/1/detail', headers={'X-Authenticated-User-Id': sender['id']}, want=401)
    for user, balance in [(sender, 100000), (receiver, 0)]:
        opened = await call('Banking 계좌 개설 ' + user['id'], 'POST', '/api/v1/banking/accounts', user,
                            {'ci': user['ci'], 'userName': '테스트 사용자', 'phoneNumber': '01000000000',
                             'bankCode': '001', 'productName': 'E2E-' + user['id'], 'initialBalance': balance}, want=201)
        user['account'] = opened['accountId']
        r = await CLIENT.post('http://mock-banking:8081/oauth/2.0/token', json={
            'ci': user['ci'], 'userName': '테스트 사용자', 'phoneNumber': '01000000000'})
        user['mockToken'] = r.json()['accessToken']
        # 계좌번호는 응답·보고서에 출력하지 않고 테스트 프로세스 메모리에서만 사용한다.
        from redis.asyncio import Redis
        redis = Redis(host='mock-redis', decode_responses=True)
        async for key in redis.scan_iter(match='{banking}:account:*'):
            if await redis.type(key) == 'hash':
                fields = await redis.hgetall(key)
                if fields.get('ownerCi') == user['ci']:
                    user['number'] = key.rsplit(':', 1)[-1]
        await redis.aclose()
        detail = await poll(lambda: account_detail(user), lambda x: x[0] == 200)
        record('계좌 생성 이벤트 Asset 반영 ' + user['id'], detail and detail[0] == 200, '계좌 상세 조회 가능')
    STATE.write_text(json.dumps(users), encoding='utf-8')
    return users


def registration_body(index):
    return {'phone_number': f'0109000000{index}', 'name': '통합시험 사용자',
            'pin': '123456', 'pin_confirm': '123456', 'terms_agreed': True,
            'privacy_agreed': True, 'terms_version': 'e2e-v1', 'privacy_version': 'e2e-v1'}


async def normal(users):
    sender, receiver, empty = users
    code, result = await transfer(sender, receiver, 'e2e-first')
    record('정상 송금', code == 200 and result.get('status') == 'COMPLETED', f'HTTP={code}, status={result.get("status")}')
    sender['transfer'] = result['transferId']
    STATE.write_text(json.dumps(users), encoding='utf-8')
    again = await transfer(sender, receiver, 'e2e-first')
    record('같은 요청 같은 transferId', again[1].get('transferId') == result['transferId'], 'transferId 동일')
    conflict = await transfer(sender, receiver, 'e2e-first', 9999)
    record('같은 키 다른 금액', conflict[0] == 409, f'HTTP={conflict[0]}')
    await call('송금 키 누락', 'POST', '/api/v1/banking/transfers', sender, body={
        'withdrawalAccountId': sender['account'], 'depositBankCode': '001', 'depositAccountNumber': receiver['number'],
        'amount': 1, 'currency': 'KRW'}, want=400)
    snapshot = await mock('GET', '/api/accounts/' + sender['number'], sender)
    record('Mock 송금인 잔액 90000', Decimal(str(snapshot[1]['balance'])) == 90000, 'balance=' + str(snapshot[1]['balance']))
    snapshot = await mock('GET', '/api/accounts/' + receiver['number'], receiver)
    record('Mock 수취인 잔액 10000', Decimal(str(snapshot[1]['balance'])) == 10000, 'balance=' + str(snapshot[1]['balance']))
    detail = await poll(lambda: account_detail(sender), lambda x: x[0] == 200 and Decimal(str(x[1]['balance'])) == 90000)
    record('송금인 Asset 90000', detail and detail[0] == 200 and Decimal(str(detail[1]['balance'])) == 90000, '이벤트 또는 정기 스냅샷 경로로 반영; DB 연결도 별도 확인')
    for user, amount in [(sender, 90000), (receiver, 10000)]:
        d = await account_detail(user, True)
        record('refresh 잔액 ' + user['id'], d[0] == 200 and Decimal(str(d[1]['balance'])) == amount, f'HTTP={d[0]}, balance={d[1].get("balance")}')
    rows = await query('banking', 'select status,external_transaction_id from banking_transfer where transfer_id=%s', (result['transferId'],))
    record('Banking 최종 상태·외부 ID', len(rows) == 1 and rows[0]['status'] == 'SUCCEEDED' and bool(rows[0]['external_transaction_id']), str(rows))
    outbox = await poll(lambda: query('banking', 'select status,event_id,attempt_count from banking_outbox where aggregate_id=%s', (str(result['transferId']),)), lambda x: x and all(r['status'] == 'PUBLISHED' for r in x))
    record('실제 Banking Outbox 발행', bool(outbox) and all(r['status'] == 'PUBLISHED' for r in outbox), str(outbox))
    history = await query('asset', 'select count(*) n from transaction_history where banking_transfer_id=%s and account_id=%s', (result['transferId'], sender['account']))
    record('Asset 내부 거래 연결 1건', history[0]['n'] == 1, str(history))
    work = await poll(lambda: query('work', 'select count(*) n from fds_inference_log where user_id=%s', (sender['id'],)), lambda x: x[0]['n'] >= 1)
    record('실제 Asset 성공 이벤트 Work 소비', work and work[0]['n'] >= 1, str(work))
    await call('타인 계좌 상세 차단', 'GET', f"/api/v1/assets/accounts/{sender['account']}/detail", receiver, want=403)
    foreign = await request('POST', '/api/v1/banking/transfers', receiver, {
        'withdrawalAccountId': sender['account'], 'depositBankCode': '001', 'depositAccountNumber': receiver['number'], 'amount': 1, 'currency': 'KRW'}, {'Idempotency-Key': 'foreign-account'})
    record('타인 출금계좌 차단', foreign[0] == 403, f'HTTP={foreign[0]}')
    failed = await transfer(sender, receiver, 'insufficient', 999999999)
    record('잔액 부족 명확 실패', failed[0] == 200 and failed[1].get('status') == 'FAILED', f'HTTP={failed[0]}, status={failed[1].get("status")}')
    simultaneous = await asyncio.gather(*(transfer(sender, receiver, 'concurrent-same', 1) for _ in range(8)))
    ids = {r[1].get('transferId') for r in simultaneous}
    row = await query('banking', "select count(*) n from banking_transfer where idempotency_key='concurrent-same'")
    record('동일 키 8개 동시 요청', len(ids) == 1 and None not in ids and row[0]['n'] == 1, f'반환 ID 종류={len(ids)}, DB행={row[0]["n"]}')
    await account_detail(sender, True)
    # 원장은 Mock 공개 출금 API로만 준비한다. Asset INSERT로 페이지 수를 만들지 않는다.
    for i in range(121):
        code, _ = await mock('POST', '/api/accounts/' + sender['number'] + '/withdrawals', sender,
                             {'amount': 1, 'merchantName': '스타벅스 테스트', 'memo': 'E2E paging'})
        if code != 200:
            raise RuntimeError('Mock withdrawal HTTP ' + str(code))
    await account_detail(sender, True)
    all_ids, sizes, cursor = [], [], None
    for _ in range(6):
        path = f"/api/v1/assets/accounts/{sender['account']}/transactions" + (f'?lastTransactionId={cursor}' if cursor else '')
        page = await request('GET', path, sender)
        if page[0] != 200:
            break
        items = page[1]['transactions']
        all_ids.extend(r['transactionId'] for r in items)
        sizes.append(len(items))
        cursor = page[1]['nextCursor']
        if not page[1]['hasNext']:
            break
    expected = (await query('asset', "select count(*) n from transaction_history where account_id=%s and visible_to_user=1", (sender['account'],)))[0]['n']
    record('50건 커서 페이지 중복·누락 없음', len(all_ids) == len(set(all_ids)) == expected and sizes[:2] == [50, 50], f'페이지 크기={sizes}, 조회={len(all_ids)}, DB={expected}')
    if all_ids:
        await call('거래 단건 조회', 'GET', f"/api/v1/assets/accounts/{sender['account']}/{all_ids[0]}/transaction", sender)
        status, _ = await request('GET', f"/api/v1/assets/accounts/{receiver['account']}/{all_ids[0]}/transaction", receiver)
        record('다른 계좌 거래 ID 차단', 400 <= status < 500, f'HTTP={status}; 500이면 오류 응답 문제')
    before = await query('asset', 'select count(*) n from transaction_history where account_id=%s', (sender['account'],))
    await account_detail(sender, True)
    after = await query('asset', 'select count(*) n from transaction_history where account_id=%s', (sender['account'],))
    record('refresh 반복 시 중복 없음', before == after, str(after))
    daily = {'expectedIncome': 100000, 'fixedExpenses': 10000, 'eventBuffer': 5000,
             'daysUntilNextPayday': 10, 'snapshotDate': str(date.today()), 'forceRefresh': False}
    await call('일별 한도 계산', 'POST', '/api/v1/assets/cashflow/daily-limit', sender, daily)
    await call('일별 한도 캐시 재조회', 'POST', '/api/v1/assets/cashflow/daily-limit', sender, daily)
    invalid = await request('POST', '/api/v1/assets/cashflow/daily-limit', sender, {**daily, 'daysUntilNextPayday': 0})
    record('0일 계산 거절', 400 <= invalid[0] < 500, f'HTTP={invalid[0]}')
    await call('계좌 미연동 일별 계산', 'POST', '/api/v1/assets/cashflow/daily-limit', empty, daily, want=409)
    month = date.today().strftime('%Y-%m')
    monthly = await call('월별 집계 조회·Outbox 생성', 'GET', '/api/v1/assets/cashflow/monthly?yearMonth=' + month, sender)
    category = await call('카테고리 집계', 'GET', '/api/v1/assets/cashflow/category?yearMonth=' + month, sender)
    record('가맹점 CAFE 분류 121원', any(c['category'] == 'CAFE' and Decimal(str(c['amount'])) == 121 for c in category.get('categories', [])), 'Mock merchantName → snapshot → Asset 분류')
    record('개인 간 송금 TRANSFER 분리', Decimal(str(monthly.get('transferAmount', -1))) == 10001, str(monthly))
    await call('거래 없는 사용자 0원 월 집계', 'GET', '/api/v1/assets/cashflow/monthly?yearMonth=' + month, empty)
    work_month = await poll(lambda: query('work', 'select * from monthly_cashflow where user_id=%s and year_month=%s', (sender['id'], month)), lambda x: len(x) == 1)
    record('실제 월 집계 이벤트 Work 소비', len(work_month or []) == 1, str(work_month))
    users[0]['monthly'] = month
    STATE.write_text(json.dumps(users), encoding='utf-8')


async def work_apis(users):
    user, other, _ = users
    uid = user['id']
    root = '/api/v1/work'
    await call('Work 타인 조회 차단', 'GET', root + f"/spending/{other['id']}/profile", user, want=403)
    for path in ['/calendar/universities', '/onboarding/questions', '/simulator/baselines',
                 f'/spending/{uid}/profile', f'/spending/{uid}/event-buffer']:
        await call('Work ' + path, 'GET', root + path, user)
    answers = ['STUDENT', 'MONTHLY_RENT', 'LARGE_CORP', 'SAVING', 'HOME_REST', 'COMPARE', 'WORK_LIFE', 'FOOD', 'UNKNOWN', 'NO_PLAN']
    body = {'user_id': int(uid), 'answers': [{'question_no': i + 1, 'answer_code': code,
             **({'answer_text': '독립할 자금을 모으고 싶다'} if i == 8 else {})} for i, code in enumerate(answers)]}
    await call('온보딩 10문항 저장', 'POST', root + f'/onboarding/{uid}/answers', user, body)
    await call('온보딩 단일 답변 수정', 'POST', root + f'/onboarding/{uid}/answers/3', user, {'question_no': 3, 'answer_code': 'STARTUP'})
    for path in [f'/onboarding/{uid}/answers', f'/onboarding/{uid}/progress', f'/onboarding/{uid}/profile']:
        await call('Work ' + path, 'GET', root + path, user)
    sim = {'monthly_income': 2800000, 'monthly_housing': 600000, 'monthly_living': 700000, 'monthly_leisure': 200000}
    result = await call('시뮬레이터 실제 Asset 잔액', 'POST', root + f'/simulator/{uid}/simulate', user, sim)
    balance = await account_detail(user)
    record('시뮬레이터 잔액 동일', result.get('asset_source') == 'ASSET_SERVICE' and Decimal(str(result.get('current_asset', -1))) == Decimal(str(balance[1]['balance'])), 'Work→Asset RPC 결과와 Asset 상세 비교')
    await call('조건 변경 시뮬레이터', 'POST', root + f'/simulator/{uid}/adjust', user, {**sim, 'monthly_delta': -200000})
    await call('사회인 준비도', 'POST', root + f'/readiness/{uid}', user, sim)
    start = date.today() + timedelta(days=3)
    await call('수동 학사 일정 등록', 'POST', root + '/spending/schedule', user, {
        'user_id': int(uid), 'event_type': 'MT', 'event_name': 'E2E MT', 'start_date': str(start),
        'end_date': str(start + timedelta(days=1)), 'expected_extra_spend': 150000}, want=201)
    for path in [f'/spending/{uid}/schedules', f'/calendar/{uid}/schedules', f'/spending/{uid}/event-buffer',
                 f'/spending/{uid}/report?year=2026&semester=2', f'/recap/{uid}/months', f'/recap/{uid}/{date.today():%Y-%m}']:
        await call('Work ' + path, 'GET', root + path, user)
    await call('학사 일정 동기화', 'POST', root + '/calendar/sync', user,
               {'user_id': int(uid), 'university_id': 1, 'year': 2026, 'semester': 2})
    detect = {'user_id': int(uid), 'transaction_id': 'E2E-API-FDS', 'amount': 480000, 'merchant': '테스트', 'hour': 3}
    await call('FDS 탐지', 'POST', root + '/fds/detect', user, detect)
    await call('FDS 동일 거래 재요청', 'POST', root + '/fds/detect', user, detect)
    for path in [f'/fds/{uid}/blacklist', f'/fds/{uid}/logs', f'/fds/{uid}/alerts', f'/fds/{uid}/safety-score']:
        value = await call('Work ' + path, 'GET', root + path, user)
        if path.endswith('/alerts'):
            alerts = value.get('alerts', []) if isinstance(value, dict) else value
            if alerts:
                aid = alerts[0].get('id', alerts[0].get('alert_id'))
                await call('FDS 알림 확인', 'PATCH', root + f'/fds/{uid}/alerts/{aid}/confirm', user)
    await call('운영 지표 사용자 차단', 'GET', root + '/metrics/retention', user, want=403)
    ops = {'X-Internal-Token': 'e2e-local-operator-only'}
    await call('운영 블랙리스트 등록', 'POST', root + '/fds/blacklist', user,
               {'user_id': int(other['id']), 'reason': 'MANUAL', 'description': 'E2E only'}, want=201, headers=ops)
    await call('운영 블랙리스트 해제', 'DELETE', root + f"/fds/{other['id']}/blacklist", user, headers=ops)
    await call('운영 재방문 지표', 'GET', root + '/metrics/retention', user, headers=ops)


async def timeout(users, key='e2e-timeout'):
    sender, receiver, _ = users
    await CLIENT.post('http://fault-proxy:18081/__control', json={'delay_once': True, 'forwarded': False})
    status, result = await transfer(sender, receiver, key, 10)
    rows = await query('banking', 'select status,reconciliation_required from banking_transfer where transfer_id=%s', (result['transferId'],))
    record('Mock 성공 후 응답 Timeout', status == 200 and rows[0]['status'] in ('UNKNOWN', 'SUCCEEDED'), str(rows))
    recovered = await poll(lambda: query('banking', 'select status,reconciliation_attempt_count from banking_transfer where transfer_id=%s', (result['transferId'],)), lambda x: x[0]['status'] == 'SUCCEEDED', 90)
    record('Timeout 대사 SUCCEEDED 복구', recovered[0]['status'] == 'SUCCEEDED' and recovered[0]['reconciliation_attempt_count'] >= 1, str(recovered))
    # 거래 결과 커밋과 Kafka 발행은 서로 다른 작업이다.
    # SUCCEEDED 직후 PENDING인 것은 정상이며, 발행 완료 조건을 제한 시간 안에서 기다려 검증한다.
    final = await poll(lambda: query('banking', 'select status,topic from banking_outbox where aggregate_id=%s', (str(result['transferId']),)),
                       lambda rows: any(row['status'] == 'PUBLISHED' and row['topic'] == 'moaje.banking.transfer-completed' for row in rows), 45)
    record('Timeout 성공 복구 Outbox 발행', bool(final) and any(r['status'] == 'PUBLISHED' and r['topic'] == 'moaje.banking.transfer-completed' for r in final), str(final))


async def auth_end(users):
    user = users[2]
    await call('JWT POST 검증', 'POST', '/api/v1/auth/token/validate', body={'access_token': user['token']})
    await call('JWT GET 검증', 'GET', '/api/v1/auth/token/validate', user)
    token = await call('계좌 토큰 생성', 'POST', '/api/v1/auth/account-token', user, {'user_id': int(user['id']), 'account_number': 'E2E-NOT-REAL'})
    if 'data' in token:
        await call('계좌 토큰 검증', 'POST', '/api/v1/auth/account-token/validate', user, {'account_token': token['data']['account_token']})
    rotated = await call('refresh 교체', 'POST', '/api/v1/auth/refresh', body={'refresh_token': user['refresh']})
    await call('이전 refresh 재사용 거절', 'POST', '/api/v1/auth/refresh', body={'refresh_token': user['refresh']}, want=401)
    await call('로그아웃', 'POST', '/api/v1/auth/logout', body={'refresh_token': rotated['data']['refresh_token']})
    await call('로그아웃 refresh 거절', 'POST', '/api/v1/auth/refresh', body={'refresh_token': rotated['data']['refresh_token']}, want=401)


async def independent(users):
    sender, receiver, empty = users
    await call('PIN 길이 검증 재확인(현행 Auth 400 규격)', 'POST', '/api/v1/auth/register', body={'email': 'bad@moaje.test', 'pin': '12345'}, want=400)
    for i in range(121):
        status, _ = await mock('POST', '/api/accounts/' + sender['number'] + '/withdrawals', sender,
                               {'amount': 1, 'merchantName': '스타벅스 테스트', 'memo': 'E2E'})
        if status != 200:
            raise RuntimeError('Mock withdrawal HTTP ' + str(status))
    refreshed = await account_detail(sender, True)
    record('Mock 외부 지출 121건 → 스냅샷 잔액', refreshed[0] == 200 and Decimal(str(refreshed[1]['balance'])) == 99879,
           f'HTTP={refreshed[0]}, balance={refreshed[1].get("balance")}')
    all_ids, sizes, cursor = [], [], None
    for _ in range(6):
        url = f"/api/v1/assets/accounts/{sender['account']}/transactions" + (f'?lastTransactionId={cursor}' if cursor else '')
        code, page = await request('GET', url, sender)
        if code != 200:
            raise RuntimeError('Paging HTTP ' + str(code))
        all_ids += [r['transactionId'] for r in page['transactions']]
        sizes.append(len(page['transactions']))
        cursor = page['nextCursor']
        if not page['hasNext']:
            break
    record('50건 페이지 중복·누락 검증', len(all_ids) == len(set(all_ids)) == 121 and sizes == [50, 50, 21], f'페이지={sizes}, 총={len(all_ids)}')
    await call('거래 단건 조회', 'GET', f"/api/v1/assets/accounts/{sender['account']}/{all_ids[0]}/transaction", sender)
    wrong = await request('GET', f"/api/v1/assets/accounts/{receiver['account']}/{all_ids[0]}/transaction", receiver)
    record('다른 계좌 거래 ID 차단', 400 <= wrong[0] < 500, f'HTTP={wrong[0]}')
    await call('타인 계좌 상세 차단', 'GET', f"/api/v1/assets/accounts/{sender['account']}/detail", receiver, want=403)
    await account_detail(sender, True)
    count = await query('asset', 'select count(*) n from transaction_history where account_id=%s', (sender['account'],))
    record('반복 refresh 거래 121건 유지', count[0]['n'] == 121, str(count))
    daily = {'expectedIncome': 100000, 'fixedExpenses': 10000, 'eventBuffer': 5000,
             'daysUntilNextPayday': 10, 'snapshotDate': str(date.today()), 'forceRefresh': False}
    result = await call('일별 한도 계산', 'POST', '/api/v1/assets/cashflow/daily-limit', sender, daily)
    record('일별 한도 금액 검증', Decimal(str(result.get('dailyLimit', -1))) == Decimal('18487.9'), str(result))
    cache = await call('일별 한도 캐시 재조회', 'POST', '/api/v1/assets/cashflow/daily-limit', sender, daily)
    record('일별 캐시 동일 입력 결과 일치', result == cache, '응답 전체 비교')
    await call('정상 ACTIVE 0원 계산', 'POST', '/api/v1/assets/cashflow/daily-limit', receiver, {**daily, 'expectedIncome': 0, 'fixedExpenses': 0, 'eventBuffer': 0})
    await call('계좌 미연동 계산 거절', 'POST', '/api/v1/assets/cashflow/daily-limit', empty, daily, want=409)
    zero_day = await request('POST', '/api/v1/assets/cashflow/daily-limit', sender, {**daily, 'daysUntilNextPayday': 0})
    record('0일 계산 거절', 400 <= zero_day[0] < 500, f'HTTP={zero_day[0]}')
    month = date.today().strftime('%Y-%m')
    monthly = await call('월별 집계', 'GET', '/api/v1/assets/cashflow/monthly?yearMonth=' + month, sender)
    categories = await call('카테고리 집계', 'GET', '/api/v1/assets/cashflow/category?yearMonth=' + month, sender)
    record('월 지출 121원·자금이동 0원', Decimal(str(monthly.get('expenseAmount', -1))) == 121 and Decimal(str(monthly.get('transferAmount', -1))) == 0, str(monthly))
    record('CAFE 121원 분류', any(r['category'] == 'CAFE' and Decimal(str(r['amount'])) == 121 for r in categories.get('categories', [])), 'merchantName을 스냅샷으로 수집한 뒤 분류')
    zero = await call('거래 없는 사용자 0원 집계', 'GET', '/api/v1/assets/cashflow/monthly?yearMonth=' + month, empty)
    record('미연동 사용자 월 집계 0원', all(Decimal(str(zero.get(k, -1))) == 0 for k in ['incomeAmount','expenseAmount','transferAmount']), str(zero))
    work = await poll(lambda: query('work', 'select * from monthly_cashflow where user_id=%s and year_month=%s', (sender['id'], month)), lambda x: len(x) == 1)
    record('실제 Asset 월 집계 Outbox → Work', len(work or []) == 1 and Decimal(str(work[0]['total_expense'])) == 121, str(work))
    cats = await poll(lambda: query('work', "select amount from category_cashflow where user_id=%s and year_month=%s and category_code='CAFE'", (sender['id'], month)), lambda x: len(x) == 1)
    record('실제 Asset 카테고리 Outbox → Work', len(cats or []) == 1 and Decimal(str(cats[0]['amount'])) == 121, str(cats))
    worktx = await poll(lambda: query('work', 'select count(*) n from fds_inference_log where user_id=%s', (sender['id'],)), lambda x: x[0]['n'] == 121)
    record('실제 스냅샷 성공 121건 → Work', worktx and worktx[0]['n'] == 121, str(worktx))


async def extended(users):
    import grpc
    from app.grpc.asset_client import AssetClient, BalanceStatus, load_channel_credentials
    from app.grpc import asset_service_pb2 as pb, asset_service_pb2_grpc as stubs
    sender, receiver, empty = users
    for user, wanted in [(sender, Decimal('99879')), (receiver, Decimal('0'))]:
        result = await AssetClient().get_current_balance(int(user['id']))
        record('실제 mTLS 잔액 RPC ' + user['id'], result.status == BalanceStatus.OK and result.amount == wanted, f'status={result.status}, amount={result.amount}')
    async with grpc.aio.secure_channel('asset:9090', load_channel_credentials()) as channel:
        stub = stubs.AssetServiceStub(channel)
        for uid, expected in [('', grpc.StatusCode.INVALID_ARGUMENT), (empty['id'], grpc.StatusCode.FAILED_PRECONDITION)]:
            try:
                await stub.GetCurrentBalance(pb.GetCurrentBalanceRequest(user_id=uid), timeout=5)
                record('잔액 RPC 오류 매핑 ' + (uid or '빈ID'), False, '오류 없이 응답')
            except grpc.aio.AioRpcError as exc:
                record('잔액 RPC 오류 매핑 ' + (uid or '빈ID'), exc.code() == expected, exc.code().name)
        response = await stub.GetDailyCashflow(pb.GetDailyCashflowRequest(
            user_id=sender['id'], days_until_next_payday=10, snapshot_date=str(date.today())), timeout=5)
        record('일별 계산 RPC', Decimal(str(response.current_balance.amount)) == 99879, f'current_balance={response.current_balance.amount}, daily_limit={response.daily_limit.amount}')
    await call('송금 Idempotency-Key 누락 차단', 'POST', '/api/v1/banking/transfers', sender, body={
        'withdrawalAccountId': sender['account'], 'depositBankCode': '001', 'depositAccountNumber': receiver['number'], 'amount': 1}, want=400)
    unauthorized = await call('타인 계좌 토큰 생성 차단', 'POST', '/api/v1/auth/account-token', sender,
                              {'user_id': int(receiver['id']), 'account_number': 'E2E-OTHER-FAKE'}, want=403)
    # 외부 과거 거래는 Mock의 테스트 전용 API로 만든다. Asset 원장에 INSERT하지 않는다.
    prior = date.today().replace(day=1) - timedelta(days=1)
    month = prior.strftime('%Y-%m')
    before = await call('전월 최초 집계', 'GET', '/api/v1/assets/cashflow/monthly?yearMonth=' + month, sender)
    token = os.environ.get('FIXTURE_TOKEN', 'moaje-local-fixture-token')
    status, fixture = await request('POST', '/internal/test-fixtures/personas', body={
        'fixtureRunId': 'e2e-three-months', 'ownerCi': sender['ci'], 'bankCode': '001',
        'productName': 'E2E-' + sender['id'], 'months': 3, 'persona': 'BALANCED_STUDENT'},
        headers={'X-Fixture-Token': token}, base='http://mock-banking:8081')
    record('Mock 다개월 페르소나 API', status == 200, f'HTTP={status}')
    await account_detail(sender, True)
    revised = await poll(lambda: request('GET', '/api/v1/assets/cashflow/monthly?yearMonth=' + month, sender),
                         lambda x: x[0] == 200 and x[1]['revision'] > before['revision'], 55)
    record('전월 늦은 거래 자동 revision 증가', revised and revised[0] == 200 and revised[1]['revision'] > before['revision'], str(revised[1] if revised else None))
    if revised and revised[0] == 200:
        rows = await poll(lambda: query('work', 'select revision,total_expense from monthly_cashflow where user_id=%s and year_month=%s', (sender['id'], month)),
                          lambda x: x and x[0]['revision'] == revised[1]['revision'])
        record('전월 수정 이벤트 Work 반영', bool(rows) and rows[0]['revision'] == revised[1]['revision'] and Decimal(str(rows[0]['total_expense'])) == Decimal(str(revised[1]['expenseAmount'])), str(rows))
    # 계좌 해지는 상태 변경 시험이며 반전 거래가 아니다.
    status, closed = await mock('DELETE', '/api/accounts/' + receiver['number'], receiver)
    record('Mock 계좌 해지', status == 200, f'HTTP={status}')
    await account_detail(receiver, True)
    balance = await AssetClient().get_current_balance(int(receiver['id']))
    record('CLOSED 계좌 잔액 합산 제외', balance.status == BalanceStatus.NOT_LINKED, f'status={balance.status}')


async def multimonth(users):
    sender = dict(users[0])
    opened = await call('다개월 전용 계좌 100만원 개설', 'POST', '/api/v1/banking/accounts', sender,
        {'ci': sender['ci'], 'userName': '테스트 사용자', 'phoneNumber': '01000000000', 'bankCode': '001',
         'productName': 'E2E-MULTI', 'initialBalance': 1000000}, want=201)
    sender['account'] = opened['accountId']
    await poll(lambda: account_detail(sender), lambda x: x[0] == 200)
    await account_detail(sender, True)
    month = (date.today().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    before = await call('다개월 시험 전월 기존 revision', 'GET', '/api/v1/assets/cashflow/monthly?yearMonth=' + month, sender)
    body = {'fixtureRunId': 'e2e-rich-three-months', 'ownerCi': sender['ci'], 'bankCode': '001',
            'productName': 'E2E-MULTI', 'months': 3, 'persona': 'BALANCED_STUDENT'}
    headers = {'X-Fixture-Token': os.environ.get('FIXTURE_TOKEN', 'moaje-local-fixture-token')}
    status, fixture = await request('POST', '/internal/test-fixtures/personas', body=body, headers=headers, base='http://mock-banking:8081')
    record('다개월 fixture 재시험(충분한 초기 잔액)', status == 200 and fixture.get('createdTransactionCount') == 24, f'HTTP={status}, 생성건수={fixture.get("createdTransactionCount")}')
    status, again = await request('POST', '/internal/test-fixtures/personas', body=body, headers=headers, base='http://mock-banking:8081')
    record('fixture 재요청 중복 방지', status == 200 and again.get('createdTransactionCount') == 0 and again.get('skippedTransactionCount') == 24, f'HTTP={status}, 생성={again.get("createdTransactionCount")}, 생략={again.get("skippedTransactionCount")}')
    refreshed = await account_detail(sender, True)
    record('다개월 snapshot 최신 잔액', refreshed[0] == 200 and Decimal(str(refreshed[1].get('balance', -1))) == 539500, f'HTTP={refreshed[0]}, balance={refreshed[1].get("balance")}')
    history = await query('asset', 'select count(*) n from transaction_history where account_id=%s', (sender['account'],))
    record('다개월 snapshot 24건 수집', history[0]['n'] == 24, str(history))
    revised = await poll(lambda: request('GET', '/api/v1/assets/cashflow/monthly?yearMonth=' + month, sender),
                         lambda x: x[0] == 200 and x[1]['revision'] > before['revision'], 50)
    ok = revised and revised[0] == 200 and revised[1]['revision'] > before['revision']
    record('전월 자동 revision 재시험', ok, str(revised[1] if revised else None))
    if ok:
        rows = await poll(lambda: query('work', 'select revision,total_expense from monthly_cashflow where user_id=%s and year_month=%s', (sender['id'], month)),
                          lambda x: x and x[0]['revision'] == revised[1]['revision'])
        record('전월 수정 Work 동기화', rows and rows[0]['revision'] == revised[1]['revision'] and Decimal(str(rows[0]['total_expense'])) == Decimal(str(revised[1]['expenseAmount'])), str(rows))


async def final_checks(users, replay_only=False):
    from app.grpc.asset_client import AssetClient, BalanceStatus
    from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
    from app.grpc.events import asset_events_pb2 as events
    sender, receiver, _ = users
    month = (date.today().replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
    rows = await query('work', 'select revision,total_expense from monthly_cashflow where user_id=%s and year_month=%s', (sender['id'], month))
    record('전월 revision 2 Work DB 최종 확인', len(rows) == 1 and rows[0]['revision'] == 2 and rows[0]['total_expense'] == Decimal('153500'), str(rows))
    transfer_rows = await query('banking', 'select count(*) n from banking_transfer')
    record('Controller 실패 후 금융거래 행 생성 없음', transfer_rows[0]['n'] == 0, str(transfer_rows))
    # 실제 Asset이 발행했던 거래 성공 본문을 그대로 재발행한 뒤 새 eventId로도 재발행한다.
    consumer = AIOKafkaConsumer(bootstrap_servers='kafka:29092', group_id=None, enable_auto_commit=False)
    producer = AIOKafkaProducer(bootstrap_servers='kafka:29092')
    monitor = AIOKafkaConsumer(bootstrap_servers='kafka:29092', group_id='moaje-work', enable_auto_commit=False)
    await consumer.start()
    await producer.start()
    await monitor.start()
    async def await_commit(metadata):
        tp = TopicPartition(metadata.topic, metadata.partition)
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            offset = await monitor.committed(tp)
            if offset is not None and offset >= metadata.offset + 1:
                return
            await asyncio.sleep(.25)
        raise TimeoutError('Work group offset did not advance')
    try:
        parts = consumer.partitions_for_topic('transaction_succeeded_events')
        consumer.assign([TopicPartition('transaction_succeeded_events', p) for p in parts])
        await consumer.seek_to_beginning()
        batch = await consumer.getmany(timeout_ms=2000, max_records=500)
        messages = [record for records in batch.values() for record in records]
        original = next((m for m in messages if events.TransactionSucceededEvent.FromString(m.value).user_id == sender['id']), None)
        before = (await query('work', 'select count(*) n from fds_inference_log where user_id=%s', (sender['id'],)))[0]['n']
        record('실제 Asset Kafka 본문 획득', original is not None, '스냅샷으로 생성된 실제 성공 이벤트 사용')
        if original:
            event = events.TransactionSucceededEvent.FromString(original.value)
            await producer.send_and_wait(original.topic, value=original.value, key=original.key)
            event.event_id = 'E2E-CHANGED-EVENT-ID'
            metadata = await producer.send_and_wait(original.topic, value=event.SerializeToString(), key=original.key)
            await await_commit(metadata)
            after = (await query('work', 'select count(*) n from fds_inference_log where user_id=%s', (sender['id'],)))[0]['n']
            record('Work 실제 성공 이벤트 중복 방지(offset 확인)', before == after, f'행 수 before={before}, after={after}; 마지막 재발행 offset 처리 확인')
        from app.grpc.common.resources_pb2 import Money
        lower = events.MonthlyCashflowAggregatedEvent(event_id='E2E-OLD-REVISION', user_id=sender['id'], year_month=month,
            revision=1, expense_amount=Money(amount=1, currency='KRW'), calculated_at='2026-10-10T00:00:00Z')
        metadata = await producer.send_and_wait('moaje.asset.monthly-cashflow-aggregated', value=lower.SerializeToString(), key=sender['id'].encode())
        await await_commit(metadata)
        rows = await query('work', 'select revision,total_expense from monthly_cashflow where user_id=%s and year_month=%s', (sender['id'], month))
        record('낮은 revision 재발행 시 최신 집계 유지', rows[0]['revision'] == 2 and rows[0]['total_expense'] == Decimal('153500'), str(rows))
    finally:
        await consumer.stop()
        await producer.stop()
        await monitor.stop()
    if replay_only:
        return
    status, _ = await mock('DELETE', '/api/accounts/' + receiver['number'], receiver)
    record('Mock 계좌 해지', status == 200, f'HTTP={status}')
    await account_detail(receiver, True)
    balance = await AssetClient().get_current_balance(int(receiver['id']))
    record('CLOSED 계좌 합산 제외 RPC', balance.status == BalanceStatus.NOT_LINKED, balance.status.name)
    await call('CLOSED 계좌 일별 계산 거절', 'POST', '/api/v1/assets/cashflow/daily-limit', receiver,
        {'expectedIncome': 0, 'fixedExpenses': 0, 'eventBuffer': 0, 'daysUntilNextPayday': 10, 'snapshotDate': str(date.today())}, want=409)


async def main():
    global CLIENT, ROWS
    if REPORT.exists():
        ROWS = json.loads(REPORT.read_text())
    start_row = len(ROWS)
    async with httpx.AsyncClient(timeout=70) as client:
        CLIENT = client
        phase = sys.argv[1] if len(sys.argv) > 1 else 'normal'
        try:
            if phase == 'normal':
                users = await setup()
                await normal(users)
                await work_apis(users)
            else:
                users = json.loads(STATE.read_text())
                if phase == 'timeout':
                    await timeout(users)
                elif phase == 'auth':
                    await auth_end(users)
                elif phase == 'independent':
                    await independent(users)
                elif phase == 'work':
                    await work_apis(users)
                elif phase == 'verify-consumed':
                    uid = users[0]['id']
                    month = date.today().strftime('%Y-%m')
                    for table, extra, expected in [('monthly_cashflow', '', 1), ('category_cashflow', " and category_code='CAFE'", 1), ('fds_inference_log', '', 121)]:
                        rows = await query('work', 'select * from ' + table + ' where user_id=%s' + extra, (uid,))
                        ok = len(rows) == expected
                        if table == 'monthly_cashflow':
                            ok = ok and Decimal(str(rows[0]['total_expense'])) == 121
                        if table == 'category_cashflow':
                            ok = ok and Decimal(str(rows[0]['amount'])) == 121
                        record('실제 Outbox→Work DB 재검증 ' + table, ok, f'행 수={len(rows)}, 기대={expected}; 집계 금액 121원 검증')
                elif phase == 'extended':
                    await extended(users)
                elif phase == 'multimonth':
                    await multimonth(users)
                elif phase == 'final':
                    await final_checks(users)
                elif phase == 'replay':
                    await final_checks(users, replay_only=True)
                elif phase == 'catalog':
                    catalog = {}
                    for name, url in [('Auth', 'http://auth:8000/openapi.json'), ('Work', 'http://work:8084/openapi.json'),
                                      ('Banking', 'http://banking:8080/v3/api-docs'), ('Asset', 'http://asset:8082/v3/api-docs')]:
                        response = await CLIENT.get(url)
                        response.raise_for_status()
                        catalog[name] = [{'method': method.upper(), 'path': path, 'summary': op.get('summary', '')}
                                         for path, methods in response.json()['paths'].items() for method, op in methods.items()
                                         if method in ('get', 'post', 'put', 'patch', 'delete')]
                        record('실행 OpenAPI 명세 ' + name, True, f'등록 API={len(catalog[name])}')
                    Path('/tmp/moaje-e2e-catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as exc:
            record('시험 단계 중단 ' + phase, False, type(exc).__name__ + ': ' + str(exc)[:160])
    return 1 if any(row['status'] == 'FAIL' for row in ROWS[start_row:]) else 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
