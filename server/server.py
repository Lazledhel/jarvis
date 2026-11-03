import os,io,re,json,base64,secrets,threading,time,wave
from pathlib import Path
ROOT=Path(__file__).parent
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
# CUDA libraries are imported read-only from the existing Whisper environment.
_dll=[]
_dirs=sorted({p.parent for p in Path(r'C:\TelegramWhisper\.venv\Lib\site-packages\nvidia').rglob('*.dll')})
for d in _dirs:_dll.append(os.add_dll_directory(str(d)))
os.environ['PATH']=os.pathsep.join(map(str,_dirs))+os.pathsep+os.environ.get('PATH','')
from fastapi import FastAPI,Request,HTTPException
from piper import PiperVoice
from faster_whisper import WhisperModel
from openai import OpenAI
from provider import generate
from reply_language import choose_language
from dialogues import Dialogues
from speech_errors import synthesize
from computer_bridge import ComputerQueue,computer_reply,routes
dialogs=Dialogues(r'D:\Jarvis-Dialogs')
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
computer_queue=ComputerQueue(ROOT/'computer-jobs.sqlite3')
app.include_router(routes(computer_queue))
gate=threading.Lock();voices={};whisper=None
TOKEN=os.environ['PHONE_TOKEN'];rate={};rate_lock=threading.Lock()
def check(request):
 ip=request.client.host;now=time.monotonic()
 with rate_lock:
  if len(rate)>1024:rate.clear()
  stamps=rate.setdefault(ip,[]);stamps[:]=[t for t in stamps if now-t<60]
  if len(stamps)>=30:raise HTTPException(429,'Try again in a minute')
  stamps.append(now)
 if not secrets.compare_digest(request.headers.get('authorization','').encode(),'Bearer '.encode()+TOKEN.encode()):raise HTTPException(401,'Unauthorized')
from workspace_api import routes as workspace_routes
import background_services
import workspace_store
from reply_language import LANGUAGES
app.include_router(workspace_routes(check))
from developer_api import developer_reply, routes as developer_routes
app.include_router(developer_routes(check))
from dashboard_api import routes as dashboard_routes, voice_reply as dashboard_reply
app.include_router(dashboard_routes(check, lambda text: synthesize(tts,text,"ru")))
from operations_center import screen_requested

def tts(text,lang):
 if os.getenv('JARVIS_TTS_ENGINE','piper')=='xtts':
  import urllib.request
  req=urllib.request.Request('http://127.0.0.1:8766/tts',data=json.dumps({'text':text,'lang':lang}).encode('utf-8'),headers={'Content-Type':'application/json','Authorization':'Bearer '+TOKEN})
  with urllib.request.urlopen(req,timeout=80) as response:
   audio=response.read(8000001)
   if len(audio)>8000000 or not audio.startswith(b'RIFF'):raise ValueError('Invalid TTS response')
   return audio
 if lang not in ('ru','en'):raise ValueError('This language requires XTTS')
 name='ru_RU-denis-medium' if lang=='ru' else os.getenv('JARVIS_EN_VOICE','en_GB-jarvis-high')
 if name not in voices:voices[name]=PiperVoice.load(str(ROOT/'voices'/(name+'.onnx')),use_cuda=False)
 out=io.BytesIO()
 with wave.open(out,'wb') as wav:voices[name].synthesize_wav(text,wav)
 return out.getvalue()
from gpu_idle import IdleResource
def release_whisper():
 global whisper
 whisper=None
 import gc
 gc.collect()
whisper_idle=IdleResource(release_whisper)

@whisper_idle.wrap
def stt(audio, desktop=False):
 global whisper
 import numpy as np
 from faster_whisper.audio import decode_audio
 samples=decode_audio(io.BytesIO(audio),sampling_rate=16000)
 if not samples.size:return '', 'ru'
 samples-=float(np.mean(samples));rms=float(np.sqrt(np.mean(samples*samples)));peak=float(np.max(np.abs(samples)))
 if rms>0.0001 and peak>0: samples*=min(12.0,max(1.0,0.075/rms),0.97/peak)
 if whisper is None:whisper=WhisperModel(os.getenv('WHISPER_MODEL','medium'),device='cuda',compute_type='int8_float16',cpu_threads=3,num_workers=1,download_root=r'C:\TelegramWhisper\models',local_files_only=True)
 segments,info=whisper.transcribe(samples,beam_size=3,best_of=1,temperature=0,vad_filter=True,condition_on_previous_text=False,initial_prompt=None if desktop else "Jarvis / Джарвис. VPN / ВПН. V2RayTun. Yandex Maps / Яндекс Карты. Google Maps / Google Карты. Budapest / Будапешт.")
 if desktop and info.language not in ('ru','en'):
  raise HTTPException(422,'Повтори команду по-русски или по-английски')
 return ' '.join(s.text.strip() for s in segments).strip(),info.language
