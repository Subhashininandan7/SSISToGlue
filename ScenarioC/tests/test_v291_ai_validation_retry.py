import json
import tempfile
from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from unsupported_process_ai import Workflow,inspect_python,GeneratedCodeRejected,RemediationBlocked,sha
FIX=ROOT/'AI_Demo_Files'
VALID='''from pyspark.sql import functions as F\n\ndef transform(spark, input_prefix, output_prefix):\n    df = spark.read.option("header", "true").csv(input_prefix + "/Employees.csv")\n    df.filter(F.col("Status") == "Active").write.mode("overwrite").option("header", "true").csv(output_prefix + "/ActiveEmployees.csv")\n'''
BAD='''from pyspark.sql import SparkSession\nspark = SparkSession.builder.getOrCreate()\n\ndef transform(spark, input_prefix, output_prefix):\n    return None\n'''

def setup(tmp):
    wf=Workflow(tmp)
    wf.analyze((FIX/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
        (FIX/'original-conversion-output (4).zip').read_bytes(),
        (FIX/'transform.ps1').read_bytes(),{}, {})
    return wf

def result(code):return json.dumps({'code':code,'explanation':'Translation of approved PowerShell logic'})

def test_rejected_top_level_has_exact_line_and_ast_kind():
    with pytest.raises(GeneratedCodeRejected,match='line 2, Assign: No executable statements') as err:
        inspect_python(BAD)
    assert err.value.feedback()['line']==2
    assert err.value.feedback()['nodeType']=='Assign'

def test_one_retry_and_review_only_no_output_baseline(tmp_path):
    wf=setup(tmp_path);calls=[]
    def model(prompt):
        calls.append(prompt)
        return result(BAD if len(calls)==1 else VALID)
    proposal=wf.propose(transport=model,approve_cost=True,approve_transmission=True)
    assert len(calls)==2
    assert 'line 2, Assign' in calls[1]
    assert proposal['status']=='AI_PATCH_REVIEW_ONLY'
    assert proposal['validationAttempts'][0]['status']=='REJECTED'
    assert proposal['validationAttempts'][1]['status']=='VALIDATED'
    assert not (tmp_path/'candidate.py').exists()
    assert json.loads((tmp_path/'ai-diagnostics.json').read_text())['status']=='VALIDATED'
    approved=wf.approve(sha(VALID.encode()),True)
    assert approved['deployAllowed'] is False
    assert (tmp_path/'candidate.py').read_text()==VALID

def test_retries_at_most_once_diagnostic_not_model_code(tmp_path):
    wf=setup(tmp_path);calls=[]
    def model(prompt):calls.append(prompt);return result(BAD)
    with pytest.raises(RemediationBlocked,match='after 2 attempts: line 2, Assign'):
        wf.propose(transport=model,approve_cost=True,approve_transmission=True)
    assert len(calls)==2
    diagnostics=json.loads((tmp_path/'ai-diagnostics.json').read_text())
    assert diagnostics['status']=='REJECTED' and len(diagnostics['attempts'])==2
    assert 'spark = SparkSession' not in (tmp_path/'ai-diagnostics.json').read_text()
    assert not (tmp_path/'proposal.json').exists()

def test_no_retry_on_valid_first_proposal(tmp_path):
    wf=setup(tmp_path);calls=[]
    wf.propose(transport=lambda x: calls.append(x) or result(VALID),approve_cost=True,approve_transmission=True)
    assert len(calls)==1

def test_unsafe_model_import_cannot_be_approved(tmp_path):
    wf=setup(tmp_path)
    with pytest.raises(RemediationBlocked,match='after 2 attempts'):
        wf.propose(transport=lambda _:result('import os\n'+VALID),approve_cost=True,approve_transmission=True)
    assert not (tmp_path/'candidate.py').exists()

def test_changes_to_original_script_block_approval(tmp_path):
    wf=setup(tmp_path)
    wf.propose(transport=lambda _:result(VALID),approve_cost=True,approve_transmission=True)
    (tmp_path/'support.ps1').write_text('changed')
    with pytest.raises(RemediationBlocked,match='Original evidence changed'):
        wf.approve(sha(VALID.encode()),True)

def test_disallow_decorators_and_top_level_main(tmp_path):
    for code in (VALID+'\nif __name__ == "__main__":\n    transform(None,"a","b")\n', VALID.replace('def transform','@staticmethod\ndef transform')):
        with pytest.raises(RemediationBlocked):inspect_python(code)
