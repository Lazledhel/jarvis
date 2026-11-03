import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import organizer as o


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'organizer.sqlite3'
        self.store=o.Organizer(self.path)
    def tearDown(self):self.temp.cleanup()
    def test_persistence_and_cyrillic_search(self):
        item=self.store.execute({'operation':'add','category':'note','title':'Паспорт','body':'Проверить билеты'},'one')
        restarted=o.Organizer(self.path)
        results=restarted.execute({'operation':'search','category':'note','query':'пАСпОРТ'},'read')['entries']
        self.assertEqual(results[0]['id'],item['id'])
        self.assertEqual(results[0]['body'],'Проверить билеты')
    def test_replayed_write_does_not_duplicate(self):
        args={'operation':'add','category':'shopping','title':'Молоко'}
        self.assertEqual(self.store.execute(args,'same'),self.store.execute(args,'same'))
        self.assertEqual(len(self.store.execute({'operation':'list','category':'shopping'},'read')['entries']),1)
    def test_complete_and_delete_only_exact_record(self):
        a=self.store.execute({'operation':'add','category':'shopping','title':'Молоко'},'a')
        b=self.store.execute({'operation':'add','category':'note','title':'Молоко'},'b')
        self.store.execute({'operation':'complete','category':'shopping','id':a['id']},'done')
        self.assertEqual(self.store.execute({'operation':'list','category':'shopping'},'read')['entries'],[])
        self.assertEqual(len(self.store.execute({'operation':'list','category':'shopping','include_completed':True},'read')['entries']),1)
        self.assertEqual(self.store.execute({'operation':'delete','category':'shopping','id':b['id']},'bad')['status'],'not_found')
        self.assertEqual(len(self.store.execute({'operation':'list','category':'note'},'read')['entries']),1)
    def test_sql_text_stays_text_and_invalid_write_rolls_back(self):
        self.store.execute({'operation':'add','category':'note','body':"'); DROP TABLE entries; --"},'sql')
        with self.assertRaises(ValueError):self.store.execute({'operation':'add','category':'invalid','title':'x'},'bad')
        self.assertEqual(len(self.store.execute({'operation':'list','category':'note'},'read')['entries']),1)


class ScheduleTests(unittest.TestCase):
    device={'version':1,'timezone':'Europe/Budapest','schedules':[]}
    def test_old_client_does_not_claim_timer_created(self):
        result,action=o.schedule_action({'operation':'create','seconds':60,'label':'Чай'},{'version':0},'ru')
        self.assertEqual(result['status'],'needs_app_update');self.assertIsNone(action)
    def test_relative_timer_and_recurrence(self):
        result,action=o.schedule_action({'operation':'create','seconds':600,'label':'Чай','type':'timer'},self.device,'ru')
        remaining=action['due_ms']/1000-dt.datetime.now().timestamp()
        self.assertTrue(598<remaining<=600)
        self.assertEqual(action['repeat'],'once')
        with self.assertRaises(ValueError):o.schedule_action({'operation':'create','seconds':60,'label':'x','type':'timer','repeat':'daily'},self.device,'ru')
    def test_cancel_cannot_target_unknown_id(self):
        result,action=o.schedule_action({'operation':'cancel','id':'a'*32},self.device,'ru')
        self.assertEqual(result['status'],'not_found');self.assertIsNone(action)
    def test_invalid_or_past_time_and_input_types(self):
        for args in ({'seconds':-1},{'seconds':True},{'seconds':1.2},{'local_datetime':'2000-01-01T08:00:00'},{'local_datetime':'2026-11-03T08:00:00+00:00'}):
            with self.subTest(args=args),self.assertRaises(ValueError):o.schedule_action(dict(operation='create',label='x',**args),self.device,'ru')
    def test_device_snapshot_sanitizes_and_validates_timezone(self):
        device=o.device_context({'organizer':{'version':1,'timezone':'Europe/Budapest','schedules':[{'id':'bad'},{'id':'a'*32,'label':'Чай','secret':'no'}]}})
        self.assertEqual(len(device['schedules']),1);self.assertNotIn('secret',device['schedules'][0])
        with self.assertRaises(KeyError):o.device_context({'organizer':{'version':1,'timezone':'not/a/zone'}})


if __name__=='__main__':unittest.main()
