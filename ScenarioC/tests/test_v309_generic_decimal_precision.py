"""Generic decimal precision: validation gates and Spark runtime feedback.

No AWS calls, model substitutions, or assumptions about any one SSIS column.
"""
import json
import sys
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from unsupported_process_ai import (
    inspect_python, inspect_decimal_precision, GeneratedCodeRejected,
    _runtime_category, preflight_local, Workflow, RemediationBlocked,
)


def module(expr, field='NetAmount'):
    return '''from pyspark.sql import functions as F

def transform(spark, input_prefix, output_prefix):
    df = spark.read.option("header", "true").csv(input_prefix + "/Rows.csv")
    out = df.withColumn(%r, %s)
    out.write.mode("overwrite").option("header", "true").csv(output_prefix + "/Output.csv")
''' % (field, expr)


def test_explicit_decimal_multiplication_over_limit_rejected():
    code=module('F.col("Amount").cast("decimal(30,10)") * F.lit("0.1").cast("decimal(10,5)")')
    with pytest.raises(GeneratedCodeRejected, match='precision 41'):
        inspect_python(code)


def test_final_cast_does_not_hide_intermediate_precision():
    code=module('(F.col("X").cast("decimal(30,10)") * F.col("Y").cast("decimal(25,5)")).cast("decimal(18,2)")')
    with pytest.raises(GeneratedCodeRejected, match='precision 56'):
        inspect_python(code)


def test_explicit_valid_decimal_types_accepted():
    assert inspect_python(module('(F.col("Amount").cast("decimal(18,2)") * F.lit("0.1").cast("decimal(3,2)")).cast("decimal(18,2)")'))


@pytest.mark.parametrize('precision,scale',[(55,2),(39,0),(18,19),(0,0)])
def test_bad_decimal_type_rejected(precision,scale):
    with pytest.raises(GeneratedCodeRejected, match='invalid'):
        inspect_python(module(f'F.col("Amount").cast("decimal({precision},{scale})")'))


def test_unrelated_columns_are_not_modified_and_no_auto_rewrite():
    code=module('F.lit(100.0)', 'Revenue')
    assert inspect_decimal_precision(code) is True


@pytest.mark.parametrize('error',[ 
    '[DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION] Decimal precision 55 exceeds max precision 38',
    'Spark decimal overflow in multiplication',
])
def test_runtime_decimal_error_is_not_environment(error):
    assert _runtime_category(error)=='DECIMAL_PRECISION'


