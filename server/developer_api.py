"""Authenticated developer jobs. Deliberately has no token-approval endpoint.

Development requests are intercepted before the ordinary conversational model.
Only the separately budgeted supervisor is allowed to call Luna for these jobs.
"""
from pathlib import Path
import json,os,re,subprocess,time,uuid

ROOT=Path(os.getenv('JARVIS_DEVELOPER_ROOT',r'D:\JarvisAgent'))
PILOT='android-calculator-pilot'
ACTIVE={'preparing','queued','local_coding','sandbox_build_and_test','waiting_resources'}
LABELS={'preparing':'подготовка','queued':'в очереди','local_coding':'локальная модель пишет код','sandbox_build_and_test':'сборка и проверка в изолированной среде','waiting_resources':'ожидание свободных ресурсов или завершения настройки стенда','awaiting_owner':'нужно согласование владельца','failed':'остановлено из-за технической ошибки','needs_attention':'нужен разбор отчёта','ready':'готово'}
def project_path(project):
 if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',project):raise ValueError('Invalid project identifier')
 return ROOT/'jobs'/project
def status(project):
 folder=project_path(project)
 if not folder.is_dir():return None
 p=folder/'state.json'
 result=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'state':'queued'}
 # Exception traces remain local; only useful status fields are sent to clients.
 return {'project':project,**{k:v for k,v in result.items() if k in ('state','iteration','model','reason','budget')},'artifacts':[name for name in ['Calculator.apk','Calculator-source.zip'] if (folder/name).is_file()]}
def start_pilot():
 result=subprocess.run(['schtasks.exe','/Run','/TN','JarvisAgentPilot'],capture_output=True,timeout=8,creationflags=subprocess.CREATE_NO_WINDOW)
 return result.returncode==0
def create(request):
 if not isinstance(request,str) or not request.strip() or len(request)>3000:raise ValueError('Invalid development request')
 normalized=request.lower().replace('ё','е')
 pilot=bool(re.search(r'калькулятор|calculator',normalized) and re.search(r'андроид|android',normalized))
 project=PILOT if pilot else 'project-'+uuid.uuid4().hex[:16]
 folder=project_path(project);folder.mkdir(parents=True,exist_ok=True)
 if not (folder/'request.json').exists():(folder/'request.json').write_text(json.dumps({'request':request,'created':time.time()},ensure_ascii=False),encoding='utf-8')
 current=status(project)
 if not pilot:
  (folder/'state.json').write_text(json.dumps({'state':'awaiting_owner','reason':'First project-specific block of up to 1,000,000 Luna input+output tokens requires explicit owner approval'}),encoding='utf-8')
 elif current['state'] not in ACTIVE and current['state']!='ready':start_pilot()
 elif current['state']=='queued':start_pilot()
 return status(project)
def developer_reply(text,lang='ru'):
 value=text.lower().replace('ё','е').strip()
 if re.search(r'(?:одобряю|разрешаю|согласую|подтверждаю).{0,40}(?:миллион|1[ .]?000[ .]?000).{0,15}токен',value):
  return 'Голосовая команда не меняет лимит. Для согласования блока используется отдельное подтверждение владельца.'
 if re.search(r'статус.{0,30}(?:разработ|калькулятор)|что.{0,20}(?:с калькулятором|разработчик)',value):
  s=status(PILOT)
  return 'Пилот калькулятора пока не запущен.' if not s else 'Android-калькулятор: '+LABELS.get(s['state'],s['state'])+'.'
 if re.search(r'^(?:напиши|создай|добавь).{0,12}(?:заметк|напоминани|список покупок)',value):return None
 if not re.search(r'\b(?:напиши|создай|разработай|сделай|write|create|develop|build)\b.{0,100}\b(?:калькулятор|приложени[ея]|программ[уы]|скрипт|бота|игру|сайт|код|модуль|проект|calculator|application|app|script|program)\b',value):return None
 if not ROOT.is_dir():return 'Среда агента-разработчика ещё не установлена. Запрос не передавался разговорной модели.'
 s=create(text)
 if s['project']!=PILOT:return 'Задача записана. Для новой программы нужно отдельно согласовать первый блок до миллиона суммарных входных и выходных токенов Luna. Код проекта: '+s['project']+'.'
 if s['state']=='ready':return 'Пилот Android-калькулятора готов. APK, исходники и результаты проверок сохранены на сервере.'
 return 'Задача Android-калькулятора принята. Текущий этап: '+LABELS.get(s['state'],s['state'])+'. Разработка использует уже согласованный первый блок токенов; следующий автоматически не подключается.'
def routes(check):
 from fastapi import APIRouter,Request,HTTPException
 from fastapi.responses import FileResponse
 router=APIRouter(prefix='/developer')
 @router.get('/jobs')
 def jobs(request:Request):
  check(request)
  folder=ROOT/'jobs'
  return {'jobs':[] if not folder.exists() else [status(p.name) for p in list(folder.iterdir())[:100] if p.is_dir() and re.fullmatch('[a-z0-9][a-z0-9_-]{0,63}',p.name)]}
 @router.post('/jobs')
 async def enqueue(request:Request):
  check(request);body=await request.body()
  if len(body)>16000:raise HTTPException(413)
  try:return create(json.loads(body)['request'])
  except (ValueError,KeyError):raise HTTPException(400,'Invalid development request')
 @router.get('/jobs/{project}')
 def job(project:str,request:Request):
  check(request)
  try:result=status(project)
  except ValueError:raise HTTPException(400)
  if result is None:raise HTTPException(404)
  return result
 @router.get('/jobs/{project}/artifact/{name}')
 def artifact(project:str,name:str,request:Request):
  check(request)
  if name not in ['Calculator.apk','Calculator-source.zip']:raise HTTPException(404)
  try:path=project_path(project)/name
  except ValueError:raise HTTPException(400)
  if not path.is_file():raise HTTPException(404)
  return FileResponse(path,filename=name,media_type='application/vnd.android.package-archive' if name.endswith('.apk') else 'application/zip')
 return router
