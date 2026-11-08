from __future__ import annotations

import copy
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

GATEWAY_URL = os.getenv('GATEWAY_URL', 'http://gateway:8080').rstrip('/')
MOCK_BANKING_URL = os.getenv('MOCK_BANKING_URL', 'http://mock-banking:8081').rstrip('/')
FIXTURE_ADMIN_TOKEN = os.environ['FIXTURE_ADMIN_TOKEN']
PORT = int(os.getenv('PORT', '8090'))
DATA_DIR = Path(os.getenv('DATA_DIR', '/data'))
INDEX_HTML = (Path(__file__).parent / 'static' / 'index.html').read_bytes()
BANKS = {'004': 'KB국민은행', '088': '신한은행', '090': '카카오뱅크', '092': '토스뱅크'}
PERSONAS = {'BALANCED_STUDENT', 'CAFE_AND_DINING', 'COMMUTER', 'STUDY_FOCUSED', 'NEW_USER', 'ZERO_BALANCE'}
# 여러 작업이 동시에 가입·과거 거래 생성에 끼어들지 않도록 로컬 도구는 한 작업씩 실행한다.
# 작업 결과를 볼륨에 기록하여 브라우저를 닫아도 진행 상황과 테스트 로그인 정보를 다시 볼 수 있다.
LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=1)
JOBS = {}
RESET_AGENT_URL = os.getenv('RESET_AGENT_URL', 'http://reset-agent:8091')
RESET_AGENT_TOKEN = os.getenv('RESET_AGENT_TOKEN', FIXTURE_ADMIN_TOKEN)
RESET_CSRF = secrets.token_urlsafe(32)


def reset_state():
    state = request_json('GET', RESET_AGENT_URL + '/status', headers={'X-Reset-Token':RESET_AGENT_TOKEN})
    # 성공한 초기화와 같은 실행 이력만 지운다. 실패 시에는 부분 삭제 상태를 확인할 수 있게 보존한다.
    # 별도 표식을 저장해 같은 완료 응답을 반복 조회해도 새로 만든 페르소나를 지우지 않는다.
    if state['status'] == 'SUCCEEDED':
        marker = DATA_DIR / 'last-reset.txt'
        with LOCK:
            if not marker.exists() or marker.read_text() != state['id']:
                JOBS.clear()
                persist()
                marker.write_text(state['id'])
    return state


class UpstreamError(RuntimeError):
    def __init__(self, method, url, status):
        self.status = status
        super().__init__(f'{method} {url.split("?")[0]} → HTTP {status}. 서비스 로그를 확인해주세요.')


def request_json(method, url, body=None, headers=None):
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    request = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json', **(headers or {})}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        # 오류 본문에 개인정보나 토큰이 섞일 수 있어 저장·브라우저 노출을 하지 않는다.
        raise UpstreamError(method, url, error.code) from None
    except urllib.error.URLError:
        raise RuntimeError('서비스에 연결하지 못했습니다. 컨테이너 실행 상태를 확인해주세요.') from None


def persist():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp = DATA_DIR / 'runs.tmp'
    temp.write_text(json.dumps(JOBS, ensure_ascii=False), encoding='utf-8')
    temp.replace(DATA_DIR / 'runs.json')


def update(job_id, **values):
    with LOCK:
        JOBS[job_id].update(values)
        persist()


def load_jobs():
    global JOBS
    path = DATA_DIR / 'runs.json'
    if path.exists():
        JOBS = json.loads(path.read_text(encoding='utf-8'))
        for job in JOBS.values():
            if job['status'] in ('QUEUED', 'RUNNING'):
                job.update(status='FAILED', stage='실행 중단', error='콘솔이 재시작되어 중단됐습니다. 일부 데이터가 남을 수 있으며 자동 재생성하지 않습니다.')
        persist()


