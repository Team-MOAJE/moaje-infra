"""휴대폰 가입·회원 관리 경로 검증. 격리 Compose에서만 실행한다."""
import asyncio
import importlib.util
import json
import sys

import httpx

spec = importlib.util.spec_from_file_location('rerun', '/tests/rerun-e2e.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
b = r.b


async def check_auth():
    body = b.registration_body(4)
    registered = await b.call('회원 관리용 사용자 가입', 'POST', '/api/v1/auth/register', body=body, want=201)
    data = registered['data']
    user = {'id': str(data['user_id']), 'token': data['access_token'], 'refresh': data['refresh_token']}
    me = await b.call('Auth 내 정보 조회', 'GET', '/api/v1/auth/me', user)
    b.record('가입 응답과 내 정보의 사용자 일치', me['data']['user_id'] == user['id'], '문자열 사용자 ID 비교')
    updated = await b.call('Auth 이름·이메일 수정', 'PATCH', '/api/v1/auth/me', user,
                          {'name': '수정된 시험 사용자', 'email': 'e2e-profile@moaje.test'})
    b.record('수정한 프로필 반환', updated['data']['name'] == '수정된 시험 사용자' and
             updated['data']['email'] == 'e2e-profile@moaje.test', '이름과 이메일 비교')
    removed = await b.call('Auth 이메일 삭제', 'PATCH', '/api/v1/auth/me', user, {'email': None})
    b.record('이메일 null 저장', removed['data']['email'] is None, '선택 정보 삭제')

    # 잠금 해제는 refresh token과 PIN으로 수행하는 기능이다.
    # Gateway가 access token도 요구하면 만료된 세션에서 사용할 수 없어 별도 결함으로 기록한다.
    await b.call('JWT 없는 잠금 해제도 잘못된 PIN은 거절', 'POST', '/api/v1/auth/session/unlock',
                 body={'refresh_token': user['refresh'], 'pin': '654321'}, want=401)
    previous_refresh = user['refresh']
    code, unlocked_without_jwt = await b.request('POST', '/api/v1/auth/session/unlock', body={'refresh_token': previous_refresh, 'pin': '123456'})
    b.record('Gateway 잠금 해제에 access token 불필요', code == 200,
             f'HTTP={code}; refresh token과 PIN만 전달. 401이면 Gateway 공개 경로 보강 필요')
    if code == 200:
        # 잠금 해제도 refresh token을 교체한다. 다음 요청에는 새 세션을 사용한다.
        user.update(token=unlocked_without_jwt['data']['access_token'], refresh=unlocked_without_jwt['data']['refresh_token'])
        await b.call('잠금 해제 후 이전 refresh 재사용 거절', 'POST', '/api/v1/auth/refresh',
                     body={'refresh_token': previous_refresh}, want=401)
    unlocked = await b.call('JWT 동반 잠금 해제', 'POST', '/api/v1/auth/session/unlock', user,
                            {'refresh_token': user['refresh'], 'pin': '123456'})
    user.update(token=unlocked['data']['access_token'], refresh=unlocked['data']['refresh_token'])
    await b.call('Auth PIN 변경', 'POST', '/api/v1/auth/pin/change', user,
                 {'current_pin': '123456', 'new_pin': '234567', 'new_pin_confirm': '234567'})
    await b.call('PIN 변경 후 이전 세션 폐기', 'POST', '/api/v1/auth/refresh',
                 body={'refresh_token': user['refresh']}, want=401)
    login = await b.call('새 PIN 로그인', 'POST', '/api/v1/auth/login',
                         body={'phone_number': body['phone_number'], 'pin': '234567'})
    user.update(token=login['data']['access_token'], refresh=login['data']['refresh_token'])
    await b.call('Auth 회원 탈퇴', 'DELETE', '/api/v1/auth/me', user, {'current_pin': '234567'})
    await b.call('탈퇴 사용자 로그인 차단', 'POST', '/api/v1/auth/login',
                 body={'phone_number': body['phone_number'], 'pin': '234567'}, want=422)
    await b.call('탈퇴 사용자 refresh 차단', 'POST', '/api/v1/auth/refresh',
                 body={'refresh_token': user['refresh']}, want=401)


async def main():
    if b.REPORT.exists():
        b.ROWS = json.loads(b.REPORT.read_text())
    start = len(b.ROWS)
    async with httpx.AsyncClient(timeout=75) as client:
        b.CLIENT = client
        await r.section('최신 Auth 회원 관리', check_auth)
    return int(any(row['status'] == 'FAIL' for row in b.ROWS[start:]))


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
