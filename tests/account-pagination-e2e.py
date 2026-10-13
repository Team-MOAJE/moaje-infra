"""계좌 선택 후 50건 커서 조회를 실제 Gateway·MySQL·Mock 스냅샷으로 검증한다."""
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bank_info', ROOT / 'bank-information-e2e.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
b.REPORT = ROOT.parent / 'docs/account-pagination-string-ids-test-20261014.json'


def account_number(owner, account):
    return subprocess.check_output([
        'docker', 'exec', 'moaje-bankinfo-20261014-mock-redis', 'redis-cli', '--raw', 'GET',
        '{banking}:account-owner:' + owner['ci'] + ':' + account['bankCode'] + ':test-' + account['bankCode'],
    ], text=True).strip()


def mock_token(owner):
    code, response = b.request('POST', '/oauth/2.0/token',
                              {'ci': owner['ci'], 'userName': '계좌 검증 사용자', 'phoneNumber': owner['phone']}, base=b.MOCK)
    assert code == 200
    return response['accessToken']


def seed(owner, account, token, begin, end, prefix):
    number = account_number(owner, account)
    # 원장을 직접 INSERT하지 않는다. 각 거래를 실제 Mock 출금 API로 생성한다.
    for index in range(begin, end):
        code, _ = b.request('POST', f'/api/accounts/{number}/withdrawals',
                             {'amount': 1, 'merchantName': prefix + str(index)}, token, base=b.MOCK, signed=True)
        assert code == 200, f'Mock 출금 실패: {index}, HTTP {code}'


def refresh(owner, account, total):
    return b.wait_for(
        lambda: b.request('POST', f'/api/v1/assets/accounts/{account["accountId"]}/refresh', token=owner['token']),
        lambda r: r[0] == 200 and r[1]['balance'] == account['balance'] - total,
    )[1]


def page(owner, account, cursor=None):
    suffix = '' if cursor is None else '?lastTransactionId=' + str(cursor)
    code, response = b.request('GET', f'/api/v1/assets/accounts/{account["accountId"]}/transactions' + suffix, token=owner['token'])
    assert code == 200
    return response


def scan(owner, account, total, sizes):
    code, detail = b.request('GET', f'/api/v1/assets/accounts/{account["accountId"]}/detail', token=owner['token'])
    first = page(owner, account)
    b.check(f'{total}건 HTTP ID·커서 타입', isinstance(detail['accountId'], str)
            and (first['nextCursor'] is None or isinstance(first['nextCursor'], str))
            and all(isinstance(r['transactionId'], str) for r in first['transactions']),
            '계좌 ID·거래 ID·커서는 문자열, 마지막 커서는 null')
    b.check(f'{total}건 상세와 첫 페이지 일치', code == 200 and detail['transactionHistory'] == first['transactions']
            and detail['hasNext'] == first['hasNext'] and detail['nextCursor'] == first['nextCursor'],
            f'첫 페이지 {len(first["transactions"])}건; 은행 {detail["bankCode"]}')
    b.check(f'{total}건 선택 계좌 은행 정보 유지', detail['bankCode'] == account['bankCode'] and detail['bankName'] == account['bankName'],
            f'{detail["bankCode"]} / {detail["bankName"]}')
    collected, actual_sizes, cursors = [], [], []
    current = first
    while True:
        rows = current['transactions']
        ids = [r['transactionId'] for r in rows]
        actual_sizes.append(len(rows))
        collected.extend(ids)
        b.check(f'{total}건 {len(actual_sizes)}페이지 정렬·계좌 분리', ids == sorted(ids, reverse=True)
                and all(r['merchantName'].startswith('A-') for r in rows),
                f'{len(rows)}건; ID 내림차순; A 계좌 거래만 포함')
        if not current['hasNext']:
            b.check(f'{total}건 마지막 페이지 종료', current['nextCursor'] is None, 'hasNext=false, nextCursor=null')
            break
        cursor = current['nextCursor']
        b.check(f'{total}건 {len(actual_sizes)}페이지 커서', bool(rows) and cursor == ids[-1] and cursor not in cursors,
                '마지막 거래 ID가 다음 커서이며 이전 커서를 반복하지 않음')
        cursors.append(cursor)
        current = page(owner, account, cursor)
        assert len(actual_sizes) < 10, '페이지 루프가 끝나지 않음'
    b.check(f'{total}건 페이지 크기', actual_sizes == sizes, f'expected={sizes}, actual={actual_sizes}')
    b.check(f'{total}건 전체 중복·누락 없음', len(collected) == total and len(set(collected)) == total,
            f'조회 {len(collected)}건, 고유 ID {len(set(collected))}건')
    b.check(f'{total}건 페이지 간 정렬', collected == sorted(collected, reverse=True), '전체 ID 내림차순')
    if collected:
        end = page(owner, account, collected[-1])
        b.check(f'{total}건 마지막 ID 이후 재요청', not end['transactions'] and not end['hasNext'] and end['nextCursor'] is None,
                '빈 배열, hasNext=false, nextCursor=null')
    return first, collected


