import base64
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from unsupported_process_ai import Workflow,RemediationBlocked,inspect_ssis,inspect_sct,inspect_python,sha

FIX=ROOT/'AI_Demo_Files'
SCT=FIX/'original-conversion-output (4).zip'
SOURCE='''from pyspark.sql import functions as F
from decimal import Decimal

def transform(spark,input_prefix,output_prefix):
    df=spark.read.option("header", "true").csv(input_prefix + "/Employees.csv")
    df=df.filter(F.col("Status") == "Active").withColumn("Bonus",(F.col("Salary").cast("decimal(18,2)")*F.lit(0.10)).cast("decimal(18,2)"))
    df.select("EmployeeID","EmployeeName","Department","Salary","Status","Bonus").write.mode("overwrite").option("header", "true").csv(output_prefix + "/ActiveEmployees.csv")
'''
class Cases(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.flow=Workflow(self.tmp.name)
        self.package=(FIX/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes()
        self.script=(FIX/'transform.ps1').read_bytes()
        self.sct=SCT.read_bytes()
        self.inputs={'Employees.csv':(FIX/'Employees.csv').read_bytes()}
        self.refs={'ActiveEmployees.csv':(FIX/'Expected_ActiveEmployees.csv').read_bytes()}
    def analyze(self):return self.flow.analyze(self.package,self.sct,self.script,self.inputs,self.refs)
    def test_real_source_and_sct_warning(self):
        self.assertEqual(inspect_ssis(self.package)['scriptName'],'transform.ps1')
        self.assertIn('25029',inspect_sct(self.sct)['warning'])
    def test_analyze_and_model_proposal_review(self):
        a=self.analyze();self.assertEqual(a['status'],'REVIEW_REQUIRED')
        seen=[]
        result=self.flow.propose(approve_cost=True,approve_transmission=True,
                                  transport=lambda p:(seen.append(p) or json.dumps({'code':SOURCE,'explanation':'mapped script'})))
        self.assertEqual(result['status'],'AI_PATCH_REVIEW_ONLY')
        self.assertIn('Microsoft.ExecuteProcess',seen[0])
        self.assertIn('Employees.csv',seen[0]);self.assertIn('ActiveEmployees.csv',seen[0])
        self.assertIn('25029',seen[0]);self.assertIn('Where-Object',seen[0])
        self.assertNotIn('Ravi',seen[0]) # raw records NOT sent
        self.assertTrue((Path(self.tmp.name)/'diff.txt').is_file())
        with self.assertRaises(RemediationBlocked):self.flow.approve('bad',True)
        approved=self.flow.approve(sha(SOURCE.encode()),True)
        self.assertEqual(approved['status'],'APPROVED_PENDING_RUNTIME_PARITY')
        self.assertFalse(approved['deployAllowed'])
    def test_no_model_call_without_approvals(self):
        self.analyze()
        with self.assertRaisesRegex(RemediationBlocked,'approvals'):
            self.flow.propose(transport=lambda _:self.fail('model called'))
    def test_no_fake_sct_warning(self):
        with zipfile.ZipFile(io.BytesIO(), 'w') as z:pass
    def test_missing_real_warning_fails(self):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('create-body-script/a.py','def a(): pass')
        with self.assertRaisesRegex(RemediationBlocked,'25029'):
            self.flow.analyze(self.package,b.getvalue(),self.script,self.inputs,self.refs)
    def test_bad_execute_process_metadata_fails(self):
        wrong=self.package.replace(b'Microsoft.ExecuteProcess',b'Microsoft.FakeTask')
        with self.assertRaises(RemediationBlocked):inspect_ssis(wrong)
    def test_script_secrets_blocked(self):
        with self.assertRaisesRegex(RemediationBlocked,'secret'):
            self.flow.analyze(self.package,self.sct,self.script+b'\n$password="not-for-bedrock"',self.inputs,self.refs)
    def test_unsafe_python_rejected(self):
        for code in ['import subprocess\n'+SOURCE, 'import os\n'+SOURCE,
                     SOURCE+'\nexec("print(1)")\n',SOURCE.replace('def transform','def tamper')]:
            with self.subTest(code=code[:30]):
                with self.assertRaises(RemediationBlocked):inspect_python(code)
    def test_wrong_response_schema_rejected(self):
        self.analyze()
        with self.assertRaisesRegex(RemediationBlocked,'schema'):
            self.flow.propose(approve_cost=True,approve_transmission=True,transport=lambda _:json.dumps({'code':SOURCE,'explanation':'x','unexpected':1}))
    def test_approval_rejects_modified_evidence(self):
        self.analyze()
        self.flow.propose(approve_cost=True,approve_transmission=True,transport=lambda _:json.dumps({'code':SOURCE,'explanation':'x'}))
        (Path(self.tmp.name)/'manifest.json').write_text('{}')
        with self.assertRaises(RemediationBlocked):self.flow.approve(sha(SOURCE.encode()),True)
    def test_missing_pyspark_is_not_success(self):
        self.analyze();self.flow.propose(approve_cost=True,approve_transmission=True,transport=lambda _:json.dumps({'code':SOURCE,'explanation':'x'}));self.flow.approve(sha(SOURCE.encode()),True)
        completed=type('Result',(),{'returncode':1,'stdout':'{"status":"FAILED","error":"pyspark unavailable"}','stderr':''})()
        def mocked_run(cmd,**kwargs):
            Path(cmd[3]).write_text('{"status":"FAILED","error":"pyspark unavailable"}',encoding='utf-8')
            return completed
        with patch('unsupported_process_ai.subprocess.run',side_effect=mocked_run):
            r=self.flow.validate()
        self.assertEqual(r['status'],'FAILED');self.assertFalse(r['deployAllowed'])
    def test_package_must_have_single_task(self):
        xml=self.package.replace(b'Microsoft.ExecuteProcess',b'Microsoft.Noop')
        with self.assertRaises(RemediationBlocked):inspect_ssis(xml)

if __name__=='__main__':unittest.main()