def validate(body):
    persona = body.get('persona', 'BALANCED_STUDENT')
    months = body.get('months', 3)
    count = body.get('transactionsPerMonth', 40)
    bank = body.get('bankCode', '004')
    balance = body.get('initialBalance', 5000000)
    if persona not in PERSONAS or bank not in BANKS:
        raise ValueError('지원하지 않는 페르소나 또는 은행입니다.')
    if type(months) is not int or not 1 <= months <= 6:
        raise ValueError('기간은 1~6개월이어야 합니다.')
    if type(count) is not int or count not in (8, 40, 80):
        raise ValueError('월별 거래 건수는 8·40·80건 중 선택해주세요.')
    if type(balance) is not int or not 0 <= balance <= 50000000:
        raise ValueError('초기 잔액은 0~5천만 원의 정수여야 합니다.')
    expense = {'BALANCED_STUDENT':153500, 'CAFE_AND_DINING':200500, 'COMMUTER':189500, 'STUDY_FOCUSED':220500}.get(persona, 0) * (count // 8) * months
    if balance < expense:
        raise ValueError(f'예상 출금 합계는 {expense:,}원입니다. 초기 잔액을 늘려주세요.')
    return dict(persona=persona, months=months, transactionsPerMonth=count, bankCode=bank, initialBalance=0 if persona == 'ZERO_BALANCE' else balance)


def login(result):
    response = request_json('POST', f'{GATEWAY_URL}/api/v1/auth/login', {'phone_number':result['phoneNumber'], 'pin':result['pin'], 'device_info':'test-fixture-console'})
    return {'Authorization': 'Bearer ' + response['data']['access_token']}


def inspect_account(result, authorization):
    if not result.get('accountId'):
        return result
    base = f'{GATEWAY_URL}/api/v1/assets/accounts/{result["accountId"]}'
    detail = request_json('POST', base + '/refresh', headers=authorization)
    result['balance'] = detail['balance']
    result['syncStatus'] = detail['syncStatus']
    result['aggregates'] = []
    for month in result['months']:
        monthly = request_json('GET', f'{GATEWAY_URL}/api/v1/assets/cashflow/monthly?yearMonth={month}', headers=authorization)
        category = request_json('GET', f'{GATEWAY_URL}/api/v1/assets/cashflow/category?yearMonth={month}', headers=authorization)
        result['aggregates'].append({'yearMonth':month, 'monthly':monthly, 'categories':category['categories']})
    # 첫 화면에서 50건씩 실제 API로 넘어가는지 확인한다. DB 직접 조회로 건수를 꾸미지 않는다.
    seen, page_sizes, cursor = set(), [], None
    for _ in range(15):
        url = base + '/transactions' + (f'?lastTransactionId={cursor}' if cursor else '')
        page = request_json('GET', url, headers=authorization)
        ids = [str(item['transactionId']) for item in page['transactions']]
        if seen.intersection(ids):
            raise RuntimeError('페이지 사이에 중복 거래가 발견됐습니다.')
        seen.update(ids)
        page_sizes.append(len(ids))
        if not page['hasNext']:
            break
        next_cursor = str(page['nextCursor'])
        if next_cursor == cursor:
            raise RuntimeError('거래내역 커서가 진행되지 않습니다.')
        cursor = next_cursor
    else:
        raise RuntimeError('거래내역 페이지가 예상 범위를 초과했습니다.')
    result['pageSizes'] = page_sizes
    result['visibleTransactionCount'] = len(seen)
    if len(seen) < result.get('createdTransactionCount', 0):
        raise RuntimeError('생성 거래보다 Asset 거래내역이 적습니다. 자동 생성은 반복하지 말고 계좌 갱신·집계 조회로 다시 확인해주세요.')
    result['checkedAt'] = datetime.now(timezone.utc).isoformat()
    return result


def create(job_id, options):
    suffix = uuid.uuid4().hex
    result = dict(fixtureRunId=job_id, persona=options['persona'], phoneNumber=f'010{secrets.randbelow(100000000):08d}', pin='123456', months=[], aggregates=[], createdTransactionCount=0)
    update(job_id, result=result, stage='회원가입', status='RUNNING')
    register = request_json('POST', f'{GATEWAY_URL}/api/v1/auth/register', {'phone_number':result['phoneNumber'], 'name':'시연용 대학생', 'email':f'fixture-{suffix}@moaje.test', 'pin':result['pin'], 'pin_confirm':result['pin'], 'terms_agreed':True, 'privacy_agreed':True, 'terms_version':'local-test-v1', 'privacy_version':'local-test-v1'})
    result['userId'] = str(register['data']['user_id'])
    update(job_id, result=copy.deepcopy(result), stage='로그인')
    auth = login(result)
    if options['persona'] == 'NEW_USER':
        return result
    update(job_id, stage='계좌 개설')
    ci, product = f'TEST-CI-{suffix}', f'MOAJE 시연 {suffix[:8]}'
    account = request_json('POST', f'{GATEWAY_URL}/api/v1/banking/accounts', {'ci':ci, 'userName':'시연용 대학생', 'phoneNumber':result['phoneNumber'], 'bankCode':options['bankCode'], 'bankName':BANKS[options['bankCode']], 'productName':product, 'initialBalance':options['initialBalance']}, auth)
    result.update(accountId=str(account['accountId']), accountNumber=account['accountNumber'], bankName=BANKS[options['bankCode']], bankCode=options['bankCode'])
    update(job_id, result=copy.deepcopy(result), stage='Mock 거래 생성')
    if options['persona'] != 'ZERO_BALANCE':
        fixture = request_json('POST', f'{MOCK_BANKING_URL}/internal/test-fixtures/personas', {'fixtureRunId':job_id, 'ownerCi':ci, 'bankCode':options['bankCode'], 'productName':product, 'persona':options['persona'], 'months':options['months'], 'transactionsPerMonth':options['transactionsPerMonth']}, {'X-Fixture-Token':FIXTURE_ADMIN_TOKEN})
        result.update(months=fixture['months'], createdTransactionCount=fixture['createdTransactionCount'])
    else:
        result['months'] = [datetime.now(timezone.utc).strftime('%Y-%m')]
    update(job_id, result=copy.deepcopy(result), stage='Asset 계좌 반영 대기')
    for _ in range(30):
        try:
            request_json('GET', f'{GATEWAY_URL}/api/v1/assets/accounts/{result["accountId"]}/detail', headers=auth)
            break
        except UpstreamError as error:
            if error.status not in (400, 404, 502, 503):
                raise
            time.sleep(1)
    else:
        raise RuntimeError('30초 안에 Asset 계좌가 반영되지 않았습니다. 생성된 로그인 정보를 보존했습니다.')
    update(job_id, stage='스냅샷 반영 · 월별 집계 · 페이지 확인')
    return inspect_account(result, auth)


def worker(job_id, refresh=False):
    try:
        with LOCK:
            job = copy.deepcopy(JOBS[job_id])
        update(job_id, status='RUNNING', error=None)
        if refresh:
            update(job_id, stage='스냅샷 갱신 · 저장된 집계 조회')
            result = inspect_account(job['result'], login(job['result']))
        else:
            result = create(job_id, job['options'])
        update(job_id, status='SUCCEEDED', stage='완료', result=result)
    except Exception as error:
        update(job_id, status='FAILED', error=str(error), stage='중단 · 일부 데이터가 생성됐을 수 있습니다')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(INDEX_HTML)
        elif self.path == '/health':
            self.write_json(200, {'status':'UP'})
        elif self.path == '/api/runs':
            try:
                reset = reset_state()
            except Exception:
                reset = {'status':'UNAVAILABLE','stage':'초기화 서비스 연결 확인 필요'}
            with LOCK:
                jobs = copy.deepcopy(list(JOBS.values()))
            self.write_json(200, {'runs': list(reversed(jobs)), 'reset':reset, 'resetToken':RESET_CSRF})
        else:
            self.write_json(404, {'message':'Not found'})

    def do_POST(self):
        # localhost 도구라도 외부 웹사이트가 브라우저를 통해 데이터 생성을 시키지 못하게 한다.
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + self.headers.get('Host', ''):
            self.write_json(403, {'message':'동일한 로컬 페이지에서만 실행할 수 있습니다.'})
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self.write_json(415, {'message':'JSON 요청만 지원합니다.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError('요청 크기가 올바르지 않습니다.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError('JSON 객체가 필요합니다.')
            with LOCK:
                if any(j['status'] in ('RUNNING', 'QUEUED') for j in JOBS.values()):
                    self.write_json(409, {'message':'현재 작업이 끝난 뒤 실행해주세요.'})
                    return
                reset = reset_state()
                if self.path == '/api/reset':
                    if not secrets.compare_digest(self.headers.get('X-Reset-Confirm',''), RESET_CSRF) or body.get('confirmation') != '전체 초기화':
                        self.write_json(400, {'message':'삭제 범위를 확인하고 전체 초기화를 입력해주세요.'})
                        return
                    if reset['status'] == 'RUNNING':
                        self.write_json(409, {'message':'초기화가 진행 중입니다.'})
                        return
                    state = request_json('POST', RESET_AGENT_URL + '/reset', {}, {'X-Reset-Token':RESET_AGENT_TOKEN})
                    self.write_json(202, state)
                    return
                if reset['status'] in ('RUNNING','FAILED'):
                    self.write_json(409, {'message':'초기화를 완료한 뒤 데이터 생성·갱신을 실행해주세요.'})
                    return
                if self.path == '/api/personas':
                    options = validate(body)
                    job_id = 'fixture-' + uuid.uuid4().hex
                    JOBS[job_id] = dict(id=job_id, status='QUEUED', stage='대기', createdAt=datetime.now(timezone.utc).isoformat(), options=options, result=None)
                    persist()
                    POOL.submit(worker, job_id)
                elif self.path == '/api/refresh':
                    job_id = body.get('id')
                    if job_id not in JOBS or not JOBS[job_id].get('result', {}).get('userId'):
                        raise ValueError('조회할 생성 이력이 없습니다.')
                    if not JOBS[job_id]['result'].get('accountId'):
                        raise ValueError('신규 사용자 시나리오는 계좌가 없습니다.')
                    update(job_id, status='QUEUED')
                    POOL.submit(worker, job_id, True)
                else:
                    self.write_json(404, {'message':'Not found'})
                    return
            self.write_json(202, {'id':job_id})
        except (ValueError, TypeError) as error:
            self.write_json(400, {'message':str(error)})
        except Exception as error:
            self.write_json(503, {'message':str(error)})

    def write_json(self, status, value):
        payload = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        print(f'fixture-console: {format % args}')


if __name__ == '__main__':
    load_jobs()
    ThreadingHTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