def main():
    b.wait_for(lambda: b.request('GET', '/docs/asset/v3/api-docs'), lambda r: r[0] == 200)
    owner, other = b.user(), b.user()
    a = b.open_account(owner, '088', '검증은행 A', 10000)
    second = b.open_account(owner, '004', '검증은행 B', 10000)
    b.wait_for(lambda: b.request('GET', '/api/v1/assets/accounts', token=owner['token']), lambda r: r[0] == 200 and len(r[1]) == 2)
    scan(owner, a, 0, [0])
    token = mock_token(owner)
    seed(owner, second, token, 0, 7, 'B-')
    refresh(owner, second, 7)
    begin = 0
    for total, sizes in [(50, [50]), (51, [50, 1]), (100, [50, 50]), (123, [50, 50, 23])]:
        seed(owner, a, token, begin, total, 'A-')
        refresh(owner, a, total)
        first, all_ids = scan(owner, a, total, sizes)
        begin = total

    # MySQL 원본의 공개 이력 ID와 비교해 단순 개수 일치만으로 누락을 놓치지 않는다.
    raw = subprocess.check_output([
        'docker', 'exec', '-e', 'MYSQL_PWD=moaje_asset', 'moaje-bankinfo-20261014-asset-mysql',
        'mysql', '-N', '-B', '-umoaje_asset', 'moaje_asset', '-e',
        f'SELECT id FROM transaction_history WHERE account_id={int(a["accountId"])} AND visible_to_user=true ORDER BY id DESC;',
    ], text=True)
    expected_ids = [line for line in raw.splitlines() if line]
    b.check('123건 API와 MySQL 원본 ID 전부 일치', all_ids == expected_ids, '50+50+23건이 DB 원본의 동일 123개 ID와 일치')
    repeated = page(owner, a, first['nextCursor'])
    b.check('같은 커서 재요청 결과 유지', [r['transactionId'] for r in repeated['transactions']] == all_ids[50:100], '동일한 두 번째 50건 반환')
    b.check('다른 본인 계좌의 거래는 별도 조회', len(page(owner, second)['transactions']) == 7, 'B 계좌 7건이 A 계좌 123건에 섞이지 않음')

    # 사용자가 스크롤하는 중 새 거래가 생겨도 기존 커서 이하의 페이지는 그대로 이어져야 한다.
    seed(owner, a, token, 123, 124, 'A-')
    refresh(owner, a, 124)
    remaining, cursor = [], first['nextCursor']
    while cursor is not None:
        result = page(owner, a, cursor)
        remaining.extend(r['transactionId'] for r in result['transactions'])
        cursor = result['nextCursor']
    b.check('스크롤 도중 새 거래가 생겨도 기존 페이지 안정', all_ids[:50] + remaining == expected_ids,
            '새 거래는 다음 첫 페이지 조회에서 표시, 기존 123건은 중복·누락 없이 유지')
    b.check('첫 페이지 재조회에는 새 거래 포함', page(owner, a)['transactions'][0]['merchantName'] == 'A-123', '신규 거래가 첫 페이지에 표시됨')
    code, _ = b.request('GET', f'/api/v1/assets/accounts/{a["accountId"]}/transactions?lastTransactionId={first["nextCursor"]}', token=other['token'])
    b.check('다음 페이지도 타인 JWT 접근 차단', code == 403, f'HTTP {code}')

    # 실제 JavaScript JSON.parse로 앱과 같은 방식의 읽기를 검증한다.
    import os
    node = os.environ['MOAJE_TEST_NODE']
    original = {'accountId': a['accountId'], 'nextCursor': first['nextCursor'], 'transactionId': all_ids[0]}
    restored = json.loads(subprocess.check_output([
        node, '-e', 'let s="";process.stdin.on("data",d=>s+=d);process.stdin.on("end",()=>{const v=JSON.parse(s);if(!Object.values(v).every(x=>typeof x==="string"))process.exit(1);process.stdout.write(JSON.stringify(v));});',
    ], input=json.dumps(original), text=True))
    b.check('JavaScript JSON.parse 이후 식별자 정밀도 유지', restored == original, '실제 JavaScript에서 세 ID가 문자열로 유지됨')
    code, _ = b.request('GET', f'/api/v1/assets/accounts/{restored["accountId"]}/detail', token=owner['token'])
    b.check('JavaScript가 읽은 계좌 ID 재요청 성공', code == 200, f'HTTP {code}')
    restored_page = page(owner, a, restored['nextCursor'])
    b.check('JavaScript가 읽은 커서로 다음 페이지 유지', [r['transactionId'] for r in restored_page['transactions']] == all_ids[50:100], '두 번째 50건 정확히 일치')


if __name__ == '__main__':
    main()
