import os,io,wave,secrets,threading,time,json,sys
from pathlib import Path
if __name__=='__main__':
 sys.stdout=open(Path(__file__).parent/'worker.log','a',encoding='utf-8',buffering=1);sys.stderr=sys.stdout
from dotenv import dotenv_values
ROOT=Path(__file__).parent
TOKEN=dotenv_values(os.getenv('JARVIS_ENV_FILE',str(ROOT/'.env')))['PHONE_TOKEN']
import numpy as np,torch
from fastapi import FastAPI,Request,HTTPException,Response
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.models.xtts import Xtts,XttsAudioConfig,XttsArgs
from TTS.config.shared_configs import BaseDatasetConfig
torch.serialization.add_safe_globals([XttsConfig,XttsAudioConfig,XttsArgs,BaseDatasetConfig])
torch.set_num_threads(4)
app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None);gate=threading.Lock();model=None;conditioning=None;last_timing={}
def authorize(request):
 if not secrets.compare_digest(request.headers.get('authorization','').encode(),('Bearer '+TOKEN).encode()):raise HTTPException(401)
def load():
 global model,conditioning
 if model is not None:return
 if not torch.cuda.is_available():raise RuntimeError('CUDA required')
 config=XttsConfig();config.load_json(str(ROOT/'model/config.json'));model=Xtts.init_from_config(config)
 model.load_checkpoint(config,checkpoint_dir=str(ROOT/'model'),eval=True,use_deepspeed=False);model.cuda()
 conditioning=model.get_conditioning_latents(audio_path=[str(ROOT/'reference/jarvis-reference.wav')],gpt_cond_len=12,max_ref_length=16,sound_norm_refs=True)
from gpu_idle import IdleResource
def release_voice():
 global model,conditioning
 conditioning=None
 model=None
 import gc
 gc.collect()
 if torch.cuda.is_initialized():
  torch.cuda.empty_cache()
voice_idle=IdleResource(release_voice)

@voice_idle.wrap
def render(text,lang,effects=True):
 try:load()
 except Exception:
  release_voice()
  raise
 t=time.perf_counter()
 with torch.inference_mode():
  result=model.inference(text,lang,*conditioning,temperature=0.65,repetition_penalty=5.0,speed=1.06,enable_text_splitting=True)
 wav=np.asarray(result['wav'],dtype=np.float32)
 if not len(wav) or not np.isfinite(wav).all():raise ValueError('Invalid audio')
 if effects:
  from scipy.signal import butter,sosfilt
  wav=sosfilt(butter(2,[100,7400],btype='bandpass',fs=24000,output='sos'),wav).astype(np.float32)
  original=wav.copy()
  for samples,gain in [(192,.035),(384,.02)]:wav[samples:]+=original[:-samples]*gain
 peak=float(np.max(np.abs(wav)));wav*=min(.92/max(peak,.001),1.4)
 out=io.BytesIO()
 with wave.open(out,'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(24000);w.writeframes((np.clip(wav,-1,1)*32767).astype('<i2').tobytes())
 global last_timing
 last_timing={'language':lang,'synthesis_seconds':round(time.perf_counter()-t,3),'audio_seconds':round(len(wav)/24000,3),'gpu_memory_mib':round(torch.cuda.memory_allocated()/1048576)}
 return out.getvalue()
@app.on_event('startup')
def start_idle_monitor():
 voice_idle.start()

@app.on_event('shutdown')
def stop_idle_monitor():
 voice_idle.stop.set()

@app.get('/health')
def health(request:Request):authorize(request);return {'ready':True,'model_loaded':model is not None,'gpu_idle_seconds':voice_idle.seconds,'engine':'XTTS-v2','voice':'Priler jarvis-remaster reference','last_timing':last_timing}
@app.post('/tts')
async def speak(request:Request):
 authorize(request)
 if not gate.acquire(False):raise HTTPException(429)
 try:
  body=bytearray()
  async for chunk in request.stream():
   body.extend(chunk)
   if len(body)>20000:raise HTTPException(413)
  try:data=json.loads(body);text=data['text'];lang=data['lang']
  except Exception:raise HTTPException(400)
  if not isinstance(text,str) or not text.strip() or len(text)>3500 or lang not in ('ru','en'):raise HTTPException(400)
  from starlette.concurrency import run_in_threadpool
  audio=await run_in_threadpool(render,text,lang)
  return Response(audio,media_type='audio/wav')
 finally:gate.release()
if __name__=='__main__':
 import uvicorn
 uvicorn.run(app,host=os.getenv('JARVIS_VOICE_BIND_HOST','localhost'),port=8766,access_log=False,log_level='warning',server_header=False,limit_concurrency=4)
