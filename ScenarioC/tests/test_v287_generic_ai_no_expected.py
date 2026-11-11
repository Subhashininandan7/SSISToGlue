import base64, json, sys, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'engine'))
import bulk,cli
from unsupported_process_ai import Workflow,sha
FIX=ROOT/'AI_Demo_Files'
CODE='''from pyspark.sql import functions as F

def transform(spark,input_prefix,output_prefix):
    src=spark.read.option("header","true").csv(input_prefix + "/Employees.csv")
    src.filter(F.col("Status")=="Active").write.mode("overwrite").option("header","true").csv(output_prefix+"/ActiveEmployees.csv")
'''
class GenericNoReference(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  prev=cli.HOME;cli.HOME=Path(tmp.name);self.addCleanup(setattr,cli,'HOME',prev)
  self.pid=bulk.create(cli,{})['id'];self.name='C_Unsupported_Execute_Process_AI_Demo.dtsx'
  def enc(path):return base64.b64encode(path.read_bytes()).decode()
  bulk.add(cli,{'portfolioId':self.pid,'fileName':self.name,'contentBase64':enc(FIX/self.name)})
  e=bulk.status(cli,{'portfolioId':self.pid})['packages'][0];sp=cli.session_path(e['sessionId']);(sp/'sct').mkdir(exist_ok=True)
  arc=FIX/'original-conversion-output (4).zip'
  (sp/'sct'/'original-conversion-output.zip').write_bytes(arc.read_bytes())
  (sp/'sct'/'original').mkdir(exist_ok=True)
  with zipfile.ZipFile(arc) as z:
   code=next(z.read(n) for n in z.namelist() if n.endswith('.py') and '25029' in z.read(n).decode('utf-8',errors='replace'))
  (sp/'sct'/'original'/'sct_000.py').write_bytes(code)
  cli.store(sp/'sct'/'manifest.json',[{'file':'sct_000.py','originalPath':'test.py','sha256':sha(code),'provenance':'REAL_SCT_BATCH_CLI'}])
  for role,name in [('script','transform.ps1'),('input','Employees.csv')]:
   bulk.upload_support(cli,{'portfolioId':self.pid,'packageName':self.name,'role':role,'fileName':name,'contentBase64':enc(FIX/name)})
 def action(self,op,**kw):return bulk.step(cli,{'portfolioId':self.pid,'packageName':self.name,'operation':op,**kw})
 def test_existing_analyze_and_ai_without_preexisting_output(self):
  analysis=self.action('analyze');self.assertEqual(analysis['result']['status'],'UNSUPPORTED_TASK_AI_ELIGIBLE')
  self.assertFalse(analysis['result']['deployAllowed'])
  with patch.object(Workflow,'propose',autospec=True) as model:
   model.return_value={'codeSha256':sha(CODE.encode()),'diff':'--- SCT/stub\n+++ Bedrock/proposal','model':'test','usage':{'testTransport':True}}
   proposal=self.action('ai-propose',approveModelCost=True,approveCodeTransmission=True)
  self.assertEqual(proposal['result']['status'],'AI_PATCH_REVIEW_ONLY')
  self.assertEqual(model.call_count,1)
  manifest=Path(cli.session_path(bulk.status(cli,{'portfolioId':self.pid})['packages'][0]['sessionId']))/'process-ai'/'manifest.json'
  obj=json.loads(manifest.read_text());self.assertEqual(obj['outputs'],{})
  self.assertIn('Employees.csv',obj['inputs'])
 def test_no_script_never_invokes_model(self):
  e=bulk.status(cli,{'portfolioId':self.pid})['packages'][0]
  (cli.session_path(e['sessionId'])/'process-support'/'script'/'transform.ps1').unlink()
  with self.assertRaisesRegex(ValueError,'sidecar'):
   self.action('analyze')
if __name__=='__main__':unittest.main()
