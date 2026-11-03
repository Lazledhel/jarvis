import json,tempfile,unittest
from pathlib import Path
import developer_api as api

class Routing(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=api.ROOT;self.start=api.start_pilot
  api.ROOT=Path(self.temp.name);self.started=[];api.start_pilot=lambda:self.started.append(True) or True
 def tearDown(self):api.ROOT=self.root;api.start_pilot=self.start;self.temp.cleanup()
 def test_calculator_is_queued_without_using_conversation_model(self):
  reply=api.developer_reply('Напиши калькулятор на андроид')
  self.assertIn('принята',reply)
  self.assertEqual(self.started,[True])
  self.assertTrue((api.ROOT/'jobs'/api.PILOT/'request.json').exists())
 def test_unapproved_new_project_cannot_start_paid_work(self):
  reply=api.developer_reply('Разработай приложение для учёта денег')
  self.assertIn('согласовать',reply)
  self.assertEqual(self.started,[])
  project=next((api.ROOT/'jobs').iterdir())
  self.assertEqual(json.loads((project/'state.json').read_text())['state'],'awaiting_owner')
 def test_notes_and_weather_keep_their_existing_routing(self):
  for text in ['Какая погода завтра?','Напиши заметку про приложение','Сколько будет 15 процентов от 2400?']:
   self.assertIsNone(api.developer_reply(text))
 def test_voice_approval_never_adds_a_grant(self):
  reply=api.developer_reply('Подтверждаю миллион токенов')
  self.assertIn('не меняет лимит',reply)
  self.assertFalse((api.ROOT/'controller/budget.sqlite3').exists())
 def test_artifact_project_paths_cannot_escape_job_root(self):
  for project in ['../../keys','C:\\Jarvis','/etc','a/b']:
   with self.assertRaises(ValueError):api.project_path(project)
if __name__=='__main__':unittest.main()
