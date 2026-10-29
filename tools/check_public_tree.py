"""Reject deployment-specific content and generated/private files before publication."""
from pathlib import Path
import re,subprocess,sys
root=Path(__file__).resolve().parents[1]
if (root/'.git').exists():
 files=[root/p for p in subprocess.check_output(['git','ls-files'],cwd=root,text=True).splitlines()]
else:files=[p for p in root.rglob('*') if p.is_file() and not any(x in p.parts for x in ['.git','.cache','.venv','build','__pycache__'])]
failures=[]
patterns=[('IPv4 literal',r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])'),('private key',r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),('key-like credential',r'(?<![A-Za-z0-9])(?:ghp_|github_pat_|sk-proj-|sk-)[A-Za-z0-9_-]{20,}'),('personal Windows path',r'[A-Za-z]:\\(?:Users|Phone-Backups|TelegramWhisper|JarvisVoice)\\')]
for p in files:
 if p.name==Path(__file__).name:continue
 if p.suffix.lower() in ['.apk','.p12','.jks','.keystore','.key','.crt','.pem','.db','.sqlite','.wav','.mp3','.otf','.ttf','.aar','.jar']:failures.append((str(p.relative_to(root)),'private/generated/binary file'));continue
 try:text=p.read_text('utf-8')
 except UnicodeDecodeError:failures.append((str(p.relative_to(root)),'unexpected binary'));continue
 for label,pattern in patterns:
  if re.search(pattern,text):failures.append((str(p.relative_to(root)),label))
for path,label in failures:print(path+': '+label)
print('Public source check:',len(files),'files;',len(failures),'findings')
sys.exit(bool(failures))
