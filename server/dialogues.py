import os,time,uuid,threading,json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
class Dialogues:
 def __init__(self,root,clock=time.time):self.root=Path(root);self.clock=clock;self.sessions={};self.lock=threading.RLock()
 def get(self,session_id):
  with self.lock:
   now=self.clock();s=self.sessions.get(str(session_id))
   if s is None or now-s['last']>=180:
    ident=uuid.uuid4().hex;dt=datetime.fromtimestamp(now,ZoneInfo(os.getenv('JARVIS_TIMEZONE','UTC')));folder=self.root/dt.strftime('%Y-%m-%d');folder.mkdir(parents=True,exist_ok=True)
    s={'id':ident,'last':now,'history':[],'file':folder/(dt.strftime('%H-%M-%S')+'_'+ident[:12]+'.txt')};self.sessions[ident]=s
    s['file'].write_text('Джарвис — диалог '+ident+'\nНачало: '+dt.isoformat()+'\n\n',encoding='utf-8')
   for key,value in list(self.sessions.items()):
    if now-value['last']>86400 and key!=s['id']:del self.sessions[key]
   return s
 def write(self,s,role,text):
  dt=datetime.fromtimestamp(self.clock(),ZoneInfo(os.getenv('JARVIS_TIMEZONE','UTC')))
  clean=str(text).replace('\x00','').replace('\r','');clean='\n'.join('    '+line for line in clean.split('\n'))
  with self.lock,s['file'].open('a',encoding='utf-8') as f:f.write('['+dt.strftime('%H:%M:%S')+'] '+role+'\n'+clean+'\n\n');f.flush()
 def finish(self,s,user,reply,sources,action):
  with self.lock:
   self.write(s,'Джарвис',reply)
   if sources:self.write(s,'Источники',json.dumps(sources,ensure_ascii=False))
   if action:self.write(s,'Подготовленное действие',json.dumps(action,ensure_ascii=False))
   s['history'].extend([{'role':'user','content':user},{'role':'assistant','content':reply}])
   size=sum(len(m['content']) for m in s['history'])
   while size>600000 and len(s['history'])>2:
    size-=len(s['history'].pop(0)['content']);size-=len(s['history'].pop(0)['content'])
   s['last']=self.clock()
 def result(self,session_id,action_id,result):
  with self.lock:
   s=self.sessions.get(str(session_id))
   if s:self.write(s,'Результат действия',str(action_id)+': '+str(result)[:500])
