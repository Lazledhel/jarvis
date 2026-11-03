import tempfile,unittest,concurrent.futures
from pathlib import Path
from developer_budget import Ledger,ApprovalRequired,UsageUncertain,BLOCK


class Tests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.ledger=Ledger(Path(self.temp.name)/'budget.sqlite3')
 def tearDown(self):self.temp.cleanup()
 def test_no_call_before_explicit_project_grant(self):
  with self.assertRaises(ApprovalRequired):self.ledger.reserve('a',[{'role':'user','content':'x'}],100,'plan')
  self.ledger.approve('a',1,'explicit-user-approval')
  with self.assertRaises(ApprovalRequired):self.ledger.reserve('another-project',[],100,'plan')
 def test_actual_input_output_usage_and_one_block_at_a_time(self):
  self.ledger.approve('a',1,'explicit-user-approval')
  ident=self.ledger.reserve('a',[],100,'plan');self.ledger.settle(ident,{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150})
  self.assertEqual(self.ledger.status('a')['charged_tokens'],150)
  with self.assertRaises(ValueError):self.ledger.approve('a',3,'not-an-approval-for-block-two')
  with self.assertRaises(ValueError):self.ledger.approve('a',1,'duplicate-approval-reference')
 def test_uncertain_timeout_or_missing_usage_stops_project(self):
  self.ledger.approve('a',1,'explicit-user-approval');ident=self.ledger.reserve('a',[],100,'plan')
  with self.assertRaises(UsageUncertain):self.ledger.settle(ident,None)
  with self.assertRaises(UsageUncertain):self.ledger.reserve('a',[],100,'retry')
  self.assertGreater(self.ledger.status('a')['charged_tokens'],0)
 def test_concurrent_reservations_cannot_overbook(self):
  self.ledger.approve('a',1,'explicit-user-approval')
  def reserve(n):
   try:return self.ledger.reserve('a',[{'role':'user','content':'x'*10000}],100,'test')
   except ApprovalRequired:return None
  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:ids=list(pool.map(reserve,range(100)))
  state=self.ledger.status('a');self.assertLessEqual(state['reserved_tokens'],BLOCK);self.assertTrue(any(x is None for x in ids))
 def test_restart_preserves_grant_and_inflight_reservations(self):
  self.ledger.approve('a',1,'explicit-user-approval');self.ledger.reserve('a',[],100,'plan')
  self.assertGreater(Ledger(self.ledger.path).status('a')['reserved_tokens'],0)

if __name__=='__main__':unittest.main()
