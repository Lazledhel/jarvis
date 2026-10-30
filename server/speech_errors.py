"""Sanitized speech failure diagnostics; never log command text, tokens or URLs."""
import json,logging,traceback,uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from fastapi import HTTPException
logger=logging.getLogger('jarvis.speech')
if not logger.handlers:
 try:handler=RotatingFileHandler(Path(__file__).with_name('speech-errors.log'),maxBytes=262144,backupCount=2,encoding='utf-8')
 except OSError:handler=logging.StreamHandler()
 handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'));logger.addHandler(handler);logger.setLevel(logging.ERROR)
def synthesize(synthesizer,text,language):
 try:return synthesizer(text,language)
 except Exception as error:
  reference=uuid.uuid4().hex[:12]
  logger.error('%s',json.dumps({'reference':reference,'stage':'speech','type':type(error).__name__,'cause_type':type(error.__cause__).__name__ if error.__cause__ else None,'upstream_status':getattr(error,'code',None),'frames':[Path(frame.filename).name+':'+str(frame.lineno) for frame in traceback.extract_tb(error.__traceback__)]}))
  message=('Синтезатор речи временно недоступен. Повторите запрос. Код: ' if language=='ru' else 'Speech synthesis is temporarily unavailable. Please try again. Reference: ')+reference
  raise HTTPException(503,message) from None
