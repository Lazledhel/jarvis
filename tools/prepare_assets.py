"""Download official wake models and generate a neutral electronic cue locally."""
from pathlib import Path
import urllib.request,zipfile,tempfile,wave,math,struct
root=Path(__file__).resolve().parents[1]/'android/app/src/main/assets';root.mkdir(parents=True,exist_ok=True)
for name in ['vosk-model-small-en-us-0.15','vosk-model-small-ru-0.22']:
 if (root/name).is_dir():continue
 with tempfile.TemporaryDirectory() as tmp:
  archive=Path(tmp)/'model.zip';urllib.request.urlretrieve('https://alphacephei.com/vosk/models/'+name+'.zip',archive)
  with zipfile.ZipFile(archive) as z:
   for member in z.infolist():
    target=(root/member.filename).resolve()
    if not target.is_relative_to(root.resolve()):raise ValueError('Unsafe archive path')
   z.extractall(root)
cue=root/'effects/ready-neutral.wav';cue.parent.mkdir(exist_ok=True)
rate=16000
with wave.open(str(cue),'wb') as out:
 out.setnchannels(1);out.setsampwidth(2);out.setframerate(rate)
 out.writeframes(b''.join(struct.pack('<h',int(6500*math.sin(2*math.pi*(660 if i<rate*.09 else 880)*i/rate)*math.sin(math.pi*i/(rate*.18)))) for i in range(int(rate*.18))))
print('Wake models and neutral cue prepared; generated files are gitignored.')
