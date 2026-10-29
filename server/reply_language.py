import re
EN_START={'what','why','when','where','who','how','which','please','call','connect','disconnect','turn','build','open','tell','say','repeat','remember','can','could','would','do','does','did','is','are','i','my','hello','hi','thanks','thank','yes','no'}
def choose_language(text,detected=None,fallback='ru'):
 if detected in ('ru','en'):return detected
 words=re.findall(r'[A-Za-zА-Яа-яЁё]+',str(text));first=words[0].lower() if words else ''
 if first in EN_START:return 'en'
 ru=len(re.findall('[А-Яа-яЁё]',str(text)));en=len(re.findall('[A-Za-z]',str(text)))
 if ru or en:return 'ru' if ru>=en else 'en'
 return fallback if fallback in ('ru','en') else 'ru'
def instruction(language):
 name='Russian' if language=='ru' else 'English'
 return ('MANDATORY LANGUAGE FOR THIS CURRENT TURN: '+name+'. Use '+name+' for your response, explanations, action confirmations and errors. The language of this latest utterance overrides the language of previous conversation turns and tool outputs. Do not switch languages merely because a place, contact, product or quotation uses a different alphabet. Preserve names and requested translations accurately; frame them in '+name+'.')
