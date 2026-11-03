"""Isolated text/metadata parser. Called in a process with a caller-enforced deadline."""
import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path


def extract(path):
 path=Path(path);data=path.read_bytes()
 if len(data)>4*1024*1024:raise ValueError('File exceeds 4 MiB')
 suffix=path.suffix.lower();metadata={'format':suffix,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
 if suffix in ('.docx','.xlsx'):
  with zipfile.ZipFile(io.BytesIO(data)) as archive:
   infos=archive.infolist()
   if len(infos)>3000 or sum(x.file_size for x in infos)>25*1024*1024:raise ValueError('Expanded archive too large')
   for item in infos:
    if item.filename.endswith('.xml') and b'<!DOCTYPE' in archive.read(item).upper():raise ValueError('XML DTD is not accepted')
 if suffix in ('.txt','.md','.csv','.json'):
  try:text=data.decode('utf-8-sig');metadata['encoding']='utf-8'
  except UnicodeDecodeError:text=data.decode('cp1251');metadata['encoding']='cp1251 fallback'
  if '\x00' in text:raise ValueError('Binary data is not text')
  if suffix=='.csv':
   rows=list(csv.reader(io.StringIO(text)))[:2000];metadata['rows_read']=len(rows);text='\n'.join(' | '.join(x[:100]) for x in rows)
 elif suffix=='.pdf':
  from pypdf import PdfReader
  reader=PdfReader(io.BytesIO(data))
  if reader.is_encrypted:raise ValueError('Encrypted PDF not supported')
  metadata['pages']=len(reader.pages);metadata['properties']={str(k):str(v)[:1000] for k,v in (reader.metadata or {}).items()}
  parts=[]
  for page in reader.pages[:200]:
   parts.append(page.extract_text() or '')
   if sum(map(len,parts))>120000:break
  text='\n\n'.join(parts);metadata['ocr']=False
 elif suffix=='.docx':
  from docx import Document
  document=Document(io.BytesIO(data));metadata['author']=document.core_properties.author;metadata['title']=document.core_properties.title
  parts=[p.text for p in document.paragraphs]
  for table in document.tables:
   for row in table.rows:parts.append(' | '.join(c.text for c in row.cells))
  text='\n'.join(parts)
 elif suffix=='.xlsx':
  from openpyxl import load_workbook
  workbook=load_workbook(io.BytesIO(data),read_only=True,data_only=False,keep_links=False)
  try:
   metadata['sheets']=workbook.sheetnames;metadata['formulas_evaluated']=False;parts=[]
   for sheet in workbook.worksheets[:20]:
    parts.append('Sheet: '+sheet.title)
    for row in sheet.iter_rows(max_row=2000,max_col=100,values_only=True):
     parts.append(' | '.join('' if x is None else str(x) for x in row))
     if sum(map(len,parts))>120000:break
    if sum(map(len,parts))>120000:break
   text='\n'.join(parts)
  finally:workbook.close()
 elif suffix in ('.jpg','.jpeg','.png','.webp'):
  from PIL import Image,ExifTags
  with Image.open(io.BytesIO(data)) as image:
   metadata.update(width=image.width,height=image.height,image_mode=image.mode,image_format=image.format)
   if image.width*image.height>50000000:raise ValueError('Image dimensions exceed metadata import limit')
   exif=image.getexif();metadata['exif']={str(ExifTags.TAGS.get(k,k)):str(v)[:1000] for k,v in exif.items()}
   gps=exif.get_ifd(34853) if exif else {}
   if gps:
    metadata['gps']={str(ExifTags.GPSTAGS.get(k,k)):str(v)[:500] for k,v in gps.items()}
    def decimal(parts,ref):return (float(parts[0])+float(parts[1])/60+float(parts[2])/3600)*(-1 if ref in ('S','W') else 1)
    if 2 in gps and 4 in gps:
     metadata['gps_latitude']=decimal(gps[2],gps.get(1));metadata['gps_longitude']=decimal(gps[4],gps.get(3))
  metadata['metadata_only']=True;text='Image metadata (no visual recognition or OCR):\n'+json.dumps(metadata,ensure_ascii=False)
 else:raise ValueError('Unsupported document or image metadata format')
 return {'text':text[:120000],'metadata':metadata,'truncated':len(text)>120000}


if __name__=='__main__':
 sys.stdout.reconfigure(encoding='utf-8')
 try:print(json.dumps(extract(sys.argv[1]),ensure_ascii=False))
 except Exception as error:
  print(json.dumps({'error':type(error).__name__,'message':str(error)[:200]}));sys.exit(1)
