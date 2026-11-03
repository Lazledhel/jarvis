"""Fail-closed per-project token grants. Only the trusted operator can approve blocks."""
import json,sqlite3,time,uuid
from pathlib import Path
from contextlib import contextmanager

BLOCK=1_000_000
class ApprovalRequired(RuntimeError):pass
class UsageUncertain(RuntimeError):pass


class Ledger:
 def __init__(self,path):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.db() as db:db.executescript('''
   CREATE TABLE IF NOT EXISTS grants(project TEXT,block INTEGER,tokens INTEGER NOT NULL,approval_ref TEXT NOT NULL,created REAL,PRIMARY KEY(project,block));
   CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,project TEXT,reserved INTEGER,charged INTEGER,state TEXT,purpose TEXT,created REAL,usage_json TEXT);
  ''')
 @contextmanager
 def db(self):
  con=sqlite3.connect(self.path,timeout=30);con.row_factory=sqlite3.Row
  try:
   con.execute('BEGIN IMMEDIATE')
   with con:yield con
  finally:con.close()
 def approve(self,project,block,approval_ref):
  if not project or type(block) is not int or block<1 or not approval_ref or len(approval_ref)<10:raise ValueError('Explicit project, block and operator approval evidence required')
  with self.db() as db:
   existing=db.execute('SELECT max(block) FROM grants WHERE project=?',(project,)).fetchone()[0] or 0
   if block!=existing+1:raise ValueError('Blocks must be approved individually and in order')
   db.execute('INSERT INTO grants VALUES(?,?,?,?,?)',(project,block,BLOCK,approval_ref,time.time()))
  return self.status(project)
 def status(self,project):
  with self.db() as db:
   granted=db.execute('SELECT coalesce(sum(tokens),0) FROM grants WHERE project=?',(project,)).fetchone()[0]
   charged=db.execute("SELECT coalesce(sum(charged),0) FROM calls WHERE project=? AND state!='reserved'",(project,)).fetchone()[0]
   reserved=db.execute("SELECT coalesce(sum(reserved),0) FROM calls WHERE project=? AND state='reserved'",(project,)).fetchone()[0]
   uncertain=db.execute("SELECT count(*) FROM calls WHERE project=? AND state='uncertain'",(project,)).fetchone()[0]
  return {'project':project,'approved_tokens':granted,'charged_tokens':charged,'reserved_tokens':reserved,'available_tokens':max(0,granted-charged-reserved),'uncertain_calls':uncertain,'next_block':granted//BLOCK+1}
 def reserve(self,project,messages,max_output,purpose):
  if type(max_output) is not int or not 1<=max_output<=8192:raise ValueError('Invalid output bound')
  serialized=json.dumps(messages,ensure_ascii=False)
  if len(serialized)>100000:raise ValueError('Developer API input too large')
  # Deliberately conservative UTF-8 byte bound plus framing margin; never rely on an unknown tokenizer.
  amount=4*len(serialized.encode('utf-8'))+8192+max_output
  ident=uuid.uuid4().hex
  with self.db() as db:
   if db.execute("SELECT 1 FROM calls WHERE project=? AND state='uncertain'",(project,)).fetchone():raise UsageUncertain('Reconcile uncertain billed request before continuing')
   granted=db.execute('SELECT coalesce(sum(tokens),0) FROM grants WHERE project=?',(project,)).fetchone()[0]
   committed=db.execute("SELECT coalesce(sum(CASE WHEN state='reserved' THEN reserved ELSE charged END),0) FROM calls WHERE project=?",(project,)).fetchone()[0]
   if amount>granted-committed:raise ApprovalRequired('Next 1,000,000-token block needs explicit owner approval')
   db.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,?,?)',(ident,project,amount,0,'reserved',purpose[:100],time.time(),None))
  return ident
 def settle(self,ident,usage):
  valid=isinstance(usage,dict) and type(usage.get('total_tokens')) is int and usage['total_tokens']>=0
  with self.db() as db:
   row=db.execute('SELECT * FROM calls WHERE id=?',(ident,)).fetchone()
   if not row or row['state']!='reserved':raise ValueError('Unknown or already settled reservation')
   if not valid or usage['total_tokens']>row['reserved']:
    db.execute("UPDATE calls SET state='uncertain',charged=reserved,usage_json=? WHERE id=?",(json.dumps(usage),ident))
   else:db.execute("UPDATE calls SET state='settled',charged=?,usage_json=? WHERE id=?",(usage['total_tokens'],json.dumps(usage),ident))
  if not valid or usage['total_tokens']>row['reserved']:raise UsageUncertain('Missing/unexpected usage: charge full reservation and pause project')
 def uncertain(self,ident):
  with self.db() as db:db.execute("UPDATE calls SET state='uncertain',charged=reserved WHERE id=? AND state='reserved'",(ident,))


def luna_call(ledger,project,api,messages,max_output=4096,purpose='development'):
 reservation=ledger.reserve(project,messages,max_output,purpose)
 try:
  response=api.chat.completions.create(model='gpt-6-luna',messages=messages,max_completion_tokens=max_output,reasoning_effort='none',timeout=60)
 except BaseException:
  # An HTTP timeout can still be billed. Do not refund or automatically retry it.
  ledger.uncertain(reservation);raise
 usage=response.usage.model_dump() if response.usage is not None else None
 ledger.settle(reservation,usage)
 return response.choices[0].message.content
