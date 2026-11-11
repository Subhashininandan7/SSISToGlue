"""Source-independent, bounded runtime feedback and safety gates."""
import json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from unsupported_process_ai import Workflow,RemediationBlocked,sha,preflight_local,_runtime_category
FIX=ROOT/'AI_Demo_Files'
VALID='''from pyspark.sql import functions as F\n\ndef transform(spark, input_prefix, output_prefix):\n    df = spark.read.option("header", "true").csv(input_prefix + "/Employees.csv")\n    df.filter(F.col("Status") == "Active").write.mode("overwrite").option("header", "true").csv(output_prefix + "/ActiveEmployees.csv")\n'''
BAD='''from pyspark.sql import functions as F\ndef transform(spark,input_prefix,output_prefix):\n    raise NameError("Unknown transformation")\n'''

def setup(tmp_path,inputs=True):
    wf=Workflow(tmp_path)
    wf.analyze((FIX/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
        (FIX/'original-conversion-output (4).zip').read_bytes(),
        (FIX/'transform.ps1').read_bytes(),
        {'Employees.csv':(FIX/'Employees.csv').read_bytes()} if inputs else {},{})
    return wf

def response(code):return json.dumps({'code':code,'explanation':'Source-derived code'})

def test_runtime_failure_retry_then_success_review_only(tmp_path):
    wf=setup(tmp_path);calls=[];run=[]
    def transport(prompt):
        calls.append(prompt)
        return response(BAD if len(calls)==1 else VALID)
    def check(code):
        run.append(code)
        return {'status':'FAILED','category':'CODE_RUNTIME','reason':'NameError: missing transform variable','verified':False} if code==BAD else {'status':'OUTPUT_GENERATED','category':'PASS','verified':True,'outputs':[{'name':'ActiveEmployees.csv','actualRows':1}]}
    result=wf.propose(transport=transport,runtime_test=check,approve_cost=True,approve_transmission=True)
    assert len(calls)==2 and len(run)==2
    assert 'CODE_RUNTIME' in calls[1] and 'NameError' in calls[1]
    assert result['runtimePreflight']['verified'] is True
    assert result['validationAttempts'][0]['phase']=='RUNTIME_REJECTED'
    assert result['validationAttempts'][1]['phase']=='RUNTIME_PASSED'
    assert not (tmp_path/'candidate.py').exists()  # review required
    assert wf.approve(sha(VALID.encode()),True)['deployAllowed'] is False

def test_missing_input_does_not_call_runtime_or_retry(tmp_path):
    wf=setup(tmp_path,inputs=False);calls=[]
    result=wf.propose(transport=lambda p:(calls.append(p) or response(VALID)),approve_cost=True,approve_transmission=True,
        runtime_test=lambda _: {'status':'NOT_RUN','category':'NO_INPUT','verified':False})
    assert len(calls)==1 and result['runtimePreflight']['status']=='NOT_RUN'
    assert 'runtimePreflight' in json.loads((tmp_path/'proposal.json').read_text())

def test_environment_failure_no_ai_retry(tmp_path):
    wf=setup(tmp_path);calls=[]
    result=wf.propose(transport=lambda p:(calls.append(p) or response(VALID)),approve_cost=True,approve_transmission=True,
        runtime_test=lambda _: {'status':'FAILED','category':'ENVIRONMENT','reason':'Java unavailable','verified':False})
    assert len(calls)==1
    assert result['runtimePreflight']['category']=='ENVIRONMENT'
    assert result['runtimePreflight']['verified'] is False

def test_persistent_code_failure_stops_bounded(tmp_path):
    wf=setup(tmp_path);calls=[]
    with pytest.raises(RemediationBlocked,match='after 3 attempts'):
        wf.propose(transport=lambda p:(calls.append(p) or response(BAD)),approve_cost=True,approve_transmission=True,
            runtime_test=lambda _: {'status':'FAILED','category':'CODE_RUNTIME','reason':'NameError','verified':False})
    assert len(calls)==3
    assert not (tmp_path/'proposal.json').exists()
    assert not (tmp_path/'candidate.py').exists()

def test_genuine_missing_fixtures_does_not_start_spark(tmp_path):
    wf=setup(tmp_path,inputs=False)
    r=preflight_local(tmp_path,VALID)
    assert r['status']=='NOT_RUN' and not r['verified']

def test_runtime_classification():
    assert _runtime_category('AnalysisException [UNRESOLVED_COLUMN] Salary')=='DATA_CONTRACT'
    assert _runtime_category('FileNotFoundException: input path does not exist')=='MISSING_INPUT'
    assert _runtime_category('NameError: missing variable')=='CODE_RUNTIME'
    assert _runtime_category('JAVA_GATEWAY_EXITED')=='ENVIRONMENT'

def test_preflight_structured_result_is_independent_of_spark_console(tmp_path,monkeypatch):
    wf=setup(tmp_path)
    class Proc:
        returncode=0
        stdout='Spark startup output\\n{"status":"IGNORE"}\\n'
        stderr='WARN Shell: missing native Hadoop library'
    def fake_run(cmd,**opts):
        Path(cmd[3]).write_text(json.dumps({'status':'OUTPUT_GENERATED','outputs':[{'name':'ActiveEmployees.csv','actualRows':2}]}))
        assert cmd[0]==sys.executable
        assert 'AWS_PROFILE' not in opts['env']
        return Proc()
    monkeypatch.setenv('AWS_PROFILE','ssis-glue-poc')
    monkeypatch.setattr('unsupported_process_ai.subprocess.run',fake_run)
    r=preflight_local(tmp_path,VALID)
    assert r['status']=='OUTPUT_GENERATED' and r['verified']
    assert r['outputs'][0]['actualRows']==2


def test_preflight_reports_original_exception_instead_of_spark_stack_tail(tmp_path,monkeypatch):
    wf=setup(tmp_path)
    class Proc:
        returncode=1
        stdout='Spark logs ignored'
        stderr='org.apache.spark.deploy.SparkSubmit.doRunMain'
    def fake_run(cmd,**opts):
        Path(cmd[3]).write_text(json.dumps({'status':'FAILED','error':'[UNRESOLVED_COLUMN] Cannot resolve Salary',
             'exceptionType':'AnalysisException','tracebackTail':'AnalysisException: [UNRESOLVED_COLUMN] Salary'}))
        return Proc()
    monkeypatch.setattr('unsupported_process_ai.subprocess.run',fake_run)
    r=preflight_local(tmp_path,VALID)
    assert r['status']=='FAILED' and r['category']=='DATA_CONTRACT'
    assert 'UNRESOLVED_COLUMN' in r['reason']
