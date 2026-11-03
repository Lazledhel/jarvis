import re
LANGUAGES={'ru':'Russian','en':'English','es':'Spanish','fr':'French','de':'German','it':'Italian','pt':'Portuguese','pl':'Polish','tr':'Turkish','nl':'Dutch','cs':'Czech','ar':'Arabic','zh-cn':'Chinese','hu':'Hungarian','ko':'Korean','ja':'Japanese','hi':'Hindi'}
EN_START={'what','why','when','where','who','how','which','please','call','connect','disconnect','turn','build','open','tell','say','repeat','remember','can','could','would','do','does','did','is','are','i','my','hello','hi','thanks','thank','yes','no'}
def choose_language(text,detected=None,fallback='ru'):
 detected='zh-cn' if detected=='zh' else detected
 if detected in LANGUAGES:return detected
 words=re.findall(r'[^\W\d_]+',str(text),re.UNICODE);first=words[0].lower() if words else ''
 if first in EN_START:return 'en'
 starts={'fr':{'bonjour','salut','comment','quelle','quel','combien','pourquoi','merci'},'de':{'hallo','guten','wie','was','warum','wieviel','danke'},'es':{'hola','cuánto','cuántos','cómo','buenos','gracias'},'it':{'ciao','buongiorno','quanto','come','grazie'},'pt':{'olá','obrigado','quanto'},'hu':{'szia','jó','mennyi','milyen','köszönöm'},'pl':{'cześć','ile','dlaczego','dziękuję'},'tr':{'merhaba','nasıl','kaç'},'nl':{'hallo','hoe','bedankt'},'cs':{'ahoj','kolik','děkuji'}}
 for code,items in starts.items():
  if first in items:return code
 for pattern,code in [(r'[\u3040-\u30ff]','ja'),(r'[\uac00-\ud7af]','ko'),(r'[\u4e00-\u9fff]','zh-cn'),(r'[\u0600-\u06ff]','ar'),(r'[\u0900-\u097f]','hi')]:
  if re.search(pattern,str(text)) and not re.search('[А-Яа-яЁё]',str(text)):return code
 ru=len(re.findall('[А-Яа-яЁё]',str(text)));en=len(re.findall('[A-Za-z]',str(text)))
 if ru or en:return 'ru' if ru>=en else 'en'
 return fallback if fallback in LANGUAGES else 'ru'
def instruction(language):
 name=LANGUAGES.get(language,'Russian')
 return ('MANDATORY LANGUAGE FOR THIS CURRENT TURN: '+name+'. Use '+name+' for your response, explanations, action confirmations and errors. The language of this latest utterance overrides the language of previous conversation turns and tool outputs. Do not switch languages merely because a place, contact, product or quotation uses a different alphabet. Preserve names and requested translations accurately; frame them in '+name+'.')
