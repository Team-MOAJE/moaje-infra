#!/usr/bin/env bash
# 읽기 전용 기동 검사다. 사용자·거래·집계 데이터와 Kafka offset은 변경하지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose --profile apps config --quiet
docker compose --profile apps exec -T work python - <<'PY'
import json
import asyncio
import socket
import urllib.error
import urllib.request

def get(url):
    return urllib.request.urlopen(url, timeout=10)

health = json.load(get('http://127.0.0.1:8084/health'))
assert health['status'] == 'ok', health
assert health['components']['database']['status'] == 'ok', health
assert health['components']['redis']['status'] == 'ok', health
assert health['components']['asset_grpc_mtls']['status'] == 'ok', health
print('PASS: Work HTTP, MySQL, shared Redis')

with socket.create_connection(('127.0.0.1', 50051), timeout=3):
    print('PASS: Work gRPC port (not Asset mTLS interoperability)')

schema = json.load(get('http://gateway:8080/docs/work/openapi.json'))
assert '/api/v1/work/calendar/universities' in schema['paths'], schema.get('info')
ui = get('http://gateway:8080/docs/swagger-ui.html').read().decode()
assert '/docs/work/openapi.json' in ui
print('PASS: Gateway Work OpenAPI and integrated Swagger entry')

try:
    get('http://gateway:8080/api/v1/work/calendar/universities')
except urllib.error.HTTPError as error:
    assert error.code == 401, error.code
else:
    raise AssertionError('Work API accepted a request without JWT')
print('PASS: Gateway rejects unauthenticated Work API requests')

# 잔액 RPC에 빈 사용자 ID를 보내 데이터 생성 없이 실제 mTLS 연결을 확인한다.
# 정상 잔액과 계좌 오류는 별도의 work-asset-integration 검사에서 확인한다.
async def check_mtls():
    import grpc
    from app.grpc.asset_client import load_channel_credentials
    from app.grpc import asset_service_pb2, asset_service_pb2_grpc
    async with grpc.aio.secure_channel('asset:9090', load_channel_credentials()) as channel:
        await asyncio.wait_for(channel.channel_ready(), timeout=10)
        stub = asset_service_pb2_grpc.AssetServiceStub(channel)
        try:
            await stub.GetCurrentBalance(asset_service_pb2.GetCurrentBalanceRequest(user_id=''), timeout=5)
        except grpc.aio.AioRpcError as error:
            assert error.code() == grpc.StatusCode.INVALID_ARGUMENT, error
        else:
            raise AssertionError('Asset accepted an empty user ID unexpectedly')
    print('PASS: Work certificate -> Asset mTLS -> RPC validation (not balance compatibility)')
asyncio.run(check_mtls())
PY

# 로그인/회원가입 검사가 아니라 라우팅 검사다. Auth의 발급 함수로 테스트용 JWT를
# 메모리에서만 만들고 공용 학교 목록을 조회한다. 토큰 출력과 DB 사용자 생성은 하지 않는다.
docker compose --profile apps exec -T auth python - <<'PY'
import json
import urllib.request
from app.core.security import create_access_token

token, _ = create_access_token('1')
request = urllib.request.Request(
    'http://gateway:8080/api/v1/work/calendar/universities',
    headers={'Authorization': 'Bearer ' + token},
)
with urllib.request.urlopen(request, timeout=10) as response:
    assert response.status == 200
    schools = json.load(response)
assert isinstance(schools, list) and schools, 'Work initial school data missing'
print('PASS: Auth-signed test JWT -> Gateway -> Work -> MySQL school list')

# 타인의 user_id와 위조 내부 헤더는 Gateway를 거쳐도 본인으로 바뀌지 않아야 한다.
import urllib.error
for path in ('/api/v1/work/spending/2/schedules', '/api/v1/work/onboarding/2/profile'):
    request = urllib.request.Request(
        'http://gateway:8080' + path,
        headers={'Authorization': 'Bearer ' + token, 'X-Authenticated-User-Id': '2'},
    )
    try:
        urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as error:
        assert error.code == 403, (path, error.code)
    else:
        raise AssertionError('Cross-user request accepted: ' + path)
print('PASS: Cross-user path and spoofed internal header rejected')
PY
