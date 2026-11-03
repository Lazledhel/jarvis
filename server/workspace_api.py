import base64
import json
from fastapi import APIRouter,Request,HTTPException
from starlette.concurrency import run_in_threadpool
import workspace_store
import knowledge_tools


def routes(authorize):
 router=APIRouter()
 @router.post('/library/import')
 async def upload(request:Request):
  authorize(request);body=bytearray()
  async for chunk in request.stream():
   body.extend(chunk)
   if len(body)>6*1024*1024:raise HTTPException(413,'Document request exceeds 6 MiB')
  try:
   data=json.loads(body);name=data['name'];content=base64.b64decode(data['content'],validate=True)
   return await run_in_threadpool(knowledge_tools.import_bytes,name,content)
  except Exception as error:
   if isinstance(error,HTTPException):raise
   raise HTTPException(400,'Could not import document: supported text formats, up to 4 MiB; encrypted/scanned/invalid files are not supported')
 @router.get('/inbox/poll')
 async def poll(request:Request):
  authorize(request);return {'items':await run_in_threadpool(lambda:workspace_store.store().poll())}
 @router.post('/inbox/ack')
 async def ack(request:Request):
  authorize(request);body=bytearray()
  async for chunk in request.stream():
   body.extend(chunk)
   if len(body)>4096:raise HTTPException(413)
  try:data=json.loads(body);await run_in_threadpool(workspace_store.store().acknowledge,data['ids'])
  except Exception:raise HTTPException(400,'Invalid notification acknowledgement')
  return {'ok':True}
 return router
