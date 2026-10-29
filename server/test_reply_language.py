import unittest
from unittest.mock import patch
from types import SimpleNamespace as S
import provider
from reply_language import choose_language
class Tests(unittest.TestCase):
 def test_spoken_digits_use_asr_language(self):
  self.assertEqual(choose_language('42','ru'),'ru');self.assertEqual(choose_language('42','en'),'en')
 def test_names_do_not_switch_turn_language(self):
  self.assertEqual(choose_language('What does Привет mean?'),'en');self.assertEqual(choose_language('Call маме'),'en');self.assertEqual(choose_language('Повтори слово Google'),'ru')
 def test_language_overrides_history(self):
  captured=[]
  def create(**kw):captured.append(kw);return S(choices=[S(message=S(content='A test.',tool_calls=None))])
  api=S(chat=S(completions=S(create=create)))
  with patch.object(provider,'client',return_value=api),patch.object(provider,'resolve',return_value='gpt-6-luna'):
   provider.generate([{'role':'assistant','content':'Буду отвечать по-русски.'}],'42','en')
  self.assertIn('MANDATORY LANGUAGE FOR THIS CURRENT TURN: English',captured[0]['messages'][0]['content'])
 def test_action_confirmation_uses_explicit_language(self):
  call=S(function=S(name='control_phone',arguments='{"kind":"call","target":"Мама"}'))
  api=S(chat=S(completions=S(create=lambda **kw:S(choices=[S(message=S(tool_calls=[call]))]))))
  with patch.object(provider,'client',return_value=api),patch.object(provider,'resolve',return_value='gpt-6-luna'):
   reply,_,action=provider.generate([],'Call Мама','en')
  self.assertTrue(reply.startswith('Prepared a call'));self.assertEqual(action['language'],'en')
 def test_invalid_action_error_uses_language(self):
  call=S(function=S(name='control_phone',arguments='{"kind":"unsupported"}'))
  api=S(chat=S(completions=S(create=lambda **kw:S(choices=[S(message=S(tool_calls=[call]))]))))
  with patch.object(provider,'client',return_value=api),patch.object(provider,'resolve',return_value='gpt-6-luna'):
   reply,_,action=provider.generate([],'Do that','en')
  self.assertTrue(reply.startswith('Please clarify'));self.assertIsNone(action)
if __name__=='__main__':unittest.main()
