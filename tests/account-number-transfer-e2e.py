"""개설 응답만으로 송금하고, 목록은 마스킹·조회는 accountId를 사용하는지 검증한다."""
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bank_info', ROOT / 'bank-information-e2e.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
b.REPORT = ROOT.parent / 'docs/account-number-transfer-test-20261014.json'


def mask(number):
    return '*' * (len(number) - 4) + number[-4:]


def sql(database, statement):
    return subprocess.check_output([
        'docker', 'exec', '-e', 'MYSQL_PWD=moaje_' + database, 'moaje-bankinfo-20261014-' + database + '-mysql',
        'mysql', '-N', '-B', '-umoaje_' + database, 'moaje_' + database, '-e', statement,
    ], text=True).strip()


def main():
    b.wait_for(lambda: b.request('GET', '/docs/asset/v3/api-docs'), lambda r: r[0] == 200)
    sender, receiver = b.user(), b.user()
    a = b.open_account(sender, '088', '검증은행 A', 20000)
    c = b.open_account(receiver, '004', '검증은행 B', 0)
    for opened in [a, c]:
        b.check('개설 응답의 계좌번호·내부 ID 구분 ' + opened['bankCode'],
                isinstance(opened['accountId'], str) and isinstance(opened['accountNumber'], str)
                and opened['accountNumber'].isdigit() and opened['accountId'] != opened['accountNumber'],
                '실제 계좌번호와 내부 accountId가 서로 다른 문자열')
        b.check('개설 응답의 마스킹 ' + opened['bankCode'], opened['maskedAccountNumber'] == mask(opened['accountNumber']),
                '끝 네 자리만 표시')
    _, listed = b.wait_for(lambda: b.request('GET', '/api/v1/assets/accounts', token=sender['token']),
                           lambda r: r[0] == 200 and len(r[1]) == 1)
    selected = listed[0]
    b.check('목록의 ID·은행 정보·마스킹 연결', selected['accountId'] == a['accountId']
            and selected['bankCode'] == '088' and selected['maskedAccountNumber'] == mask(a['accountNumber']),
            '목록 선택 값은 accountId, 화면 표시 값은 maskedAccountNumber')
    b.check('목록에 원번호 없음', 'accountNumber' not in selected and a['accountNumber'] not in json.dumps(selected),
            '마스킹 필드만 제공')

    path = f'/api/v1/assets/accounts/{selected["accountId"]}'
    code, detail = b.request('GET', path + '/detail', token=sender['token'])
    b.check('선택한 accountId로 상세 조회', code == 200 and detail['accountId'] == selected['accountId']
            and detail['accountNumber'] == a['accountNumber']
            and 'displayAccountNumber' not in detail and 'maskedAccountNumber' not in detail, f'HTTP {code}; 전체 번호만 제공')
    b.check('상세 HTTP 캐시 금지', any(k.lower() == 'cache-control' and v == 'no-store' for k, v in b.LAST_RESPONSE_HEADERS.items()),
            'Cache-Control: no-store (HTTP 헤더 이름은 대소문자를 구분하지 않음)')
    cached = subprocess.check_output(['docker', 'exec', 'moaje-bankinfo-20261014-redis', 'redis-cli', '--raw',
                                     'GET', 'asset:account-detail:' + a['accountId']], text=True)
    b.check('Redis 상세 캐시에 원번호 없음', a['accountNumber'] not in cached and json.loads(cached)['accountNumber'] is None,
            '캐시의 accountNumber=null')
    for token, expected, label in [(receiver['token'], 400, '타인 JWT'), (None, 401, 'JWT 누락'), ('invalid-token', 401, 'JWT 변조')]:
        code, _ = b.request('GET', path + '/detail', token=token)
        b.check('상세 인증 거절 ' + label, code == expected, f'HTTP {code}')
    code, _ = b.request('GET', f'/api/v1/assets/accounts/{a["accountNumber"]}/detail', token=sender['token'])
    b.check('계좌번호를 조회 ID로 사용하면 찾지 못함', code == 404, f'HTTP {code}; 계좌번호 자동 변환 없음')
    code, _ = b.request('GET', '/api/v1/assets/accounts/detail?accountNumber=' + a['accountNumber'], token=sender['token'])
    b.check('accountId 없는 상세 조회 경로 없음', code == 404, f'HTTP {code}')

    body = {'withdrawalAccountId': selected['accountId'], 'depositBankCode': c['bankCode'],
            'depositAccountNumber': c['accountNumber'], 'amount': 1000, 'currency': 'KRW'}
    missing_id = {k: v for k, v in body.items() if k != 'withdrawalAccountId'}
    missing_id['withdrawalAccountNumber'] = a['accountNumber']
    code, _ = b.request('POST', '/api/v1/banking/transfers', missing_id, sender['token'], headers={'Idempotency-Key': 'missing-account-id'})
    b.check('출금 계좌번호만으로 송금 불가', code == 400, f'HTTP {code}')
    b.check('거절 요청은 거래를 생성하지 않음', sql('banking', 'SELECT COUNT(*) FROM banking_transfer;') == '0', '거래 Row 0건')
    code, _ = b.request('POST', '/api/v1/banking/transfers', body, receiver['token'], headers={'Idempotency-Key': 'foreign-account-id'})
    b.check('다른 JWT 사용자에게 출금 권한 없음', code == 403, f'HTTP {code}')
    code, result = b.request('POST', '/api/v1/banking/transfers', body, sender['token'], headers={'Idempotency-Key': 'account-id-transfer'})
    b.check('개설 응답만으로 실제 송금 성공', code == 200 and result['status'] == 'COMPLETED', f'HTTP {code}; COMPLETED')
    # 동일 요청에는 같은 키를 재사용해야 계정계가 중복으로 출금하지 않는다.
    code, repeated = b.request('POST', '/api/v1/banking/transfers', body, sender['token'], headers={'Idempotency-Key': 'account-id-transfer'})
    b.check('같은 송금 재시도는 같은 거래', code == 200 and repeated['transferId'] == result['transferId'], '동일 transferId')
    for owner, opened, expected in [(sender, a, 19000), (receiver, c, 1000)]:
        code, refreshed = b.wait_for(lambda: b.request('POST', f'/api/v1/assets/accounts/{opened["accountId"]}/refresh', token=owner['token']),
                                     lambda r: r[0] == 200 and r[1]['balance'] == expected)
        b.check('송금 후 잔액·전체번호 ' + opened['bankCode'], refreshed['balance'] == expected
                and refreshed['accountNumber'] == opened['accountNumber'], f'잔액 {expected}원, 본인 원번호 일치')
    code, page = b.request('GET', path + '/transactions', token=sender['token'])
    b.check('선택 계좌 거래목록', code == 200 and len(page['transactions']) == 1 and page['transactions'][0]['amount'] == 1000,
            '송금 이력 한 건')
    transaction_id = page['transactions'][0]['transactionId']
    code, _ = b.request('GET', path + f'/{transaction_id}/transaction', token=sender['token'])
    b.check('accountId·transactionId로 단건 조회', code == 200, f'HTTP {code}')
    code, _ = b.request('GET', path + '/transactions', token=receiver['token'])
    b.check('타인 거래내역 접근 차단', code == 403, f'HTTP {code}')

    # 과거 계좌에 마스킹 값이 없던 상황만 재현한다. 원장 거래를 직접 조작하지 않는다.
    sql('asset', f'UPDATE account SET masked_account_number=NULL WHERE id={int(a["accountId"])};')
    code, refreshed = b.request('POST', path + '/refresh', token=sender['token'])
    _, restored_list = b.request('GET', '/api/v1/assets/accounts', token=sender['token'])
    b.check('기존 계좌의 마스킹을 스냅샷으로 보충', code == 200 and restored_list[0]['maskedAccountNumber'] == mask(a['accountNumber']),
            'Mock → Banking gRPC → Asset 복구')

    # Outbox와 실제 Kafka 레코드의 바이트를 확인한다. 원번호는 결과 파일에 출력하지 않는다.
    payloads = sql('banking', "SELECT HEX(payload) FROM banking_outbox WHERE event_type='AccountCreatedEvent';")
    data = b''.join(bytes.fromhex(line) for line in payloads.splitlines())
    b.check('계좌 생성 Outbox에는 원번호 없음', all(x['accountNumber'].encode() not in data for x in [a, c])
            and all(mask(x['accountNumber']).encode() in data for x in [a, c]), '원번호 미포함, 마스킹 포함')
    records = subprocess.run(['docker', 'exec', 'moaje-bankinfo-20261014-kafka', 'kafka-console-consumer',
                              '--bootstrap-server', 'localhost:29092', '--topic', 'account_created_events',
                              '--from-beginning', '--max-messages', '2', '--timeout-ms', '15000'], capture_output=True)
    b.check('실제 Kafka 이벤트에도 원번호 없음', records.returncode == 0
            and all(x['accountNumber'].encode() not in records.stdout for x in [a, c])
            and all(mask(x['accountNumber']).encode() in records.stdout for x in [a, c]), 'Kafka 원본 바이트 확인')


if __name__ == '__main__':
    main()
