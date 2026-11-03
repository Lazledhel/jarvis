import datetime as dt
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import workspace_store as ws
import knowledge_tools as kt
import background_services as bg
import information_tools as info
from library_extract import extract
from reply_language import choose_language,instruction

RSS='<rss><channel><item><title>F1 news</title><link>https://example.org/article</link><pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate><source url="https://example.org">Example</source></item></channel></rss>'


class WorkspaceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.env=patch.dict(os.environ,{'JARVIS_WORKSPACE_DB':str(self.root/'workspace.sqlite3'),'JARVIS_ORGANIZER_DB':str(self.root/'organizer.sqlite3'),'JARVIS_LIBRARY_ROOT':str(self.root/'library')});self.env.start();self.store=ws.store()
 def tearDown(self):self.env.stop();self.temp.cleanup()
 def test_profile_alias_expiration_persistence(self):
  self.store.profile({'operation':'set','key':'answer_length','value':'кратко'})
  self.store.profile({'operation':'set_alias','phrase':'мой отчёт','value':'прочитай последний отчёт'})
  self.assertEqual(ws.store().context()['preferences']['answer_length'],'кратко')
  self.assertEqual(ws.store().expand('МОЙ ОТЧЁТ'),'прочитай последний отчёт')
  self.assertEqual(ws.store().expand('покажи мой отчёт'),'покажи мой отчёт')
  self.store.profile({'operation':'set_state','value':'занят','minutes':1})
  with patch.object(ws.time,'time',return_value=ws.time.time()+120):self.assertIsNone(self.store.context()['temporary_state'])
  with self.assertRaises(ValueError):self.store.profile({'operation':'set','key':'api_key','value':'x'})
 def test_library_read_search_and_metadata(self):
  item=self.store.add_document('Пылесос','Замена фильтров двигателя',{'author':'owner'})
  result=self.store.library({'operation':'search','query':'ФИЛЬТР'})
  self.assertEqual(result['documents'][0]['id'],item['id'])
  self.assertEqual(self.store.library({'operation':'metadata','id':item['id']})['metadata']['author'],'owner')
  self.assertIn('двигателя',self.store.library({'operation':'read','id':item['id']})['text'])
 def test_journal_source_validation_and_persistence(self):
  source=self.store.add_document('source','measurement: 3 V',{})
  record=self.store.record({'operation':'write','kind':'lab_entry','title':'Тест','body':'Измерено 3 В','project':'робот','source_ids':[source['id']]})
  self.assertEqual(ws.store().record({'operation':'read','id':record['id']})['body'],'Измерено 3 В')
  with self.assertRaises(ValueError):self.store.record({'operation':'write','kind':'analysis','title':'x','body':'x','source_ids':['invented']})
 def test_inbox_ack_is_validated_and_persistent(self):
  ident=self.store.notify('Title','Body');self.assertEqual(ws.store().poll()[0]['id'],ident)
  self.store.acknowledge([ident]);self.assertEqual(ws.store().poll(),[])
  with self.assertRaises(ValueError):self.store.acknowledge(['bad'])
 def test_topic_removed_stays_removed_and_can_be_added(self):
  topic=bg.topics()[0];bg.execute({'operation':'remove_topic','id':topic['id']})
  self.assertNotIn(topic['id'],[x['id'] for x in bg.topics()])
  ws.store();self.assertNotIn(topic['id'],[x['id'] for x in bg.topics()])
  bg.execute({'operation':'add_topic','name':topic['name']});self.assertIn(topic['id'],[x['id'] for x in bg.topics()])
 def test_news_dates_sources_and_unavailable_fallback(self):
  with patch.object(info,'public_get',return_value=(RSS,'https://news.google.com/rss','application/xml')):
   data=bg.collect_news('F1');self.assertEqual(data['items'][0]['source'],'Example')
   result=bg.execute({'operation':'refresh','id':bg.topics()[0]['id']});self.assertFalse(result['results'][0]['stale'])
  with patch.object(info,'public_get',side_effect=TimeoutError):
   result=bg.execute({'operation':'refresh','id':bg.topics()[0]['id']});self.assertTrue(result['results'][0]['stale']);self.assertIsNotNone(result['results'][0]['cached'])
 def test_monitor_baseline_no_duplicate_and_private_url_blocked(self):
  job={'id':'a'*32,'kind':'page','config':json.dumps({'url':'https://example.org'}),'notify':1,'next_run':123}
  with patch.object(info,'fetch_page',return_value={'url':'https://example.org','title':'Page','text':'old'}):bg.run_job(job)
  self.assertEqual(self.store.poll(),[])
  with patch.object(info,'fetch_page',return_value={'url':'https://example.org','title':'Page','text':'new'}):bg.run_job(job);bg.run_job(job)
  self.assertEqual(len(self.store.poll()),1)
  with patch.object(info,'public_target',side_effect=ValueError):
   with self.assertRaises(ValueError):bg.execute({'operation':'watch_url','url':'http://127.0.0.1'})
 def test_notification_schedule_requires_time_and_city(self):
  with self.assertRaises(ValueError):bg.execute({'operation':'schedule_news','notify':True})
  with self.assertRaises(ValueError):bg.execute({'operation':'schedule_weather','notify':False})
  result=bg.execute({'operation':'schedule_news','notify':True,'daily_time':'08:00'},{'timezone':'Europe/Budapest'})
  self.assertTrue(result['notifications_enabled'])
 def test_import_path_bomb_and_actual_docx_xlsx_pdf(self):
  for name in ('../.env','C:\\secret.txt','../private.pdf'):
   with self.subTest(name=name),self.assertRaises(ValueError):kt.import_approved_file(name)
  with self.assertRaises(ValueError):kt.import_bytes('evil.exe',b'x')
  result=kt.import_bytes('note.txt','Привет из документа'.encode());self.assertEqual(result['status'],'imported')
  from docx import Document
  doc=Document();doc.add_paragraph('Документ для Jarvis');stream=io.BytesIO();doc.save(stream)
  self.assertEqual(kt.import_bytes('test.docx',stream.getvalue())['status'],'imported')
  from openpyxl import Workbook
  wb=Workbook();wb.active.append(['Voltage',3]);wb.active.append(['Formula','=1+2']);stream=io.BytesIO();wb.save(stream);wb.close()
  item=kt.import_bytes('test.xlsx',stream.getvalue());self.assertFalse(item['metadata']['formulas_evaluated'])
  self.assertIn('=1+2',self.store.library({'operation':'read','id':item['id']})['text'])
  from pypdf import PdfWriter
  from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
  pdf=PdfWriter();page=pdf.add_blank_page(width=200,height=100)
  font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
  page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):pdf._add_object(font)})})
  content=DecodedStreamObject();content.set_data(b'BT /F1 12 Tf 10 50 Td (Jarvis PDF text) Tj ET');page[NameObject('/Contents')]=pdf._add_object(content)
  stream=io.BytesIO();pdf.write(stream);parsed=kt.import_bytes('text.pdf',stream.getvalue())
  self.assertIn('Jarvis PDF text',self.store.library({'operation':'read','id':parsed['id']})['text'])
  writer=PdfWriter();writer.add_blank_page(width=100,height=100);stream=io.BytesIO();writer.write(stream)
  with self.assertRaises(ValueError):kt.import_bytes('scanned.pdf',stream.getvalue())
  bomb=io.BytesIO()
  with zipfile.ZipFile(bomb,'w',compression=zipfile.ZIP_DEFLATED) as archive:archive.writestr('huge.xml',b'x'*(26*1024*1024))
  with self.assertRaises(ValueError):kt.import_bytes('bomb.docx',bomb.getvalue())
 def test_image_metadata_without_recognition(self):
  from PIL import Image
  stream=io.BytesIO();Image.new('RGB',(32,16)).save(stream,format='PNG')
  item=kt.import_bytes('image.png',stream.getvalue());self.assertEqual(item['metadata']['width'],32);self.assertTrue(item['metadata']['metadata_only'])
 def test_engineering_si_and_statistics(self):
  self.assertEqual(kt.engineering('ohm_current',{'voltage':12,'resistance':100})['result'],.12)
  self.assertAlmostEqual(kt.engineering('resistors_parallel',values=[100,100])['result'],50)
  self.assertEqual(kt.engineering('heat',{'mass':1,'heat_capacity':4200,'delta_temperature':10})['result'],42000)
  self.assertEqual(kt.engineering('statistics',values=[1,2,3])['mean'],2)
  with self.assertRaises(ValueError):kt.engineering('ohm_current',{'voltage':12,'resistance':0})
  with self.assertRaises(ValueError):kt.engineering('statistics',values=[float('nan')])
 def test_gather_saves_real_source_ids_and_report_notification(self):
  with patch.object(info,'search_web',return_value={'results':[{'title':'Source','url':'https://example.org'}]}),patch.object(info,'fetch_page',return_value={'url':'https://example.org','title':'Source','text':'Evidence','retrieved_at':'2026-11-02T00:00:00Z'}):
   collected=kt.gather('research')
  ident=collected['sources'][0]['id'];self.assertEqual(self.store.library({'operation':'read','id':ident})['text'],'Evidence')
  saved=kt.execute('research_workspace',{'operation':'write','kind':'report','title':'Report','body':'Evidence is limited','source_ids':[ident],'notify':True})
  self.assertEqual(saved['status'],'saved');self.assertEqual(len(self.store.poll()),1)
 def test_language_detection_and_explicit_asr_language(self):
  for text,language in [('Bonjour, comment allez-vous?','fr'),('Сколько будет 2+2?','ru'),('Wie geht es dir?','de'),('Mennyi kettő meg kettő?','hu'),('こんにちは','ja')]:self.assertEqual(choose_language(text),language)
  self.assertEqual(choose_language('5','fr'),'fr');self.assertIn('French',instruction('fr'))


if __name__=='__main__':unittest.main()
