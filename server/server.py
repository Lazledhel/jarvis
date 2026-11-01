import os,io,re,json,base64,secrets,threading,time,wave
from pathlib import Path
ROOT=Path(__file__).parent
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
# Optional Windows CUDA DLL directories, configured on the deployment host.
_dll=[]
if os.name=='nt':
 for folder in os.getenv('JARVIS_CUDA_DLL_DIRS','').split(os.pathsep):
  if folder and Path(folder).is_dir():_dll.append(os.add_dll_directory(folder))
from fastapi import FastAPI,Request,HTTPException
from piper import PiperVoice
from faster_whisper import WhisperModel
from openai import OpenAI
from provider import generate
from reply_language import choose_language
from dialogues import Dialogues
from speech_errors import synthesize
from computer_bridge import ComputerQueue,computer_reply,routes
dialogs=Dialogues(os.getenv('JARVIS_DIALOG_DIR',str(ROOT/'dialogues')))
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
def tts(text,lang):
 if os.getenv('JARVIS_TTS_ENGINE','piper')=='xtts':
  import urllib.request
  req=urllib.request.Request(os.getenv('JARVIS_VOICE_URL','http://localhost:8766/tts'),data=json.dumps({'text':text,'lang':lang}).encode('utf-8'),headers={'Content-Type':'application/json','Authorization':'Bearer '+TOKEN})
  with urllib.request.urlopen(req,timeout=80) as response:
   audio=response.read(8000001)
   if len(audio)>8000000 or not audio.startswith(b'RIFF'):raise ValueError('Invalid TTS response')
   return audio
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
def stt(audio):
 global whisper
 import numpy as np
 from faster_whisper.audio import decode_audio
 samples=decode_audio(io.BytesIO(audio),sampling_rate=16000)
 if not samples.size:return '', 'ru'
 samples-=float(np.mean(samples));rms=float(np.sqrt(np.mean(samples*samples)));peak=float(np.max(np.abs(samples)))
 if rms>0.0001 and peak>0: samples*=min(12.0,max(1.0,0.075/rms),0.97/peak)
 if whisper is None:whisper=WhisperModel(os.getenv('WHISPER_MODEL','medium'),device=os.getenv('WHISPER_DEVICE','cuda'),compute_type=os.getenv('WHISPER_COMPUTE_TYPE','int8_float16'),cpu_threads=3,num_workers=1,download_root=os.getenv('WHISPER_MODEL_DIR',str(ROOT/'models')),local_files_only=False)
 segments,info=whisper.transcribe(samples,beam_size=3,best_of=1,temperature=0,vad_filter=True,condition_on_previous_text=False,initial_prompt="Jarvis / Джарвис. VPN / ВПН. V2RayTun. Yandex Maps / Яндекс Карты. Google Maps / Google Карты. Budapest / Будапешт.")
 return ' '.join(s.text.strip() for s in segments).strip(),info.language
@app.get('/health')
def health(request:Request):
 check(request);return {'ok':True,'api_key_ready':bool(os.getenv('AIML_API_KEY')),'provider':'AI/ML API','model':os.getenv('AIML_MODEL','gpt-6-luna'),'stt':'Whisper '+os.getenv('WHISPER_MODEL','medium')+' CUDA','tts':os.getenv('JARVIS_TTS_ENGINE','piper'),'context_timeout_seconds':180,'dialogues_txt':True,'stt_loaded':whisper is not None,'gpu_idle_seconds':whisper_idle.seconds}
@app.on_event('startup')
def start_idle_monitor():
 whisper_idle.start()

@app.on_event('shutdown')
def stop_idle_monitor():
 whisper_idle.stop.set()

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
   text,lang=stt(audio)
  except Exception:raise HTTPException(400,'Could not recognize WAV')
 text=re.sub(r'^\s*(?:jarvis|джарвис)[,.:!\s]*','',text,flags=re.I)
 lang=choose_language(text,lang)
 if not text:raise HTTPException(422,'Речь не распознана. Повторите, пожалуйста.' if lang=='ru' else 'Speech not recognized. Please repeat.')
 session=dialogs.get(data.get('conversation_id',''));session['language']=lang;dialogs.write(session,'Вы',text);action=None
 desktop_reply=computer_reply(computer_queue,text,lang)
 if desktop_reply is not None:
  reply=desktop_reply;sources=[]
 elif not os.getenv('AIML_API_KEY'):
  reply='Распознавание работает. Добавьте ключ AI ML API на сервере в файл настройки и перезапустите Джарвиса.' if lang=='ru' else 'Speech recognition works. Add your AI ML API key on the server and restart Jarvis.'
  sources=[]
 else:
  history=list(session['history'])
  try:
   reply,sources,action=generate(history,text,lang)
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
 audio=synthesize(tts,spoken,lang)
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
 uvicorn.run(app,host=os.getenv('JARVIS_BIND_HOST','localhost'),port=int(os.getenv('JARVIS_PORT','8765')),ssl_keyfile=str(ROOT/'server.key'),ssl_certfile=str(ROOT/'server.crt'),access_log=False,log_level='warning',limit_concurrency=8,timeout_keep_alive=3,server_header=False)