@app.get('/health')
def health(request:Request):
 check(request);return {'ok':True,'api_key_ready':bool(os.getenv('AIML_API_KEY')),'provider':'AI/ML API','model':os.getenv('AIML_MODEL','gpt-6-luna'),'stt':'Whisper '+os.getenv('WHISPER_MODEL','medium')+' CUDA','tts':os.getenv('JARVIS_TTS_ENGINE','piper'),'context_timeout_seconds':180,'dialogues_txt':True,'stt_loaded':whisper is not None,'gpu_idle_seconds':whisper_idle.seconds}
@app.on_event('startup')
def start_idle_monitor():
 whisper_idle.start()
 background_services.collector.start()

@app.on_event('shutdown')
def stop_idle_monitor():
 whisper_idle.stop.set()
 background_services.collector.stop()

_desktop_phrases = {}
_desktop_phrase_lock = threading.Lock()

@app.get('/dashboard/voice/{phrase}')
def desktop_phrase(request: Request, phrase: str):
 check(request)
 phrases={'help':'Чем я могу помочь?', 'mail':'Сэр, вам пришло важное письмо'}
 if phrase not in phrases:raise HTTPException(404)
 with _desktop_phrase_lock:
  if phrase not in _desktop_phrases:
   _desktop_phrases[phrase]=base64.b64encode(synthesize(tts,phrases[phrase],'ru')).decode()
  return {'audio':_desktop_phrases[phrase]}


@app.post('/dashboard/wake')
async def desktop_wake(request: Request):
 check(request)
 body=bytearray()
 async for chunk in request.stream():
  body.extend(chunk)
  if len(body)>400000:raise HTTPException(413,'Wake audio too large')
 try:
  audio=base64.b64decode(json.loads(body)['audio'],validate=True)
  with wave.open(io.BytesIO(audio)) as wav:
   if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000) or wav.getnframes()>16000*8:
    raise ValueError()
 except (ValueError,KeyError,TypeError,EOFError,wave.Error):
  raise HTTPException(400,'Invalid wake audio')
 if not gate.acquire(False):return {'wake':False}
 try:
  from starlette.concurrency import run_in_threadpool
  text,_=await run_in_threadpool(stt,audio,True)
  return {'wake':bool(re.search(r'(?<!\w)(?:джарвис|jarvis)(?!\w)',text,re.I))}
 except HTTPException as error:
  if error.status_code!=422:raise
  return {'wake':False}
 finally:gate.release()


@app.post('/ask')
async def ask(request:Request):
 check(request)
 if not gate.acquire(False):raise HTTPException(429,'Assistant is busy')
 try:
  # Enforce a body limit while reading, independently of client Content-Length.
  body=bytearray()
  async for chunk in request.stream():
   body.extend(chunk)
   if len(body)>3000000:raise HTTPException(413,'Command too long')
  try:data=json.loads(body)
  except Exception:raise HTTPException(400,'Invalid JSON')
  from starlette.concurrency import run_in_threadpool
  return await run_in_threadpool(answer,data)
 finally:gate.release()
