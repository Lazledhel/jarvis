import unittest,tempfile,os,sqlite3
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from computer_bridge import ComputerQueue,extract_goal,routes,computer_reply
class Tests(unittest.TestCase):
 def test_explicit_voice_gate(self):
  self.assertEqual(extract_goal('На компьютере: сделай отчёт'),'сделай отчёт');self.assertEqual(extract_goal('Сделай отчёт на компьютере.'),'Сделай отчёт');self.assertIsNone(extract_goal('Что означает фраза «на компьютере»?'));self.assertIsNone(extract_goal('Найди прогноз погоды'));self.assertEqual(extract_goal('на компьютере'),'')
 def test_queue_lease_and_completion(self):
  with tempfile.TemporaryDirectory() as tmp:
   queue=ComputerQueue(Path(tmp)/'jobs.sqlite3');ident=queue.enqueue('test',{'title':'test','steps':['one','two']});first=queue.claim();self.assertEqual(first['id'],ident);self.assertIsNone(queue.claim())
   with queue.db() as db:db.execute('UPDATE jobs SET lease_until=0 WHERE id=?',(ident,))
   second=queue.claim();self.assertNotEqual(first['lease'],second['lease'])
   with self.assertRaises(HTTPException):queue.acknowledge(dict(first,thread_id='thread'))
   queue.acknowledge(dict(second,thread_id='thread',turn_id='turn'));queue.complete({'id':ident,'thread_id':'thread','state':'completed'});self.assertIsNone(queue.claim())
 def test_worker_auth_is_separate(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'COMPUTER_BRIDGE_TOKEN':'worker-test-only'}):
   app=FastAPI();app.include_router(routes(ComputerQueue(Path(tmp)/'jobs.sqlite3')));client=TestClient(app)
   self.assertEqual(client.get('/computer/next').status_code,401);self.assertEqual(client.get('/computer/next',headers={'Authorization':'Bearer phone-test-only'}).status_code,401)
 def test_normal_dialog_does_not_enqueue(self):
  with tempfile.TemporaryDirectory() as tmp:
   queue=ComputerQueue(Path(tmp)/'jobs.sqlite3');self.assertIsNone(computer_reply(queue,'Обычный вопрос','ru'));self.assertIsNone(queue.claim())
 def test_queue_with_plan(self):
  with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'COMPUTER_BRIDGE_TOKEN':'worker-test-only'}),patch('computer_bridge.plan_goal',return_value={'title':'test','steps':['one','two']}):
   queue=ComputerQueue(Path(tmp)/'jobs.sqlite3');self.assertIn('Codex',computer_reply(queue,'на компьютере проверь связь','ru'));self.assertEqual(len(queue.claim()['steps']),2)
if __name__=='__main__':unittest.main()
