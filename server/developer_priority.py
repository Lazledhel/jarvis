"""Give existing speech services priority over the optional developer model.

No network listener or model tool is exposed. Only a process whose executable
matches the dedicated developer runtime may be stopped.
"""
from contextlib import contextmanager
from pathlib import Path
import json,os,threading

ROOT=Path(os.getenv('JARVIS_DEVELOPER_ROOT',r'D:\JarvisAgent'))
def _release_developer():
 import ctypes
 from ctypes import wintypes as w
 try:data=json.loads((ROOT/'controller/inference.pid.json').read_text())
 except (OSError,ValueError):return
 pid=data.get('pid')
 if type(pid) is not int or pid<=0:return
 expected=os.path.normcase(str((ROOT/'tools/llama/llama-server.exe').resolve()))
 kernel=ctypes.WinDLL('kernel32',use_last_error=True)
 kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
 kernel.CloseHandle.argtypes=[w.HANDLE];kernel.CloseHandle.restype=w.BOOL
 kernel.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,ctypes.POINTER(w.DWORD)];kernel.QueryFullProcessImageNameW.restype=w.BOOL
 kernel.WaitForSingleObject.argtypes=[w.HANDLE,w.DWORD];kernel.WaitForSingleObject.restype=w.DWORD
 kernel.TerminateProcess.argtypes=[w.HANDLE,w.UINT];kernel.TerminateProcess.restype=w.BOOL
 handle=kernel.OpenProcess(0x101001,False,pid)
 if not handle:return
 try:
  buffer=ctypes.create_unicode_buffer(32768);size=w.DWORD(len(buffer))
  if not kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):return
  if os.path.normcase(buffer.value)!=expected:return
  if kernel.WaitForSingleObject(handle,5000)==258:
   if not kernel.TerminateProcess(handle,75):raise RuntimeError('Developer process could not yield GPU')
   if kernel.WaitForSingleObject(handle,5000)!=0:raise RuntimeError('Developer GPU release timed out')
 finally:kernel.CloseHandle(handle)

@contextmanager
def voice_priority():
 folder=ROOT/'controller'
 if os.name!='nt' or not folder.is_dir():yield;return
 marker=folder/'voice-priority'
 marker.touch()
 stop=threading.Event()
 def heartbeat():
  while not stop.wait(5):
   try:marker.touch()
   except OSError:pass
 worker=threading.Thread(target=heartbeat,name='voice-priority',daemon=True);worker.start()
 try:
  _release_developer()
  yield
 finally:
  stop.set();marker.touch()
