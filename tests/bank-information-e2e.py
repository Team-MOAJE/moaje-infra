"""격리 Compose에서 계좌 목록 → 계좌 선택 → 거래내역과 소유권을 확인한다."""
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

GATEWAY = os.getenv('BANK_INFO_GATEWAY', 'http://127.0.0.1:19080')
MOCK = os.getenv('BANK_INFO_MOCK', 'http://127.0.0.1:19081')
REPORT = Path(__file__).resolve().parents[1] / 'docs/bank-information-test-20261014.json'
ROWS = []
LAST_RESPONSE_HEADERS = {}


def request(method, path, body=None, token=None, base=GATEWAY, headers=None, signed=False):
    global LAST_RESPONSE_HEADERS
    raw = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode() if body is not None else None
    hdr = {'Content-Type': 'application/json', **(headers or {})}
    if token:
        hdr['Authorization'] = 'Bearer ' + token
    if signed:
        hdr['X-Signature'] = hmac.new(os.environ['MOCK_HMAC'].encode(), raw or b'', hashlib.sha256).hexdigest()
    req = urllib.request.Request(base + path, data=raw, headers=hdr, method=method)
    try:
        response = urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        LAST_RESPONSE_HEADERS = dict(response.headers)
        data = response.read()
        return response.status, json.loads(data) if data else None


