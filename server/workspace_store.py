"""Owner-controlled profile, imported knowledge, research records and durable jobs."""
import datetime as dt
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

PROFILE_KEYS={'name','address_form','style','humor','answer_length','work_hours','preferred_tools','default_language'}
RECORD_KINDS={'concept','specification','hypothesis','experiment_plan','lab_entry','analysis','timeline','report'}


class Workspace:
 def __init__(self,path=None):
  self.path=Path(path or os.getenv('JARVIS_WORKSPACE_DB',str(Path(__file__).parent/'workspace.sqlite3')))
  self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.db() as db:
   db.executescript('''
    CREATE TABLE IF NOT EXISTS profile(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS aliases(phrase TEXT PRIMARY KEY,expansion TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS current_state(id INTEGER PRIMARY KEY CHECK(id=1),body TEXT,expires REAL);
    CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY,name TEXT NOT NULL,body TEXT NOT NULL,metadata TEXT NOT NULL,created REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY,kind TEXT,title TEXT,body TEXT,project TEXT,source_ids TEXT,created REAL);
    CREATE TABLE IF NOT EXISTS topics(id TEXT PRIMARY KEY,name TEXT UNIQUE,query TEXT,enabled INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,kind TEXT,config TEXT,enabled INTEGER,next_run REAL,interval_seconds INTEGER,notify INTEGER,last_status TEXT);
    CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY,body TEXT,updated REAL);
    CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY,title TEXT,body TEXT,created REAL,delivered INTEGER DEFAULT 0);
   ''')
   for name,query in [('Формула-1','Формула 1 F1'),('Политика','политика мировые новости'),('Экономика','экономика мировые новости')]:
    # Seed only once; disabled/deleted preferences must never reappear on restart.
    if not db.execute("SELECT 1 FROM profile WHERE key='_topics_initialized'").fetchone():
     db.execute('INSERT OR IGNORE INTO topics(id,name,query) VALUES(?,?,?)',(uuid.uuid4().hex,name,query))
   db.execute("INSERT OR IGNORE INTO profile VALUES('_topics_initialized','true')")

 @contextmanager
 def db(self):
  con=sqlite3.connect(self.path,timeout=15);con.row_factory=sqlite3.Row
  con.create_function('CASEFOLD',1,lambda x:str(x).casefold())
  try:
   with con:yield con
  finally:con.close()

 def profile(self,args):
  op=args['operation']
  with self.db() as db:
   if op=='set':
    key=args.get('key');value=str(args.get('value','')).strip()
    if key not in PROFILE_KEYS or not value or len(value)>500:raise ValueError('Invalid profile key/value')
    if key=='default_language':
     from reply_language import LANGUAGES
     if value not in LANGUAGES:raise ValueError('Unsupported language')
    db.execute('INSERT OR REPLACE INTO profile VALUES(?,?)',(key,value));return {'status':'saved','key':key,'value':value}
   if op=='delete':
    if args.get('key') not in PROFILE_KEYS:raise ValueError('Unknown key')
    db.execute('DELETE FROM profile WHERE key=?',(args['key'],));return {'status':'deleted'}
   if op=='set_state':
    body=str(args.get('value','')).strip();minutes=args.get('minutes',60)
    if not body or len(body)>500 or type(minutes) is not int or not 1<=minutes<=1440:raise ValueError('Invalid temporary state')
    db.execute('INSERT OR REPLACE INTO current_state VALUES(1,?,?)',(body,time.time()+minutes*60));return {'status':'saved','expires_in_minutes':minutes}
   if op=='clear_state':db.execute('DELETE FROM current_state');return {'status':'cleared'}
   if op in ('set_alias','delete_alias'):
    phrase=str(args.get('phrase','')).strip().casefold();expansion=str(args.get('value','')).strip()
    if not phrase or len(phrase)>120:raise ValueError('Invalid alias')
    if op=='delete_alias':db.execute('DELETE FROM aliases WHERE phrase=?',(phrase,))
    else:
     if not expansion or len(expansion)>1500:raise ValueError('Invalid alias expansion')
     if db.execute('SELECT count(*) FROM aliases').fetchone()[0]>=100 and not db.execute('SELECT 1 FROM aliases WHERE phrase=?',(phrase,)).fetchone():raise ValueError('Alias limit reached')
     db.execute('INSERT OR REPLACE INTO aliases VALUES(?,?)',(phrase,expansion))
    return {'status':'saved' if op=='set_alias' else 'deleted','phrase':phrase}
   if op!='get':raise ValueError('Unknown profile operation')
  return self.context()

 def context(self):
  with self.db() as db:
   profile={x['key']:x['value'] for x in db.execute('SELECT * FROM profile') if x['key'] in PROFILE_KEYS}
   state=db.execute('SELECT body,expires FROM current_state WHERE id=1 AND expires>?',(time.time(),)).fetchone()
   aliases=[dict(x) for x in db.execute('SELECT * FROM aliases LIMIT 100')]
  return {'preferences':profile,'temporary_state':dict(state) if state else None,'aliases':aliases}

 def expand(self,text):
  with self.db() as db:row=db.execute('SELECT expansion FROM aliases WHERE phrase=?',(text.strip().casefold(),)).fetchone()
  return row[0] if row else text

 def add_document(self,name,body,metadata):
  if not body.strip():raise ValueError('No extractable text; scanned PDFs require OCR, not included here')
  ident=uuid.uuid4().hex
  with self.db() as db:db.execute('INSERT INTO documents VALUES(?,?,?,?,?)',(ident,name[:250],body[:120000],json.dumps(metadata,ensure_ascii=False),time.time()))
  return {'status':'imported','id':ident,'name':name[:250],'characters':min(len(body),120000),'truncated':len(body)>120000,'metadata':metadata}

 def library(self,args):
  op=args['operation'];ident=str(args.get('id',''));query=str(args.get('query','')).strip()
  with self.db() as db:
   if op=='list':return {'documents':[dict(x) for x in db.execute('SELECT id,name,created FROM documents ORDER BY created DESC LIMIT 100')]}
   if op=='delete':
    if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Exact ID required')
    count=db.execute('DELETE FROM documents WHERE id=?',(ident,)).rowcount;return {'status':'deleted' if count else 'not_found'}
   if op in ('read','metadata'):
    row=db.execute('SELECT * FROM documents WHERE id=?',(ident,)).fetchone()
    if not row:return {'status':'not_found'}
    if op=='metadata':return {'id':ident,'name':row['name'],'metadata':json.loads(row['metadata']),'notice':'Metadata is supplied by the file and can be forged.'}
    offset=args.get('offset',0)
    if type(offset) is not int or not 0<=offset<=120000:raise ValueError('Invalid offset')
    return {'id':ident,'name':row['name'],'text':row['body'][offset:offset+14000],'next_offset':offset+14000 if len(row['body'])>offset+14000 else None,'untrusted_content':True}
   if op!='search' or not query or len(query)>240:raise ValueError('Search query required')
   terms=re.findall(r'\w+',query.casefold())[:12]
   matches=[]
   for row in db.execute('SELECT id,name,body FROM documents ORDER BY created DESC LIMIT 2000'):
    text=(row['name']+' '+row['body']).casefold();hits=[term for term in terms if term in text]
    if hits:
     pos=max(0,row['body'].casefold().find(hits[0])-120)
     matches.append({'id':row['id'],'name':row['name'],'score':len(hits),'snippet':row['body'][pos:pos+1800]})
   matches.sort(key=lambda x:x['score'],reverse=True)
   research=[]
   for row in db.execute('SELECT id,kind,title,body FROM records ORDER BY created DESC LIMIT 2000'):
    body=(row['title']+' '+row['body']).casefold()
    if any(term in body for term in terms):research.append({'id':row['id'],'kind':row['kind'],'title':row['title'],'snippet':row['body'][:1800]})
  from organizer import store
  notes=[]
  for category in ('note','task','shopping'):
   notes.extend(store().execute({'operation':'search','category':category,'query':query},'workspace-read')['entries'][:10])
  return {'documents':matches[:12],'notes_tasks':notes,'research_records':research[:12],'search_type':'literal keyword matching, not semantic embeddings','untrusted_content':True}

 def record(self,args):
  op=args['operation'];ident=str(args.get('id',''));project=str(args.get('project',''))[:200]
  with self.db() as db:
   if op=='write':
    kind=args.get('kind');title=str(args.get('title','')).strip();body=str(args.get('body','')).strip();sources=args.get('source_ids',[])
    if kind not in RECORD_KINDS or not title or len(title)>250 or not body or len(body)>24000 or not isinstance(sources,list) or len(sources)>20:raise ValueError('Invalid research record')
    for source in sources:
     if not db.execute('SELECT 1 FROM documents WHERE id=?',(source,)).fetchone():raise ValueError('Unknown source ID')
    ident=uuid.uuid4().hex;db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?)',(ident,kind,title,body,project,json.dumps(sources),time.time()))
    return {'status':'saved','id':ident,'kind':kind,'title':title}
   if op=='list':
    return {'records':[dict(x) for x in db.execute('SELECT id,kind,title,project,created FROM records WHERE (?="" OR CASEFOLD(project)=CASEFOLD(?)) ORDER BY created DESC LIMIT 100',(project,project))]}
   if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('Exact ID required')
   if op=='read':
    row=db.execute('SELECT * FROM records WHERE id=?',(ident,)).fetchone();return dict(row) if row else {'status':'not_found'}
   if op=='delete':return {'status':'deleted' if db.execute('DELETE FROM records WHERE id=?',(ident,)).rowcount else 'not_found'}
   raise ValueError('Unknown research operation')

 def cache(self,key,value=None):
  with self.db() as db:
   if value is not None:db.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?)',(key,json.dumps(value,ensure_ascii=False),time.time()))
   row=db.execute('SELECT body,updated FROM cache WHERE key=?',(key,)).fetchone()
  return {'data':json.loads(row[0]),'updated_at':dt.datetime.fromtimestamp(row[1],dt.timezone.utc).isoformat()} if row else None

 def notify(self,title,body):
  ident=uuid.uuid4().hex
  with self.db() as db:db.execute('INSERT INTO inbox VALUES(?,?,?,?,0)',(ident,title[:200],body[:6000],time.time()))
  return ident

 def poll(self):
  with self.db() as db:return [dict(x) for x in db.execute('SELECT id,title,body,created FROM inbox WHERE delivered=0 ORDER BY created LIMIT 20')]

 def acknowledge(self,ids):
  if not isinstance(ids,list) or len(ids)>20 or any(not re.fullmatch('[a-f0-9]{32}',str(x)) for x in ids):raise ValueError('Invalid acknowledgement')
  with self.db() as db:db.executemany('UPDATE inbox SET delivered=1 WHERE id=?',[(x,) for x in ids])


def store():return Workspace()
