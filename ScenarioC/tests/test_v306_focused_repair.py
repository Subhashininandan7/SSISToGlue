"""Regression for Nov 9 2026: fixed-point AST rejection, unparsable reply, then repair.

Model transport is synthetic. A passing test does NOT assert AWS Bedrock success.
"""
import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from unsupported_process_ai import Workflow, RemediationBlocked

FIX=ROOT/'AI_Demo_Files'

def setup(tmp_path):
    workflow=Workflow(tmp_path)
    workflow.analyze(
        (FIX/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
        (FIX/'original-conversion-output (4).zip').read_bytes(),
        (FIX/'transform.ps1').read_bytes(), {}, {})
    return workflow

BAD='''from pyspark.sql import functions as F
def transform(spark, input_prefix, output_prefix):
    df=spark.read.csv(input_prefix + '/Employees.csv', header=True)
    df=df.withColumn('Bonus', F.format_number(F.col('Salary').cast('decimal(18,2)') * F.lit('0.10'), 3))
    df.write.mode('overwrite').option('header', True).csv(output_prefix + '/ActiveEmployees.csv')
'''
GOOD=BAD.replace("F.format_number(F.col('Salary').cast('decimal(18,2)') * F.lit('0.10'), 3)","(F.col('Salary').cast('decimal(18,2)') * F.lit('0.10').cast('decimal(3,2)')).cast('decimal(18,2)')")


def test_three_attempt_regression_source_candidate_survives_bad_second_reply(tmp_path):
    wf=setup(tmp_path)
    prompts=[]
    def fake_model(prompt):
        prompts.append(prompt)
        if len(prompts)==1:
            return json.dumps({'code':BAD,'explanation':'initial'})
        if len(prompts)==2:
            return 'Here is the correction, but I cannot provide code in the requested structure.'
        return json.dumps({'code':GOOD,'explanation':'fixed-point decimal, no grouping'})
    result=wf.propose(transport=fake_model,runtime_test=lambda code: {'status':'NOT_RUN','category':'ENVIRONMENT','verified':False},approve_cost=True,approve_transmission=True)
    assert len(prompts)==3
    assert 'REJECTED_CANDIDATE_PYTHON' in prompts[1]
    assert "format_number" in prompts[1]
    assert 'Original PowerShell' in prompts[1]
    assert 'REJECTED_CANDIDATE_PYTHON' in prompts[2]
    assert 'previous reply was NOT a usable' in prompts[2]
    assert 'format_number' not in json.loads((tmp_path/'proposal.json').read_text())['code']
    assert result['validationAttempts'][0]['phase']=='AST_REJECTED'
    assert result['validationAttempts'][1]['phase']=='AST_REJECTED'
    assert result['validationAttempts'][2]['status']=='VALIDATED'
    assert not (tmp_path/'candidate.py').exists()


def test_unfixed_result_is_not_approved_even_after_all_retries(tmp_path):
    wf=setup(tmp_path)
    prompts=[]
    def always_bad(prompt):
        prompts.append(prompt)
        return json.dumps({'code':BAD,'explanation':'unchanged'})
    with pytest.raises(RemediationBlocked,match='rejected after 3 attempts'):
        wf.propose(transport=always_bad,runtime_test=lambda code: {'status':'NOT_RUN','category':'ENVIRONMENT','verified':False},approve_cost=True,approve_transmission=True)
    assert len(prompts)==3
    assert not (tmp_path/'proposal.json').exists()
    assert not (tmp_path/'candidate.py').exists()
    diagnostics=json.loads((tmp_path/'ai-diagnostics.json').read_text())
    assert diagnostics['status']=='REJECTED'
