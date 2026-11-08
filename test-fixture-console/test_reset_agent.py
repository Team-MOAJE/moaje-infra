import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import os
os.environ.setdefault('RESET_AGENT_TOKEN','unit-test')
import reset_agent as agent


class ResetTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.filepatch=patch.object(agent,'STATE_FILE',Path(self.temp.name)/'state.json')
        self.filepatch.start()
        agent.STATE={'status':'RUNNING','stage':'test'}
    def tearDown(self):
        self.filepatch.stop()
        self.temp.cleanup()

    def test_only_own_compose_and_explicit_mock_are_selected(self):
        items=[{'Id':s,'State':'running','Labels':{'com.docker.compose.project':'test-project','com.docker.compose.service':s}} for s in agent.APP_SERVICES|agent.DB_SERVICES|agent.REDIS_SERVICES|{'kafka'}]
        items.append({'Id':'foreign','State':'running','Labels':{'com.docker.compose.project':'other','com.docker.compose.service':'redis'}})
        with patch.object(agent,'docker',side_effect=[{'Config':{'Labels':{'com.docker.compose.project':'test-project'}}},items]):
            project,selected=agent.targets()
            self.assertEqual(project,'test-project')
            self.assertNotIn('foreign',[c['Id'] for c in selected.values()])

    def test_incomplete_target_fails_before_mutation(self):
        with patch.object(agent,'docker',side_effect=[{'Config':{'Labels':{'com.docker.compose.project':'test'}}},[]]) as docker:
            with self.assertRaisesRegex(RuntimeError,'필수'):
                agent.targets()
            self.assertTrue(all(c.args[0]=='GET' for c in docker.call_args_list))

    def test_failed_db_keeps_apps_stopped(self):
        targets={s:{'Id':s,'State':'running'} for s in agent.APP_SERVICES|agent.DB_SERVICES|agent.REDIS_SERVICES|{'kafka'}}
        with patch.object(agent,'targets',return_value=('test',targets)), patch.object(agent,'docker') as docker, patch.object(agent,'kafka_reset',return_value=2), patch.object(agent,'mysql_reset',side_effect=RuntimeError('injected-db-failure')):
            agent.run_reset()
            self.assertEqual(agent.STATE['status'],'FAILED')
            self.assertTrue(any('/stop?' in c.args[1] for c in docker.call_args_list))
            self.assertFalse(any(c.args[1].endswith('/start') for c in docker.call_args_list))
            self.assertEqual(set(agent.STATE['resumeServices']),agent.APP_SERVICES)

    def test_kafka_verifies_low_watermark(self):
        responses=['banking:0:10\n__consumer_offsets:0:100\n','ok','banking:0:10\n']
        with patch.object(agent,'execute',side_effect=responses) as command:
            self.assertEqual(agent.kafka_reset('test-kafka'),1)
            self.assertNotIn('__consumer_offsets',command.call_args_list[1].args[1][-1])
        with patch.object(agent,'execute',side_effect=['banking:0:10\n','ok','banking:0:9\n']):
            with self.assertRaisesRegex(RuntimeError,'삭제 확인'):
                agent.kafka_reset('test-kafka')

    def test_migration_tables_are_preserved(self):
        with patch.object(agent,'execute') as command:
            agent.mysql_reset('test-mysql')
            sql=command.call_args.args[1][-1]
            self.assertIn("NOT IN ('flyway_schema_history','alembic_version')",sql)
            self.assertIn('FOREIGN_KEY_CHECKS=0',sql)
            self.assertIn('COUNT(*)',sql)

if __name__=='__main__':
    unittest.main()
