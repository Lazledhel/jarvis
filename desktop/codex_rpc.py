"""Codex's documented stdio app-server client; never auto-approves requests."""
import json,queue,subprocess,threading,time,os,shutil
from pathlib import Path
class Rpc:
 def __init__(self,executable):
  if not Path(executable).is_file():
   resolved=shutil.which(executable)
   if not resolved and os.name=='nt':
    candidates=list((Path(os.getenv('LOCALAPPDATA',''))/'OpenAI/Codex/bin').glob('*/codex.exe'));resolved=str(max(candidates,key=lambda p:p.stat().st_mtime)) if candidates else None
   if not resolved:raise FileNotFoundError('Codex executable not found')
   executable=resolved
  flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
  self.process=subprocess.Popen([executable,'app-server','--stdio'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=flags)
  self.waiters={};self.events=queue.Queue();self.lock=threading.Lock();self.serial=0;self.attention=set();threading.Thread(target=self.read,daemon=True).start()
  self.call('initialize',{'clientInfo':{'name':'jarvis_desktop_bridge','title':'Jarvis Desktop Bridge','version':'1.0.0'}});self.send({'method':'initialized','params':{}})
 def send(self,value):
  with self.lock:self.process.stdin.write(json.dumps(value,ensure_ascii=False)+'\n');self.process.stdin.flush()
 def call(self,method,params,timeout=60):
  self.serial+=1;ident=self.serial;waiting=queue.Queue();self.waiters[ident]=waiting;self.send({'id':ident,'method':method,'params':params})
  try:reply=waiting.get(timeout=timeout)
  finally:self.waiters.pop(ident,None)
  if 'error' in reply:raise RuntimeError('Codex RPC '+method+' failed: '+str(reply['error'].get('code')))
  return reply['result']
 def read(self):
  for line in self.process.stdout:
   try:message=json.loads(line)
   except ValueError:continue
   if 'method' in message and 'id' in message:
    thread=message.get('params',{}).get('threadId')
    if thread:self.attention.add(thread)
    self.send({'id':message['id'],'error':{'code':-32001,'message':'Human approval required. Open the task in Codex to continue.'}})
   elif message.get('id') in self.waiters:self.waiters[message['id']].put(message)
   else:self.events.put(message)
 def start(self,folder,prompt,title):
  response=self.call('thread/start',{'cwd':str(folder),'approvalPolicy':'on-request','sandbox':'workspace-write','serviceName':'jarvis-desktop'})
  thread=response['thread']['id'];self.call('thread/name/set',{'threadId':thread,'name':title})
  turn=self.call('turn/start',{'threadId':thread,'input':[{'type':'text','text':prompt}]})
  return thread,turn['turn']['id']
 def wait(self,thread,turn,timeout=1800):
  until=time.monotonic()+timeout
  while time.monotonic()<until:
   if thread in self.attention:return 'needs_attention'
   if self.process.poll() is not None:return 'needs_attention'
   try:event=self.events.get(timeout=1)
   except queue.Empty:continue
   if event.get('method')=='turn/completed' and event.get('params',{}).get('threadId')==thread:
    return 'completed' if event['params']['turn'].get('status')=='completed' else 'needs_attention'
  return 'needs_attention'
 def close(self):self.process.terminate()
