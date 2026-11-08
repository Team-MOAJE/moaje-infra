import copy
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('FIXTURE_ADMIN_TOKEN', 'unit-test-token')
import app


class ConsoleTest(unittest.TestCase):
    def test_budget_rejected_before_mutation(self):
        with self.assertRaises(ValueError):
            app.validate(dict(persona='STUDY_FOCUSED', months=6, transactionsPerMonth=80, initialBalance=1000))

    def test_zero_and_new_user(self):
        self.assertEqual(app.validate(dict(persona='ZERO_BALANCE'))['initialBalance'], 0)
        self.assertEqual(app.validate(dict(persona='NEW_USER'))['persona'], 'NEW_USER')

    def test_invalid_counts_and_bool(self):
        for count in (0, 9, 81, True, '40'):
            with self.assertRaises(ValueError):
                app.validate(dict(transactionsPerMonth=count))

    def test_new_user_does_not_open_account(self):
        app.JOBS = {'x': {}}
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'DATA_DIR', Path(folder)), patch.object(app, 'request_json') as request:
            request.side_effect = [{'data':{'user_id':'test-user'}}, {'data':{'access_token':'test-token'}}]
            result = app.create('x', app.validate(dict(persona='NEW_USER')))
            self.assertNotIn('accountId', result)
            self.assertEqual(request.call_count, 2)
            self.assertNotIn('test-token', (Path(folder)/'runs.json').read_text())

    def test_interrupted_job_not_replayed(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(app, 'DATA_DIR', Path(folder)):
            app.JOBS={'x':{'status':'RUNNING'}}
            app.persist()
            app.load_jobs()
            self.assertEqual(app.JOBS['x']['status'], 'FAILED')

    def test_pagination_duplicate_is_failure(self):
        result={'accountId':'1','months':[],'createdTransactionCount':2}
        responses=[{'balance':0,'syncStatus':'SYNCED'}, {'transactions':[{'transactionId':'7'}],'hasNext':True,'nextCursor':'7'}, {'transactions':[{'transactionId':'7'}],'hasNext':False}]
        with patch.object(app, 'request_json', side_effect=responses), self.assertRaisesRegex(RuntimeError, '중복'):
            app.inspect_account(copy.deepcopy(result), {})

    def test_missing_projection_is_not_success(self):
        with patch.object(app, 'request_json', side_effect=[{'balance':0,'syncStatus':'SYNCED'}, {'transactions':[], 'hasNext':False}]), self.assertRaisesRegex(RuntimeError, '적습니다'):
            app.inspect_account({'accountId':'1','months':[],'createdTransactionCount':120}, {})

if __name__ == '__main__':
    unittest.main()
