import unittest,tempfile
from pathlib import Path
from dialogues import Dialogues
from phone_commands import validate
class Tests(unittest.TestCase):
 def test_three_minute_boundary_and_log(self):
  with tempfile.TemporaryDirectory() as tmp:
   now=[1000000.];d=Dialogues(tmp,lambda:now[0]);s=d.get('');d.write(s,'Вы','Меня зовут Тест');d.finish(s,'Меня зовут Тест','Запомнил',[],None)
   now[0]+=179.999;self.assertIs(d.get(s['id']),s);now[0]+=.001;new=d.get(s['id']);self.assertNotEqual(new['id'],s['id']);self.assertEqual(new['history'],[]);self.assertIn('Меня зовут Тест',s['file'].read_text(encoding='utf-8'));self.assertIn('Запомнил',s['file'].read_text(encoding='utf-8'))
 def test_timeout_from_last_reply(self):
  with tempfile.TemporaryDirectory() as tmp:
   now=[1000.];d=Dialogues(tmp,lambda:now[0]);s=d.get('');now[0]+=170;d.finish(s,'a','b',[],None);now[0]+=170;self.assertIs(d.get(s['id']),s)
 def test_supported_actions_only(self):
  with self.assertRaises(ValueError):validate({'kind':'shell','target':'anything'})
  with self.assertRaises(ValueError):validate({'kind':'vpn','enabled':'false'})
  with self.assertRaises(ValueError):validate({'kind':'route','target':''})
  self.assertEqual(validate({'kind':'call','target':'мама'})['kind'],'call')
if __name__=='__main__':unittest.main()
