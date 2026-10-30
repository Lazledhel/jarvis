from contextlib import contextmanager
"""Authenticated, persistent voice-to-computer task queue."""
import json,os,re,secrets,sqlite3,time,uuid,threading
from pathlib import Path
from fastapi import APIRouter,HTTPException,Request

def extract_goal(text):
 text=str(text).strip()
 prefix=re.match(r'^на\s+компьютере\b[\s,:.!—-]*',text,re.I)
 if prefix:return text[prefix.end():].strip()
 suffix=re.search(r'[\s,:—-]+на\s+компьютере[.!?]*$',text,re.I)
 return text[:suffix.start()].strip() if suffix else None

def plan_goal(goal,language):
 from provider import client,resolve
 api=client();answer=api.chat.completions.create(model=resolve(api),messages=[{'role':'system','content':'Split this computer task into 1 to 8 concrete steps. Return only JSON with title (max 90 characters) and steps (array of short strings). Preserve the user intent. Do not execute anything, add goals, or request secrets. Use the user language: '+language},{'role':'user','content':goal}],response_format={'type':'json_object'},max_completion_tokens=600,reasoning_effort='none')
 data=json.loads(answer.choices[0].message.content);steps=data.get('steps')
 if not isinstance(steps,list) or not 1<=len(steps)<=8 or any(not isinstance(step,str) or not step.strip() or len(step)>800 for step in steps):raise ValueError('Invalid plan')
 return {'title':str(data.get('title',goal))[:90],'steps':[step.strip() for step in steps]}

class ComputerQueue:
 def __init__(self,path):
  self.condition=threading.Condition();self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.db() as db:db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,created REAL,goal TEXT,title TEXT,steps TEXT,state TEXT,lease TEXT,lease_until REAL,thread_id TEXT,turn_id TEXT)')
 @contextmanager
 def db(self):
  connection=sqlite3.connect(self.path,timeout=10)
  try:
   with connection:yield connection
  finally:connection.close()
 def enqueue(self,goal,plan):
  ident=uuid.uuid4().hex
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE')
   if db.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','leased')").fetchone()[0]>=100:raise HTTPException(429,'Computer queue is full')
   db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(ident,time.time(),goal,plan['title'],json.dumps(plan['steps'],ensure_ascii=False),'queued',None,0,None,None))
  with self.condition:self.condition.notify_all()
  return ident
 def claim(self):
  with self.db() as db:
   db.execute('BEGIN IMMEDIATE');row=db.execute("SELECT id,goal,title,steps FROM jobs WHERE state='queued' OR (state='leased' AND lease_until<?) ORDER BY created LIMIT 1",(time.time(),)).fetchone()
   if not row:return None
   lease=secrets.token_urlsafe(24);db.execute("UPDATE jobs SET state='leased',lease=?,lease_until=? WHERE id=?",(lease,time.time()+90,row[0]))
   return {'id':row[0],'goal':row[1],'title':row[2],'steps':json.loads(row[3]),'lease':lease}
 def acknowledge(self,data):
  with self.db() as db:
   cursor=db.execute("UPDATE jobs SET state='started',thread_id=?,turn_id=?,lease_until=0 WHERE id=? AND lease=? AND state IN ('leased','started')",(str(data['thread_id']),str(data.get('turn_id','')),str(data['id']),str(data['lease'])))
   if not cursor.rowcount:raise HTTPException(409,'Lease expired')
 def complete(self,data):
  if data.get('state') not in ('completed','failed','needs_attention'):raise HTTPException(400,'Invalid state')
  with self.db() as db:
   cursor=db.execute('UPDATE jobs SET state=? WHERE id=? AND thread_id=?',(data['state'],str(data['id']),str(data['thread_id'])))
   if not cursor.rowcount:raise HTTPException(409,'Unknown computer task')

def bridge_token():
 value=os.getenv('COMPUTER_BRIDGE_TOKEN','')
 if not value and os.getenv('COMPUTER_BRIDGE_TOKEN_FILE'):
  try:value=Path(os.environ['COMPUTER_BRIDGE_TOKEN_FILE']).read_text().strip()
  except OSError:return ''
 return value

def computer_reply(queue,text,language):
 goal=extract_goal(text)
 if goal is None:return None
 if not bridge_token():return 'Связь с компьютером ещё не настроена.' if language=='ru' else 'The computer connection has not been configured yet.'
 if not goal:return 'Скажите «на компьютере», а затем задачу, которую нужно выполнить.' if language=='ru' else 'Say the computer phrase followed by the task to perform.'
 try:plan=plan_goal(goal[:3000],language)
 except Exception:plan={'title':goal[:90],'steps':[goal[:800]]}
 queue.enqueue(goal[:3000],plan)
 return ('Разбил задачу на шаги и поставил в очередь для компьютера. Она появится отдельным чатом в Codex.' if language=='ru' else 'I have prepared the steps and queued the task for your computer. It will appear in a separate Codex chat.')

def routes(queue):
 router=APIRouter()
 def authorize(request):
  token=bridge_token()
  if not token or not secrets.compare_digest(request.headers.get('authorization','').encode(),('Bearer '+token).encode()):raise HTTPException(401,'Unauthorized')
 async def data(request):
  body=await request.body()
  if len(body)>4096:raise HTTPException(413,'Request too large')
  try:value=json.loads(body)
  except Exception:raise HTTPException(400,'Invalid JSON')
  if not isinstance(value,dict):raise HTTPException(400,'Invalid payload')
  return value
 @router.get('/computer/next')
 async def next_job(request:Request):
  authorize(request)
  from starlette.concurrency import run_in_threadpool
  def wait():
   until=time.monotonic()+20
   with queue.condition:
    while True:
     job=queue.claim()
     if job or time.monotonic()>=until:return {'job':job}
     queue.condition.wait(max(0,until-time.monotonic()))
  return await run_in_threadpool(wait)
 @router.post('/computer/ack')
 async def acknowledge(request:Request):
  authorize(request);value=await data(request)
  if not all(isinstance(value.get(k),str) for k in ['id','lease','thread_id']):raise HTTPException(400,'Missing fields')
  queue.acknowledge(value);return {'ok':True}
 @router.post('/computer/result')
 async def result(request:Request):
  authorize(request);value=await data(request)
  if not all(isinstance(value.get(k),str) for k in ['id','thread_id','state']):raise HTTPException(400,'Missing fields')
  queue.complete(value);return {'ok':True}
 return router
