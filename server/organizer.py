"""Persistent personal notes/lists and validated, device-local schedule actions."""
import datetime as dt
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo
from information_tools import definition


class Organizer:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS entries(id TEXT PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL, completed INTEGER NOT NULL DEFAULT 0)')
            db.execute('CREATE TABLE IF NOT EXISTS operations(id TEXT PRIMARY KEY, result TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.create_function('CASEFOLD',1,lambda value: str(value).casefold())
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def execute(self, arguments, operation_id):
        operation = arguments.get('operation')
        category = arguments.get('category', 'note')
        if category not in ('note', 'shopping', 'task') or operation not in ('add', 'list', 'search', 'complete', 'delete', 'update'):
            raise ValueError('Unsupported organizer operation')
        title = str(arguments.get('title', '')).strip()
        body = str(arguments.get('body', '')).strip()
        ident = str(arguments.get('id', ''))
        query = str(arguments.get('query', '')).strip()
        if len(title)>200 or len(body)>6000 or len(query)>200 or '\x00' in title+body+query:
            raise ValueError('Text too long or invalid')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT result FROM operations WHERE id=?', (operation_id,)).fetchone()
            if previous:
                return json.loads(previous[0])
            if operation=='add':
                if not title and not body: raise ValueError('Missing text')
                ident = uuid.uuid4().hex
                db.execute('INSERT INTO entries(id,category,title,body,created) VALUES(?,?,?,?,?)', (ident,category,title or body[:80],body,time.time()))
                result = {'status':'created','id':ident,'category':category,'title':title or body[:80],'body':body}
            elif operation in ('list', 'search'):
                rows = db.execute('SELECT * FROM entries WHERE category=? AND (?=0 OR completed=0) AND (?="" OR instr(CASEFOLD(title || char(10) || body),CASEFOLD(?))>0) ORDER BY created DESC LIMIT 101', (category,0 if arguments.get('include_completed', False) else 1,query,query)).fetchall()
                result = {'status':'ok','entries':[dict(x) for x in rows[:100]],'truncated':len(rows)>100}
            else:
                if not re.fullmatch('[a-f0-9]{32}', ident): raise ValueError('Use an exact ID from a previous list/search result')
                row = db.execute('SELECT * FROM entries WHERE id=? AND category=?',(ident,category)).fetchone()
                if not row: return {'status':'not_found','id':ident}
                if operation=='delete': db.execute('DELETE FROM entries WHERE id=?',(ident,))
                elif operation=='complete': db.execute('UPDATE entries SET completed=1 WHERE id=?',(ident,))
                else:
                    if not title and not body: raise ValueError('Missing replacement text')
                    db.execute('UPDATE entries SET title=?,body=? WHERE id=?',(title or row['title'],body,ident))
                result = {'status':{'delete':'deleted','complete':'completed','update':'updated'}[operation],'id':ident}
            if operation not in ('list','search'):
                db.execute('INSERT INTO operations VALUES(?,?)',(operation_id,json.dumps(result,ensure_ascii=False)))
            return result


TOOL = definition('personal_organizer', 'Persistent personal notes, shopping list and tasks. Use ONLY at the user request. For complete/update/delete first find/list the actual stored ID; never invent IDs or delete all entries. Preserve dictated note content. Search supports a literal text substring; Russian search is case sensitive, use exact text if needed. One item per add; make multiple calls for multiple purchases.', {
    'operation':{'type':'string','enum':['add','list','search','complete','update','delete']},
    'category':{'type':'string','enum':['note','shopping','task']},
    'title':{'type':'string'},'body':{'type':'string'},'id':{'type':'string'},'query':{'type':'string'},'include_completed':{'type':'boolean'}
}, ['operation','category'])

SCHEDULE_TOOL = definition('manage_schedule', 'Prepare a LOCAL Android timer/reminder. Requires organizer_version>=1 device capability. For create use seconds for a relative timer/reminder, or local_datetime ISO YYYY-MM-DDTHH:MM:SS in the device timezone. Ask if date/time is unclear. Recurrence once/daily/weekly only; weekly repeats the same weekday. For list use current device schedule snapshot; cancel requires an exact ID from snapshot. Never claim installed before device confirmation.', {
    'operation':{'type':'string','enum':['create','list','cancel']}, 'type':{'type':'string','enum':['timer','reminder']},
    'label':{'type':'string'},'seconds':{'type':'integer'},'local_datetime':{'type':'string'},'repeat':{'type':'string','enum':['once','daily','weekly']},'id':{'type':'string'}
}, ['operation'])


def device_context(data):
    raw = data.get('organizer', {})
    if not isinstance(raw,dict) or raw.get('version')!=1: return {'version':0}
    zone = str(raw.get('timezone',''))
    ZoneInfo(zone)
    schedules = raw.get('schedules',[])
    if not isinstance(schedules,list) or len(schedules)>100: raise ValueError('Invalid schedules')
    clean=[]
    for item in schedules:
        if not isinstance(item,dict): continue
        if re.fullmatch('[a-f0-9]{32}',str(item.get('id',''))):
            clean.append({k:item.get(k) for k in ('id','label','due_ms','type','repeat')})
    return {'version':1,'timezone':zone,'now':dt.datetime.now(ZoneInfo(zone)).isoformat(), 'schedules':clean}


def schedule_action(args, device, language):
    if device.get('version')!=1:
        return {'status':'needs_app_update','instruction':'Explain that local timers/reminders require Jarvis Android 2.4; no schedule was created.'},None
    entries=device.get('schedules',[])
    operation=args.get('operation')
    if operation=='list': return {'status':'ok','entries':entries},None
    action={'kind':'schedule','id':uuid.uuid4().hex,'language':language,'operation':operation}
    if operation=='cancel':
        target=str(args.get('id',''))
        if target not in {x['id'] for x in entries}: return {'status':'not_found'},None
        action['target_id']=target
    elif operation=='create':
        label=str(args.get('label','')).strip()
        if not label or len(label)>200: raise ValueError('Missing or long label')
        kind=args.get('type','timer'); repeat=args.get('repeat','once')
        if kind not in ('timer','reminder') or repeat not in ('once','daily','weekly'): raise ValueError('Invalid schedule type')
        if kind=='timer' and repeat!='once': raise ValueError('Timers cannot repeat')
        zone=ZoneInfo(device['timezone']); now=dt.datetime.now(zone)
        if 'seconds' in args:
            seconds=args['seconds']
            if type(seconds) is not int or not 1<=seconds<=366*86400: raise ValueError('Invalid duration')
            due=now.timestamp()+seconds
            action['duration_seconds']=seconds
        else:
            naive=dt.datetime.fromisoformat(str(args.get('local_datetime','')))
            if naive.tzinfo is not None: raise ValueError('Use a local datetime without an offset')
            local=naive.replace(tzinfo=zone)
            if local.astimezone(dt.timezone.utc).astimezone(zone).replace(tzinfo=None)!=naive: raise ValueError('Nonexistent local time due to DST')
            if local.utcoffset()!=naive.replace(tzinfo=zone,fold=1).utcoffset(): raise ValueError('Ambiguous local time due to DST; ask for clarification')
            due=local.timestamp()
        if due<=now.timestamp() or due>now.timestamp()+366*86400: raise ValueError('Schedule date is past or too far away')
        action.update(type=kind,label=label,due_ms=int(due*1000),repeat=repeat,timezone=device['timezone'])
    else: raise ValueError('Unknown schedule operation')
    return {'status':'prepared'},action


def store():
    return Organizer(os.getenv('JARVIS_ORGANIZER_DB', str(Path(__file__).parent/'organizer.sqlite3')))
