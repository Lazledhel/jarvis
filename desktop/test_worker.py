import tempfile,unittest,sqlite3
from pathlib import Path
from worker import Worker
class Tests(unittest.TestCase):
 def test_redelivery_never_starts_second_turn(self):
  with tempfile.TemporaryDirectory() as tmp:
   worker=Worker.__new__(Worker);worker.root=Path(tmp)/'tasks';worker.root.mkdir();worker.state=Path(tmp)/'state.sqlite3'
   with worker.db() as db:db.execute('CREATE TABLE jobs(id TEXT PRIMARY KEY,state TEXT,thread_id TEXT,turn_id TEXT)')
   class FakeRpc:
    starts=0
    def start(self,*args):self.starts+=1;return 'thread','turn'
    def wait(self,*args):return 'completed'
   worker.rpc=FakeRpc();calls=[];worker.api=lambda path,body:calls.append((path,body));job={'id':'a'*32,'goal':'test','title':'test','steps':['one'],'lease':'lease-one'};worker.dispatch(job);worker.dispatch(dict(job,lease='lease-two'));self.assertEqual(worker.rpc.starts,1);self.assertEqual(calls[-1][1]['state'],'completed')
if __name__=='__main__':unittest.main()