def check(name, condition, detail):
    # 인증 토큰과 개인정보는 보고서에 기록하지 않는다.
    row = {'name': name, 'status': 'PASS' if condition else 'FAIL', 'detail': detail}
    ROWS.append(row)
    REPORT.write_text(json.dumps(ROWS, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(row, ensure_ascii=False), flush=True)
    assert condition, name


def wait_for(fn, condition, seconds=120):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            last = fn()
            if condition(last):
                return last
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(1)
    raise AssertionError(f'응답 준비 시간 초과: {last[0] if last else "연결 실패"}')


def user():
    # SMS를 보내지 않는 모의 회원가입 입력이며 검증 종료 후 볼륨과 함께 삭제한다.
    phone = '010' + f'{secrets.randbelow(100_000_000):08d}'
    body = {'phone_number': phone, 'name': '계좌 검증 사용자', 'pin': '123456', 'pin_confirm': '123456',
            'terms_agreed': True, 'privacy_agreed': True, 'terms_version': 'test-v1', 'privacy_version': 'test-v1'}
    status, registered = request('POST', '/api/v1/auth/register', body)
    check('현행 Auth 회원가입', status == 201, f'HTTP {status}')
    status, login = request('POST', '/api/v1/auth/login', {'phone_number': phone, 'pin': '123456'})
    check('Auth 로그인', status == 200, f'HTTP {status}')
    return {'id': str(registered['data']['user_id']), 'token': login['data']['access_token'],
            'phone': phone, 'ci': 'TEST-BANK-' + secrets.token_hex(8)}


def open_account(owner, code, name, balance):
    body = {'ci': owner['ci'], 'userName': '계좌 검증 사용자', 'phoneNumber': owner['phone'],
            'bankCode': code, 'bankName': name, 'productName': 'test-' + code, 'initialBalance': balance}
    status, opened = request('POST', '/api/v1/banking/accounts', body, owner['token'])
    check('Banking 계좌 생성 ' + code,
          status == 201 and opened.get('bankCode') == code and opened.get('bankName') == name,
          f'HTTP {status}; bankCode={opened.get("bankCode")}; bankName={opened.get("bankName")}')
    return opened


def withdraw(owner, opened, amount):
    status, token = request('POST', '/oauth/2.0/token',
                            {'ci': owner['ci'], 'userName': '계좌 검증 사용자', 'phoneNumber': owner['phone']}, base=MOCK)
    assert status == 200
    account_id = opened['accountId']
    # 개설 응답의 계좌번호를 그대로 사용한다. 프런트와 달리 Redis를 직접 읽는 우회가 필요하지 않다.
    number = opened['accountNumber']
    status, account = request('POST', '/api/accounts/' + number + '/withdrawals',
                               {'amount': amount, 'merchantName': '검증 카페'}, token['accessToken'], base=MOCK, signed=True)
    check('Mock 계좌 은행 정보 ' + opened['bankCode'],
          status == 200 and account.get('bankCode') == opened['bankCode'] and account.get('bankName') == opened['bankName'],
          f'HTTP {status}; bankCode={account.get("bankCode")}')
    _, refreshed = wait_for(
        lambda: request('POST', f'/api/v1/assets/accounts/{account_id}/refresh', token=owner['token']),
        lambda result: result[0] == 200 and result[1].get('balance') == opened['balance'] - amount,
    )
    check('스냅샷 은행 정보 ' + opened['bankCode'],
          refreshed['bankCode'] == opened['bankCode'] and refreshed['bankName'] == opened['bankName'],
          'Mock → Banking gRPC → Asset Refresh 은행 정보 일치')


def main():
    wait_for(lambda: request('GET', '/docs/asset/v3/api-docs'), lambda r: r[0] == 200)
    owner, other = user(), user()
    accounts = [open_account(owner, '088', '검증은행 A', 70000), open_account(owner, '004', '검증은행 B', 20000)]
    foreign = open_account(other, '090', '검증은행 C', 9000)
    expected = {a['accountId']: a for a in accounts}
    status, listed = wait_for(lambda: request('GET', '/api/v1/assets/accounts', token=owner['token']),
                              lambda r: r[0] == 200 and len(r[1]) == 2)
    check('계좌 생성 이벤트의 은행 정보가 목록에 반영됨',
          all(row['accountId'] in expected and row['bankCode'] == expected[row['accountId']]['bankCode']
              and row['bankName'] == expected[row['accountId']]['bankName'] for row in listed),
          f'HTTP {status}; 본인 계좌 2건, 코드 088·004 및 이름 일치')
    check('목록에 타인 계좌가 없음', foreign['accountId'] not in [r['accountId'] for r in listed], '타인 계좌 제외')

    for opened, amount in zip(accounts, [1000, 2000]):
        withdraw(owner, opened, amount)
        account_id = opened['accountId']
        status, detail = request('GET', f'/api/v1/assets/accounts/{account_id}/detail', token=owner['token'])
        check('선택한 계좌 상세 ' + opened['bankCode'],
              status == 200 and detail['accountId'] == account_id and detail['bankCode'] == opened['bankCode']
              and detail['bankName'] == opened['bankName'] and detail['balance'] == opened['balance'] - amount,
              f'HTTP {status}; 은행 정보와 잔액 일치')
        status, history = request('GET', f'/api/v1/assets/accounts/{account_id}/transactions', token=owner['token'])
        transactions = history['transactions']
        check('선택한 계좌 거래내역 ' + opened['bankCode'],
              status == 200 and len(transactions) == 1 and transactions[0]['amount'] == amount,
              f'HTTP {status}; 해당 계좌 출금 {amount}원 한 건만 조회')
        tx_id = transactions[0]['transactionId']
        status, item = request('GET', f'/api/v1/assets/accounts/{account_id}/{tx_id}/transaction', token=owner['token'])
        check('선택한 거래 단건 조회 ' + opened['bankCode'], status == 200 and item['transactionId'] == tx_id,
              f'HTTP {status}; 동일 transactionId')

    for suffix, method in [('detail', 'GET'), ('transactions', 'GET'), ('refresh', 'POST')]:
        status, _ = request(method, f'/api/v1/assets/accounts/{accounts[0]["accountId"]}/{suffix}', token=other['token'])
        check('타인 계좌 접근 거절 ' + suffix, status == (400 if suffix in ('detail', 'refresh') else 403), f'HTTP {status}')
    first_id = accounts[0]['accountId']
    _, page = request('GET', f'/api/v1/assets/accounts/{first_id}/transactions', token=owner['token'])
    status, _ = request('GET', f'/api/v1/assets/accounts/{first_id}/{page["transactions"][0]["transactionId"]}/transaction', token=other['token'])
    check('타인 거래 단건 접근 거절', status == 404, f'HTTP {status}; 거래 존재 정보도 노출하지 않음')
    status, _ = request('GET', '/api/v1/assets/accounts')
    check('JWT 없는 목록 접근 거절', status == 401, f'HTTP {status}')
    status, forged = request('GET', '/api/v1/assets/accounts', token=other['token'],
                            headers={'X-Authenticated-User-Id': owner['id']})
    check('위조 사용자 헤더보다 검증된 JWT를 우선함',
          status == 200 and len(forged) == 1 and forged[0]['accountId'] == foreign['accountId'], f'HTTP {status}; 본인 계좌만 조회')


if __name__ == '__main__':
    main()
