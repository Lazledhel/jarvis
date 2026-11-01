import threading
import unittest
from gpu_idle import IdleResource

class IdleTests(unittest.TestCase):
 def test_deadline_resets_after_every_call(self):
  now=[0];released=[]
  idle=IdleResource(lambda:released.append(True),seconds=60,clock=lambda:now[0])
  call=idle.wrap(lambda:42)
  self.assertFalse(idle.sweep())
  self.assertEqual(call(),42)
  now[0]=59;self.assertFalse(idle.sweep())
  call();now[0]=118;self.assertFalse(idle.sweep())
  now[0]=119;self.assertTrue(idle.sweep())
  self.assertEqual(released,[True]);self.assertFalse(idle.sweep())
 def test_cannot_release_during_inference(self):
  started=threading.Event();finish=threading.Event();released=[]
  idle=IdleResource(lambda:released.append(True),seconds=1,clock=lambda:100)
  idle.last=0
  def inference():started.set();finish.wait(2)
  t=threading.Thread(target=idle.wrap(inference));t.start()
  self.assertTrue(started.wait(1))
  self.assertFalse(idle.sweep());self.assertEqual(released,[])
  finish.set();t.join()
 def test_failure_still_schedules_cleanup(self):
  released=[];now=[0]
  idle=IdleResource(lambda:released.append(True),seconds=1,clock=lambda:now[0])
  @idle.wrap
  def failed():raise RuntimeError()
  with self.assertRaises(RuntimeError):failed()
  now[0]=2;self.assertTrue(idle.sweep());self.assertEqual(released,[True])
if __name__=="__main__":unittest.main()
