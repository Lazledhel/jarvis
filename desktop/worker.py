from contextlib import contextmanager
"""Pull authenticated tasks from Jarvis and start visible, separate Codex threads."""
import argparse,json,os,sqlite3,ssl,time,urllib.request,urllib.parse
from pathlib import Path
from codex_rpc import Rpc
class Worker:
 def __init__(self,config):
  self.config=config;self.root=Path(config['task_root']);self.root.mkdir(parents=True,exist_ok=True);self.state=Path(config['state_path']);self.state.parent.mkdir(parents=True,exist_ok=True);self.tls=ssl.create_default_context(cafile=config['ca_file'])
  if urllib.parse.urlparse(config['server_url']).scheme!='https':raise ValueError('HTTPS required')
  with self.db() as db:db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,state TEXT,thread_id TEXT,turn_id TEXT)')
  self.rpc=Rpc(config['codex_exe'])
 @contextmanager
 def db(self):
  connection=sqlite3.connect(self.state)
  try:
   with connection:yield connection
  finally:connection.close()
 def api(self,path,body=None):
  request=urllib.request.Request(self.config['server_url'].rstrip('/')+path,data=None if body is None else json.dumps(body).encode(),headers={'Authorization':'Bearer '+self.config['token'],'Content-Type':'application/json'})
  with urllib.request.urlopen(request,context=self.tls,timeout=40) as response:return json.load(response)
 def dispatch(self,job):
  ident=job.get('id','')
  if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise ValueError('Invalid job ID')
  with self.db() as db:
   row=db.execute('SELECT state,thread_id,turn_id FROM jobs WHERE id=?',(ident,)).fetchone()
   if row:
    if not row[1]:raise RuntimeError('Interrupted dispatch requires manual recovery; not duplicated')
    self.api('/computer/ack',{'id':ident,'lease':job['lease'],'thread_id':row[1],'turn_id':row[2]});previous=row[0].removeprefix('reported_');state=previous if previous in ('completed','failed','needs_attention') else 'needs_attention';self.api('/computer/result',{'id':ident,'thread_id':row[1],'state':state});return
   db.execute('INSERT INTO jobs VALUES(?,?,?,?)',(ident,'dispatching',None,None))
  folder=self.root/ident;folder.mkdir(exist_ok=True)
  goal=str(job['goal'])[:3000];steps=job.get('steps',[])
  if not isinstance(steps,list) or len(steps)>8 or any(not isinstance(x,str) or len(x)>800 for x in steps):raise ValueError('Invalid plan')
  prompt='Голосовая задача владельца Jarvis, переданная по его команде «на компьютере».\n\nИсходная задача:\n'+goal+'\n\nПредварительный план:\n'+'\n'.join(str(n+1)+'. '+step for n,step in enumerate(steps))+'\n\nВыполни задачу в этом отдельном чате, уточнив план при необходимости. Основной источник намерения — исходная задача, план служит подсказкой. Соблюдай действующие правила доступа и подтверждения. Не отправляй сообщения другим людям без явного указания пользователя. Результат оставь в этом чате.'
  thread,turn=self.rpc.start(folder,prompt,'Джарвис · '+str(job.get('title','Задача'))[:75])
  with self.db() as db:db.execute('UPDATE jobs SET state=?,thread_id=?,turn_id=? WHERE id=?',('started',thread,turn,ident))
  self.api('/computer/ack',{'id':ident,'lease':job['lease'],'thread_id':thread,'turn_id':turn})
  state=self.rpc.wait(thread,turn)
  with self.db() as db:db.execute('UPDATE jobs SET state=? WHERE id=?',(state,ident))
  self.api('/computer/result',{'id':ident,'thread_id':thread,'state':state})
  with self.db() as db:db.execute('UPDATE jobs SET state=? WHERE id=?',('reported_'+state,ident))
 def report_pending(self):
  with self.db() as db:pending=db.execute("SELECT id,thread_id,state FROM jobs WHERE state IN ('completed','failed','needs_attention')").fetchall()
  for ident,thread,state in pending:
   try:
    self.api('/computer/result',{'id':ident,'thread_id':thread,'state':state})
    with self.db() as db:db.execute('UPDATE jobs SET state=? WHERE id=?',('reported_'+state,ident))
   except Exception:continue
 def run(self):
  while True:
   try:
    if self.rpc.process.poll() is not None:self.rpc=Rpc(self.config['codex_exe'])
    self.report_pending()
    value=self.api('/computer/next')
    if value.get('job'):self.dispatch(value['job'])
   except Exception as error:
    print(time.strftime('%Y-%m-%d %H:%M:%S'),type(error).__name__,flush=True);time.sleep(5)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args();config=json.loads(Path(args.config).read_text('utf-8-sig'));import sys;log=Path(config['state_path']).with_suffix('.log');sys.stdout=open(log,'a',encoding='utf-8',buffering=1);sys.stderr=sys.stdout;Worker(config).run()
