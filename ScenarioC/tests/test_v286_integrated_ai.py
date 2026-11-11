import base64, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import bulk, cli
from unsupported_process_ai import sha, Workflow

FIX=ROOT/'AI_Demo_Files'
SRC='''from pyspark.sql import functions as F

def transform(spark,input_prefix,output_prefix):
    df=spark.read.option("header", "true").csv(input_prefix + "/Employees.csv")
    df=df.filter(F.col("Status") == "Active")
    df.write.mode("overwrite").option("header", "true").csv(output_prefix + "/ActiveEmployees.csv")
'''
class Integration(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.old=cli.HOME;cli.HOME=Path(self.tmp.name);self.addCleanup(setattr,cli,'HOME',self.old)
  self.p=bulk.create(cli,{})['id']
  self.name='C_Unsupported_Execute_Process_AI_Demo.dtsx'
  raw=(FIX/self.name).read_bytes()
  bulk.add(cli,{'portfolioId':self.p,'fileName':self.name,'contentBase64':base64.b64encode(raw).decode()})
  self.e=bulk.status(cli,{'portfolioId':self.p})['packages'][0]
  sp=cli.session_path(self.e['sessionId']);(sp/'sct').mkdir(exist_ok=True)
  (sp/'sct'/'original-conversion-output.zip').write_bytes((FIX/'original-conversion-output (4).zip').read_bytes())
  (sp/'sct'/'original').mkdir(exist_ok=True)
  import zipfile,io
  with zipfile.ZipFile(FIX/'original-conversion-output (4).zip') as z:
   code=next(z.read(n) for n in z.namelist() if n.endswith('.py') and '25029' in z.read(n).decode('utf-8',errors='replace'))
  (sp/'sct'/'original'/'sct_000.py').write_bytes(code)
  cli.store(sp/'sct'/'manifest.json',[{'file':'sct_000.py','originalPath':'test.py','sha256':sha(code),'provenance':'REAL_SCT_BATCH_CLI'}])
  for role,filename in [('script','transform.ps1'),('input','Employees.csv'),('reference','Expected_ActiveEmployees.csv')]:
   raw=(FIX/filename).read_bytes()
   bulk.upload_support(cli,{'portfolioId':self.p,'packageName':self.name,'role':role,'fileName':filename,'contentBase64':base64.b64encode(raw).decode()})
 def action(self,op,**kwargs):return bulk.step(cli,{'portfolioId':self.p,'packageName':self.name,'operation':op,**kwargs})
 def test_analyze_fallback_and_one_button_ai_proposal(self):
  r=self.action('analyze')
  self.assertEqual(r['result']['status'],'UNSUPPORTED_TASK_AI_ELIGIBLE')
  self.assertEqual(r['state'],'REPAIR_BLOCKED')
  state=bulk.status(cli,{'portfolioId':self.p})['packages'][0]
  self.assertTrue(state['unsupportedProcessAI'])
  self.assertEqual(state['processAIKind'],'EXECUTE_PROCESS_25029')
  with patch.object(Workflow,'propose',autospec=True) as propose:
   propose.return_value={'codeSha256':sha(SRC.encode()),'diff':'--- a\n+++ b','model':'test','usage':{'testTransport':True}}
   result=self.action('ai-propose',approveModelCost=True,approveCodeTransmission=True)
  self.assertEqual(result['result']['status'],'AI_PATCH_REVIEW_ONLY')
  self.assertEqual(result['result']['baseHash'],sha(SRC.encode()))
  self.assertEqual(bulk.status(cli,{'portfolioId':self.p})['packages'][0]['pendingBaseHash'],sha(SRC.encode()))
  self.assertEqual(propose.call_count,1)
 def test_no_ai_without_evidence_or_ssis_metadata(self):
  p=cli.session_path(self.e['sessionId'])/'process-support'/'script'/'transform.ps1'
  p.unlink()
  with self.assertRaisesRegex(ValueError,'sidecar'):
   self.action('analyze')
 def test_ai_must_not_deploy_from_review_lane(self):
  self.action('analyze')
  with self.assertRaisesRegex(ValueError,'Approved AI candidate must pass independent local Spark validation'):
   self.action('deploy',approvePortfolioDeployment=True)
 def test_matched_script_and_valid_csv_only(self):
  with self.assertRaisesRegex(ValueError,'not named'):
   bulk.upload_support(cli,{'portfolioId':self.p,'packageName':self.name,'role':'script','fileName':'random.ps1','contentBase64':base64.b64encode(b'write-host 1').decode()})
  with self.assertRaises(Exception):
   bulk.upload_support(cli,{'portfolioId':self.p,'packageName':self.name,'role':'reference','fileName':'bad.csv','contentBase64':base64.b64encode(b'').decode()})
if __name__=='__main__':unittest.main()
