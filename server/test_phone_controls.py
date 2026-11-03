import unittest
from phone_commands import validate,description


class Tests(unittest.TestCase):
 def test_switches_require_explicit_boolean(self):
  for kind in ('vpn','flashlight','dnd','wifi','bluetooth'):
   self.assertFalse(validate({'kind':kind,'enabled':False})['enabled'])
   for value in (None,1,'true'):
    with self.subTest(kind=kind,value=value),self.assertRaises(ValueError):validate({'kind':kind,'enabled':value})
 def test_percent_and_directions_are_validated(self):
  self.assertEqual(validate({'kind':'volume','percent':0})['percent'],0)
  self.assertEqual(validate({'kind':'brightness','direction':'down'})['direction'],'down')
  for value in (-1,101,True,20.5):
   with self.subTest(value=value),self.assertRaises(ValueError):validate({'kind':'brightness','percent':value})
  with self.assertRaises(ValueError):validate({'kind':'volume','percent':50,'stream':'arbitrary'})
 def test_web_urls_block_nonweb_and_credentials(self):
  self.assertEqual(validate({'kind':'website','target':'example.org'})['target'],'https://example.org')
  for value in ('file:///etc/passwd','intent://x','https://name:password@example.org','https://example.org\nBad: x','https://example.org:8765/'):
   with self.subTest(value=value),self.assertRaises(ValueError):validate({'kind':'website','target':value})
 def test_media_and_camera_do_not_accept_unknown_actions(self):
  self.assertEqual(validate({'kind':'camera','facing':'front'})['facing'],'front')
  with self.assertRaises(ValueError):validate({'kind':'media','command':'send_message'})
  with self.assertRaises(ValueError):validate({'kind':'camera','facing':'secret'})
 def test_descriptions_do_not_claim_capture_or_connectivity_change(self):
  self.assertIn('Снимок нужно сделать',description(validate({'kind':'camera'})))
  self.assertIn('подтвердить',description(validate({'kind':'wifi','enabled':False})))

if __name__=='__main__':unittest.main()
