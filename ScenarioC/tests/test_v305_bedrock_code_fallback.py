"""Regression cases for Nova-style Python-only response in bounded Bedrock retry."""
import sys, json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from unsupported_process_ai import parse_bedrock_proposal, GeneratedCodeRejected, Workflow
CODE = """from pyspark.sql import functions as F

def transform(spark, input_prefix, output_prefix):
    df = spark.read.option('header','true').csv(input_prefix + '/Employees.csv')
    df.filter(F.col('Status') == 'Active').write.mode('overwrite').option('header','true').csv(output_prefix + '/ActiveEmployees.csv')
"""
@pytest.mark.parametrize('response', [CODE, 'Translation based on the source:\n```python\n'+CODE+'\n```\nVerify against SSIS reference.'])
def test_one_module_accepted(response):
    result=parse_bedrock_proposal(response)
    assert 'def transform' in result['code'] and 'explanation' in result

def test_multiple_fenced_modules_rejected():
    with pytest.raises(GeneratedCodeRejected):
        parse_bedrock_proposal('```python\n'+CODE+'\n```\n```python\n'+CODE+'\n```')

def test_single_fenced_module_without_transform_rejected():
    with pytest.raises(GeneratedCodeRejected):
        parse_bedrock_proposal('```python\nprint(1)\n```')

def test_python_fallback_still_ast_validated(tmp_path):
    fix=ROOT/'AI_Demo_Files'; wf=Workflow(tmp_path)
    wf.analyze((fix/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
               (fix/'original-conversion-output (4).zip').read_bytes(),
               (fix/'transform.ps1').read_bytes(),{}, {})
    # The model's text envelope is now acceptable, but existing source and AST
    # validation are still mandatory.
    proposed=wf.propose(transport=lambda _: '```python\n'+CODE+'\n```',approve_cost=True,approve_transmission=True)
    assert proposed['status']=='AI_PATCH_REVIEW_ONLY'
    assert json.loads((tmp_path/'ai-diagnostics.json').read_text())['attempts'][0]['modelResponseChars']>0
