"""격리 환경 전용: 원거래 처리 후 응답만 지연해 UNKNOWN 복구를 재현한다."""
import json
import threading
import time
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

mode = {"delay_once": False, "forwarded": False, "transfer_posts": 0}
lock = threading.Lock()


class Proxy(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 인증정보와 요청 본문은 로그에 남기지 않는다.

    def handle_request(self):
        data = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        if self.path == '/__control':
            with lock:
                if self.command == 'POST':
                    mode.update(json.loads(data))
                result = json.dumps(mode).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(result)
            return
        headers = {k: v for k, v in self.headers.items() if k.lower() not in ('host', 'connection')}
        req = urllib.request.Request('http://mock-banking:8081' + self.path,
                                     data=data if self.command != 'GET' else None,
                                     headers=headers, method=self.command)
        try:
            response = urllib.request.urlopen(req, timeout=60)
        except urllib.error.HTTPError as error:
            response = error
        body = response.read()
        delay = False
        if self.path == '/api/transfers' and self.command == 'POST':
            with lock:
                mode['forwarded'] = True
                mode['transfer_posts'] += 1
                delay = mode['delay_once']
                mode['delay_once'] = False
        # Mock의 처리 결과를 받은 뒤 기다린다. 실패한 송금을 꾸미는 것이 아니다.
        if delay:
            time.sleep(35)
        self.send_response(response.status)
        self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    do_GET = handle_request
    do_POST = handle_request
    do_DELETE = handle_request


ThreadingHTTPServer(('0.0.0.0', 18081), Proxy).serve_forever()
