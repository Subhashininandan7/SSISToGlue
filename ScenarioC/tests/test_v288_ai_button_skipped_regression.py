"""Regression: unsupported SCT 25029 with no coordinator must not be skipped by AI button."""
import base64, json, sys, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import bulk, cli
from unsupported_process_ai import Workflow,sha
FIX=ROOT/'AI_Demo_Files'

def enc(data):return base64.b64encode(data).decode()

class AIBeforeNormalAnalysis(unittest.TestCase):
 def setUp(self):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
  old=cli.HOME;cli.HOME=Path(t.name);self.addCleanup(setattr,cli,'HOME',old)
  self.name='C_Unsupported_Execute_Process_AI_Demo.dtsx';self.pid=bulk.create(cli,{})['id']
  bulk.add(cli,{'portfolioId':self.pid,'fileName':self.name,'contentBase64':enc((FIX/self.name).read_bytes())})
  entry=bulk.status(cli,{'portfolioId':self.pid})['packages'][0]
  root=cli.session_path(entry['sessionId']);(root/'sct').mkdir(exist_ok=True)
  (root/'sct'/'original-conversion-output.zip').write_bytes((FIX/'original-conversion-output (4).zip').read_bytes())
  with zipfile.ZipFile(FIX/'original-conversion-output (4).zip') as z:
   b=next(z.read(n) for n in z.namelist() if n.endswith('.py') and b'25029' in z.read(n))
  (root/'sct'/'original').mkdir(exist_ok=True)
  (root/'sct'/'original'/'sct_000.py').write_bytes(b)
  cli.store(root/'sct'/'manifest.json',[{'file':'sct_000.py','originalPath':'generated.py','sha256':sha(b),'provenance':'REAL_SCT_BATCH_CLI'}])
  for role,name in [('script','transform.ps1'),('input','Employees.csv')]:
   bulk.upload_support(cli,{'portfolioId':self.pid,'packageName':self.name,'role':role,'fileName':name,'contentBase64':enc((FIX/name).read_bytes())})
 def invoke(self):return bulk.step(cli,{'portfolioId':self.pid,'packageName':self.name,'operation':'ai-propose','approveModelCost':True,'approveCodeTransmission':True})
 def test_original_button_routes_coordinator_free_sct_25029(self):
  with patch.object(Workflow,'propose',autospec=True) as model:
   model.return_value={'codeSha256':'a'*64,'diff':'--- SCT/stub\n+++ Bedrock/proposal','model':'test','usage':{}}
   result=self.invoke()
  self.assertEqual(result['result']['status'],'AI_PATCH_REVIEW_ONLY')
  self.assertEqual(model.call_count,1)
  state=bulk.status(cli,{'portfolioId':self.pid})['packages'][0]
  self.assertEqual(state['processAIKind'],'EXECUTE_PROCESS_25029')
  self.assertEqual(state['pendingBaseHash'],'a'*64)
  self.assertTrue(state['unsupportedProcessAI'])
 def test_missing_script_provides_explicit_error_before_model_call(self):
  e=bulk.status(cli,{'portfolioId':self.pid})['packages'][0]
  (cli.session_path(e['sessionId'])/'process-support'/'script'/'transform.ps1').unlink()
  with patch.object(Workflow,'propose',autospec=True) as model:
   with self.assertRaisesRegex(ValueError,'sidecar'):self.invoke()
   model.assert_not_called()
 def test_normal_package_without_25029_keeps_normal_analysis_gate(self):
  e=bulk.status(cli,{'portfolioId':self.pid})['packages'][0]
  path=cli.session_path(e['sessionId'])/'sct'/'original-conversion-output.zip'
  with zipfile.ZipFile(path,'w') as z:z.writestr('dummy.py','def run(): pass')
  with self.assertRaisesRegex(ValueError,'Analyze SCT code first'):self.invoke()

if __name__=='__main__':unittest.main()
