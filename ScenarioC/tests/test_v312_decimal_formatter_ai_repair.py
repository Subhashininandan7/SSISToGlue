"""Scenario C regression: no manual editing of model-generated candidate."""
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from unsupported_process_ai import (Workflow, normalize_source_fixed_point,
    inspect_python, _runtime_category, RemediationBlocked, read_json)
FIX=ROOT/'AI_Demo_Files'
SOURCE=(FIX/'transform.ps1').read_text(encoding='utf-8')
BAD = """from pyspark.sql.functions import col, format_string
from decimal import Decimal

def transform(spark,input_prefix,output_prefix):
    df=spark.read.csv(input_prefix+'/Employees.csv',header=True,inferSchema=True)
    df=df.filter(col('Status')=='Active')
    df=df.withColumn('Salary',col('Salary').cast('decimal(10,2)'))
    df=df.withColumn('Bonus',(col('Salary')*Decimal('0.10')).cast('decimal(10,2)'))
    df=df.withColumn('Bonus',format_string('%.2f',col('Bonus')))
    df.write.option('header','true').csv(output_prefix+'/ActiveEmployees.csv')
"""

def workflow(path):
    w=Workflow(path)
    w.analyze((FIX/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
              (FIX/'original-conversion-output (4).zip').read_bytes(),
              (FIX/'transform.ps1').read_bytes(),
              {'Employees.csv':(FIX/'Employees.csv').read_bytes()},
              {'ActiveEmployees.csv':(FIX/'Expected_ActiveEmployees.csv').read_bytes()})
    return w

def test_exact_reported_java_error_is_repairable_code_failure():
    assert _runtime_category('java.util.IllegalFormatConversionException: f != org.apache.spark.sql.types.Decimal')=='CODE_RUNTIME'
    assert _runtime_category('SparkFileUtils.createTempDir winutils JAVA_HOME')=='ENVIRONMENT'

def test_source_based_decimal_formatter_is_normalized_without_float():
    fixed,changes=normalize_source_fixed_point(BAD,SOURCE)
    assert len(changes)==1 and changes[0]['column']=='Bonus'
    assert "cast('decimal(38,2)').cast('string')" in fixed
    assert 'format_string(' not in fixed and 'double' not in fixed
    assert inspect_python(fixed)

def test_model_proposal_is_normalized_and_remains_review_only(tmp_path):
    w=workflow(tmp_path)
    r=w.propose(transport=lambda prompt:json.dumps({'code':BAD,'explanation':'model output'}),
                approve_cost=True,approve_transmission=True)
    assert r['status']=='AI_PATCH_REVIEW_ONLY'
    proposal=read_json(tmp_path/'proposal.json')
    assert 'format_string(' not in proposal['code']
    assert "cast('decimal(38,2)').cast('string')" in proposal['code']
    assert not (tmp_path/'candidate.py').exists()
    assert read_json(tmp_path/'manifest.json')['status']=='REVIEW_REQUIRED'

def test_approval_hash_required_and_deploy_not_silently_allowed(tmp_path):
    w=workflow(tmp_path)
    r=w.propose(transport=lambda prompt:json.dumps({'code':BAD,'explanation':'model output'}),
                approve_cost=True,approve_transmission=True)
    with pytest.raises(RemediationBlocked):
        w.approve('bad hash',approved=True)
    assert not (tmp_path/'candidate.py').exists()

def test_repair_loop_retries_at_most_twice_in_test_transport(tmp_path):
    w=workflow(tmp_path)
    calls=[]
    def transport(prompt):
        calls.append(prompt)
        return json.dumps({'code':BAD,'explanation':'model output'})
    def runtime(code):
        return {'status':'FAILED','category':'CODE_RUNTIME','reason':'java.util.IllegalFormatConversionException: f != org.apache.spark.sql.types.Decimal','verified':False}
    with pytest.raises(RemediationBlocked,match='after 3 attempts'):
        w.propose(transport=transport,runtime_test=runtime,
                  approve_cost=True,approve_transmission=True)
    assert len(calls)==3
    assert 'IllegalFormatConversionException' in calls[1]
    assert not (tmp_path/'candidate.py').exists()
