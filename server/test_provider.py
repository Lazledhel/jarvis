import os,unittest
from unittest.mock import patch
from types import SimpleNamespace as S
import provider
class Message:
 def __init__(self,content=None,calls=None):self.content=content;self.tool_calls=calls
 def model_dump(self,**kw):return {'role':'assistant','tool_calls':[{'id':c.id,'type':'function','function':{'name':c.function.name,'arguments':c.function.arguments}} for c in self.tool_calls]}
class Tests(unittest.TestCase):
 def setUp(self):provider._model=None;provider._until=0
 def test_key_is_sent_only_to_aiml(self):
  with patch.dict(os.environ,{'AIML_API_KEY':'test-not-real','AIML_API_URL':'https://api.aimlapi.com/v1'}):self.assertEqual(str(provider.client().base_url),'https://api.aimlapi.com/v1/')
  with patch.dict(os.environ,{'AIML_API_KEY':'test-not-real','AIML_API_URL':'https://api.openai.com/v1'}):
   with self.assertRaises(ValueError):provider.client()
 def test_no_model_substitution(self):
  api=S(models=S(list=lambda:S(data=[S(id='gpt-4o')])))
  with self.assertRaises(LookupError):provider.resolve(api)
 def test_exact_requested_model_with_provider_prefix(self):
  api=S(models=S(list=lambda:S(data=[S(id='openai/gpt-6-luna')])));self.assertEqual(provider.resolve(api),'openai/gpt-6-luna')
 def test_search_and_citations(self):
  call=S(id='test',function=S(name='search_web',arguments='{"query":"test"}'))
  replies=iter([S(choices=[S(message=Message(calls=[call]))]),S(choices=[S(message=Message('Answer [source](https://example.org)'))])])
  api=S(models=S(list=lambda:S(data=[S(id='gpt-6-luna')])),chat=S(completions=S(create=lambda **kw:next(replies))))
  with patch.object(provider,'client',return_value=api),patch.object(provider,'search',return_value=[{'title':'source','url':'https://example.org','snippet':'test'}]):
   answer,sources,action=provider.generate([],'Question');self.assertTrue(answer.startswith('Answer'));self.assertEqual(sources,[{'title':'source','url':'https://example.org'}])
if __name__=='__main__':unittest.main()