def test_runtime_decimal_failure_retries_and_uses_previous_code(tmp_path):
    source=ROOT/'AI_Demo_Files'
    workflow=Workflow(tmp_path)
    workflow.analyze((source/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
        (source/'original-conversion-output (4).zip').read_bytes(),
        (source/'transform.ps1').read_bytes(),
        {'Employees.csv':(source/'Employees.csv').read_bytes()}, {})
    bad=module('F.col("Amount").cast("decimal(28,5)") * F.col("Rate").cast("decimal(15,3)")')
    good=module('(F.col("Amount").cast("decimal(18,2)") * F.col("Rate").cast("decimal(3,2)")).cast("decimal(18,2)")')
    prompts=[]
    def transport(prompt):
        prompts.append(prompt)
        return json.dumps({'code':bad if len(prompts)==1 else good,'explanation':'test'})
    # Static validation prevents the over-precision candidate before local execution.
    answer=workflow.propose(transport=transport,approve_cost=True,approve_transmission=True)
    assert answer['status']=='AI_PATCH_REVIEW_ONLY'
    assert len(prompts)==2
    assert 'precision 44' in prompts[1]
    assert 'before multiplication' in prompts[1]
    assert answer['validationAttempts'][0]['phase']=='AST_REJECTED'
    assert answer['validationAttempts'][1]['phase']=='RUNTIME_UNVERIFIED'
    assert not (tmp_path/'candidate.py').exists()


def test_runtime_decimal_error_feedback_and_retry(tmp_path):
    source=ROOT/'AI_Demo_Files'
    workflow=Workflow(tmp_path)
    workflow.analyze((source/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
        (source/'original-conversion-output (4).zip').read_bytes(),
        (source/'transform.ps1').read_bytes(), {}, {})
    code=module('F.col("Amount")')
    prompts=[]
    def runner(value):
        return ({'status':'FAILED','category':'DECIMAL_PRECISION',
                 'reason':'Decimal precision 55 exceeds max precision 38','verified':False}
                if len(prompts)==1 else {'status':'OUTPUT_GENERATED','category':'PASS','verified':True})
    result=workflow.propose(transport=lambda p: prompts.append(p) or json.dumps({'code':code,'explanation':'test'}),
                            runtime_test=runner,approve_cost=True,approve_transmission=True)
    assert len(prompts)==2
    assert 'DECIMAL_PRECISION' in prompts[1]
    assert result['validationAttempts'][0]['phase']=='RUNTIME_REJECTED'
    assert result['validationAttempts'][1]['phase']=='RUNTIME_PASSED'


def test_failed_approved_candidate_can_be_repaired_without_implicit_reapproval(tmp_path, monkeypatch):
    """Regression: previous approval/hash remains until a new review is accepted."""
    import unsupported_process_ai as ai
    source=ROOT/'AI_Demo_Files'
    workflow=Workflow(tmp_path)
    workflow.analyze((source/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
        (source/'original-conversion-output (4).zip').read_bytes(),
        (source/'transform.ps1').read_bytes(), {}, {})
    bad=module('F.col("Amount")',field='Amount')
    good=module('F.col("Amount").cast("decimal(18,2)")',field='Amount')
    first=workflow.propose(transport=lambda _:json.dumps({'code':bad,'explanation':'first'}),
             approve_cost=True,approve_transmission=True)
    workflow.approve(first['codeSha256'],True)
    old_bytes=(tmp_path/'candidate.py').read_bytes()
    from unsupported_process_ai import sha, read_json
    assert sha(old_bytes)==first['codeSha256']
    class Proc:
        returncode=1
        stdout=''
        stderr=''
    def fail_run(command, **kwargs):
        Path(command[3]).write_text(json.dumps({'status':'FAILED',
           'error':'[DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION] Decimal precision 55 exceeds max precision 38',
           'exceptionType':'AnalysisException', 'rootCause':'[DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION] Decimal precision 55 exceeds max precision 38'}))
        return Proc()
    monkeypatch.setattr(ai.subprocess,'run',fail_run)
    failed=workflow.validate()
    assert failed['status']=='FAILED'
    assert read_json(tmp_path/'manifest.json')['status']=='RUNTIME_VALIDATION_FAILED'
    report=read_json(tmp_path/'local-validation-failure.json')
    assert report['category']=='DECIMAL_PRECISION' and report['codeSha256']==sha(old_bytes)
    prompts=[]
    second=workflow.propose(transport=lambda p:prompts.append(p) or json.dumps({'code':good,'explanation':'corrected'}),
              approve_cost=True,approve_transmission=True)
    assert second['status']=='AI_PATCH_REVIEW_ONLY'
    assert len(prompts)==1
    assert 'DECIMAL_PRECISION' in prompts[0]
    assert 'REJECTED_CANDIDATE_PYTHON' in prompts[0]
    assert sha((tmp_path/'candidate.py').read_bytes())==first['codeSha256']
    assert read_json(tmp_path/'manifest.json')['status']=='RUNTIME_VALIDATION_FAILED'
    with pytest.raises(RemediationBlocked):
        workflow.approve(first['codeSha256'],True)
    accepted=workflow.approve(second['codeSha256'],True)
    assert accepted['deployAllowed'] is False
    assert read_json(tmp_path/'manifest.json')['status']=='APPROVED_PENDING_RUNTIME_PARITY'
    assert (tmp_path/'review-history'/(first['codeSha256']+'.py')).read_bytes()==old_bytes
    assert (tmp_path/'review-history'/(first['codeSha256']+'.json')).is_file()
    assert not (tmp_path/'local-validation-evidence.json').exists()
    assert not (tmp_path/'local-validation-failure.json').exists()


def test_no_repair_on_environment_failure_or_wrong_hash(tmp_path):
    source=ROOT/'AI_Demo_Files'
    workflow=Workflow(tmp_path)
    workflow.analyze((source/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
        (source/'original-conversion-output (4).zip').read_bytes(),
        (source/'transform.ps1').read_bytes(), {}, {})
    code=module('F.col("Amount")')
    first=workflow.propose(transport=lambda _:json.dumps({'code':code,'explanation':'test'}),
             approve_cost=True,approve_transmission=True)
    workflow.approve(first['codeSha256'],True)
    manifest=json.loads((tmp_path/'manifest.json').read_text())
    manifest['status']='RUNTIME_VALIDATION_FAILED'
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    (tmp_path/'local-validation-failure.json').write_text(json.dumps({'codeSha256':first['codeSha256'],
        'category':'ENVIRONMENT','reason':'Java failed to start'}))
    with pytest.raises(RemediationBlocked,match='Only verified generated-code failures'):
        workflow.propose(transport=lambda _:None,approve_cost=True,approve_transmission=True)
    (tmp_path/'local-validation-failure.json').write_text(json.dumps({'codeSha256':'a'*64,
        'category':'DECIMAL_PRECISION','reason':'precision 55'}))
    with pytest.raises(RemediationBlocked,match='different approved code hash'):
        workflow.propose(transport=lambda _:None,approve_cost=True,approve_transmission=True)


def test_failed_approved_candidate_can_be_revalidated_without_new_model_call(tmp_path, monkeypatch):
    import unsupported_process_ai as ai
    source=ROOT/'AI_Demo_Files'
    workflow=Workflow(tmp_path)
    workflow.analyze((source/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
        (source/'original-conversion-output (4).zip').read_bytes(),
        (source/'transform.ps1').read_bytes(), {}, {})
    code=module('F.col("Amount")')
    proposal=workflow.propose(transport=lambda _:json.dumps({'code':code,'explanation':'test'}),
        approve_cost=True,approve_transmission=True)
    workflow.approve(proposal['codeSha256'],True)
    calls=[]
    class Proc:
        returncode=1
        stdout=''
        stderr=''
    def fake_run(command, **kwargs):
        calls.append(1)
        result = ({'status':'FAILED', 'exceptionType':'AnalysisException',
            'error':'[DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION] Decimal precision 55 exceeds max precision 38'}
            if len(calls)==1 else {'status':'OUTPUT_GENERATED','outputs':[{'name':'Output.csv','actualRows':1}]})
        Path(command[3]).write_text(json.dumps(result))
        x=Proc();x.returncode=1 if len(calls)==1 else 0
        return x
    monkeypatch.setattr(ai.subprocess,'run',fake_run)
    failure=workflow.validate()
    assert failure['nextAction']=='REGENERATE_AI_FOR_REVIEW'
    assert failure['failureCategory']=='DECIMAL_PRECISION'
    success=workflow.validate()
    assert success['status']=='OUTPUT_GENERATED'
    assert json.loads((tmp_path/'manifest.json').read_text())['status']=='LOCAL_OUTPUT_GENERATED'
    assert not (tmp_path/'local-validation-failure.json').exists()
