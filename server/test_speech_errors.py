import unittest
from fastapi import HTTPException
from speech_errors import synthesize
class Tests(unittest.TestCase):
 def test_success(self):self.assertEqual(synthesize(lambda text,language:b'RIFF', 'test','en'),b'RIFF')
 def test_failure_is_diagnostic_without_sensitive_content(self):
  def fail(text,language):raise RuntimeError('secret-token-private-command')
  for language in ['ru','en']:
   with self.assertLogs('jarvis.speech',level='ERROR') as logs:
    with self.assertRaises(HTTPException) as result:synthesize(fail,'private command',language)
   self.assertEqual(result.exception.status_code,503);self.assertNotIn('secret-token',str(logs.output));self.assertNotIn('private command',str(logs.output));self.assertIn('RuntimeError',str(logs.output))
if __name__=='__main__':unittest.main()