def answer(data):
 text=str(data.get('text',''))[:3000];lang=choose_language(text)
 if not text:
  try:audio=base64.b64decode(data.get('audio',''),validate=True)
  except Exception:raise HTTPException(400,'Invalid audio')
  try:
   with wave.open(io.BytesIO(audio)) as w:
    if w.getnchannels()!=1 or w.getsampwidth()!=2 or w.getframerate()!=16000 or w.getnframes()>16000*30:raise ValueError()
   text,lang=stt(audio,data.get("desktop") is True)
   if data.get("desktop") is True and re.search(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]",text):
    raise HTTPException(422,"Повтори команду по-русски или по-английски")
  except HTTPException:raise
  except Exception:raise HTTPException(400,'Could not recognize WAV')
 text=re.sub(r'^\s*(?:jarvis|джарвис)[,.:!\s]*','',text,flags=re.I)
 lang=choose_language(text,lang)
 if not text:raise HTTPException(422,'Речь не распознана. Повторите, пожалуйста.' if lang=='ru' else 'Speech not recognized. Please repeat.')
 if data.get("desktop") is True and screen_requested(text):
  return {"heard":text,"screen_requested":True,"conversation_id":data.get("conversation_id","")}
 preferred=workspace_store.store().context()['preferences'].get('default_language')
 if preferred in LANGUAGES:lang=preferred
 session=dialogs.get(data.get('conversation_id',''));session['language']=lang;dialogs.write(session,'Вы',text);action=None
 development_reply=dashboard_reply(text)
 if development_reply is None:development_reply=developer_reply(text,lang)
 desktop_reply=None if development_reply is not None else computer_reply(computer_queue,text,lang)
 if development_reply is not None:
  reply=development_reply;sources=[]
 elif desktop_reply is not None:
  reply=desktop_reply;sources=[]
 elif not (os.getenv('AIML_API_KEY') or os.getenv('JARVIS_OFFLINE_MODEL') or os.getenv('JARVIS_MAIL_LOCAL_MODEL')):
  reply='Распознавание работает. Добавьте ключ AI ML API на сервере в файл настройки и перезапустите Джарвиса.' if lang=='ru' else 'Speech recognition works. Add your AI ML API key on the server and restart Jarvis.'
  sources=[]
 else:
  history=list(session['history'])
  try:
   from organizer import device_context
   try:device=device_context(data)
   except (ValueError,KeyError):device={'version':0}
   reply,sources,action=generate(history,text,lang,device)
  except Exception as e:
   status=getattr(e,'status_code',None)
   if isinstance(e,LookupError):
    reply='Запрошенная модель GPT-6 Luna недоступна в каталоге вашего аккаунта AI ML API. Другую модель я не выбирал.' if lang=='ru' else 'The requested GPT-6 Luna model is unavailable in your AI ML API account. No other model was selected.'
   elif status in (401,403):
    reply='AI ML API отклонил ключ или доступ. Проверьте ключ и разрешения аккаунта.' if lang=='ru' else 'AI ML API denied access. Please check your key and account permissions.'
   else:reply='Сейчас сервис AI ML API не ответил. Попробуйте повторить запрос чуть позже.' if lang=='ru' else 'AI ML API is currently unavailable. Please try again shortly.'
   sources=[]
 if not reply:raise HTTPException(502,'Empty response')
 dialogs.finish(session,text,reply,sources,action)
 spoken=re.sub(r'https?://\S+','',re.sub(r'\[([^\]]+)\]\([^)]+\)',r'\1',reply));spoken=re.sub(r'[*#`]','',spoken)[:3500]
 try:audio=synthesize(tts,spoken,lang)
 except HTTPException:
  if data.get('desktop') is not True:raise
  audio=b''
 return {'heard':text,'reply':reply,'language':lang,'sources':sources,'audio':base64.b64encode(audio).decode(),'api_key_ready':bool(os.getenv('AIML_API_KEY')),'conversation_id':session['id'],'action':action}
@app.post('/action-result')
async def action_result(request:Request):
 check(request);body=await request.body()
 if len(body)>4096:raise HTTPException(413)
 data=json.loads(body);dialogs.result(data.get('conversation_id',''),data.get('action_id',''),data.get('result',''));return {'ok':True}
@app.post('/reply-finished')
async def reply_finished(request:Request):
 check(request);body=await request.body()
 if len(body)>1024:raise HTTPException(413)
 data=json.loads(body)
 with dialogs.lock:
  s=dialogs.sessions.get(str(data.get('conversation_id','')))
  if s:s['last']=dialogs.clock()
 return {'ok':True}
if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host='0.0.0.0',port=8765,ssl_keyfile=str(ROOT/'server.key'),ssl_certfile=str(ROOT/'server.crt'),access_log=False,log_level='warning',limit_concurrency=8,timeout_keep_alive=3,server_header=False)
