"""페르소나 도구가 현재 Auth 계약으로 가입·로그인하는지 확인한다."""
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
with patch.dict(os.environ, {'FIXTURE_ADMIN_TOKEN': 'test-only-fixture-token'}):
    spec = importlib.util.spec_from_file_location('fixture_console', ROOT / 'test-fixture-console/app.py')
    console = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(console)


class FixtureAuthContractTest(unittest.TestCase):
    def test_phone_registration_and_login_contract(self):
        """휴대폰 가입 필수값을 전달하고 같은 번호로 로그인·계좌 개설한다."""
        # given: 네트워크 없이 요청 양식을 확인한다. 실제 연동은 별도 Compose에서 검사한다.
        def response(method, url, body=None, headers=None):
            if url.endswith('/register'):
                return {'data': {'user_id': 'test-user'}}
            if url.endswith('/login'):
                return {'data': {'access_token': 'test-only-access-token'}}
            if url.endswith('/banking/accounts'):
                return {'accountId': 'test-account'}
            if url.endswith('/internal/test-fixtures/personas'):
                return {'months': ['2026-09'], 'createdTransactionCount': 8}
            if '/cashflow/monthly?' in url:
                return {'expenseAmount': 153500}
            if '/cashflow/category?' in url:
                return {'categories': []}
            return {}

        with patch.object(console, 'request_json', side_effect=response) as request:
            # when
            result = console.create_persona('BALANCED_STUDENT', 1)

        # then: PIN 확인·필수 동의가 빠지거나 이메일 로그인으로 돌아가는 실수를 막는다.
        calls = {call.args[1]: call.args for call in request.call_args_list}
        registration = calls[console.GATEWAY_URL + '/api/v1/auth/register'][2]
        login = calls[console.GATEWAY_URL + '/api/v1/auth/login'][2]
        account = calls[console.GATEWAY_URL + '/api/v1/banking/accounts'][2]
        self.assertRegex(registration['phone_number'], r'^010\d{8}$')
        self.assertEqual(registration['pin'], registration['pin_confirm'])
        self.assertTrue(registration['terms_agreed'])
        self.assertTrue(registration['privacy_agreed'])
        self.assertTrue(registration['terms_version'])
        self.assertTrue(registration['privacy_version'])
        self.assertTrue(registration['name'])
        self.assertNotIn('email', login)
        self.assertEqual(registration['phone_number'], login['phone_number'])
        self.assertEqual(registration['phone_number'], account['phoneNumber'])
        self.assertEqual(registration['phone_number'], result['phoneNumber'])
        self.assertNotIn('access_token', result)
        self.assertEqual(result['createdTransactionCount'], 8)


if __name__ == '__main__':
    unittest.main()
