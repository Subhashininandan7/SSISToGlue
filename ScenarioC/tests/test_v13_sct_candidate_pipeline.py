"""Regression tests use ACTUAL uploaded SCT CLI bytes as a FIXTURE.
AWS and dtexec API tests are stubbed; they are NOT proof of cloud/Windows execution.
"""
import base64
import csv
import io
import json
import hashlib
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import cli, cloud, sct_candidate, ssis_verify, sct_local_check

@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'HOME',tmp_path/'home')
    monkeypatch.setattr(cli,'FIXTURES',ROOT/'fixtures')
    return tmp_path


def source(session):
    path=ROOT/'ssis-packages'/'A_Employees_Active_Bonus_FIXED.dtsx'
    return cli.handle({'action':'source','sessionId':session,'fileName':path.name,
                       'contentBase64':base64.b64encode(path.read_bytes()).decode()})


def prepared(env):
    sid=cli.handle({'action':'new','scenario':'A'})['id']
    source(sid)
    p=cli.session_path(sid)
    blob=(ROOT/'evidence'/'ScenarioA_Unfixed_ActualSCT_Output.zip').read_bytes()
    r=cli.record_sct_output(p,cli.load(sid)[1],blob,'REAL_SCT_BATCH_CLI')
    cli.store(p/'sct'/'auto-result.json',{'exitCode':0,'pythonModules':3,'method':'REAL_SCT_BATCH_CLI'})
    result=cli.handle({'action':'prepare-sct','sessionId':sid})
    return sid,p,result


def test_fixed_source_isolated_connector_and_contract():
    import xml.etree.ElementTree as ET
    fixed=ROOT/'ssis-packages'/'A_Employees_Active_Bonus_FIXED.dtsx'
    old=ROOT/'ssis-packages'/'A_Employees_Active_Bonus.dtsx'
    with pytest.raises(sct_candidate.CandidateBlocked,match='overwrite independent'):
        sct_candidate.contract_for_package(old)
    contract=sct_candidate.contract_for_package(fixed)
    assert 'ssis-output' in contract['ssisOutput']
    assert 'expected' not in contract['ssisOutput']
    assert len(contract['dataflowComponents'])==4
    tree=ET.parse(fixed)
    names=[n.get(sct_candidate.D+'ObjectName') for n in tree.findall(sct_candidate.D+'ConnectionManagers/'+sct_candidate.D+'ConnectionManager')]
    assert set(names)=={'Employees Input','ActiveEmployees Output'}


def test_real_sct_fixture_generates_script_not_reference(env):
    sid,p,r=prepared(env)
    assert r['provenance']=='REAL_SCT_BATCH_CLI'
    assert r['status']=='SCT_SCENARIO_A_PREFLIGHT_READY_NOT_RUN'
    assert len(r['edits'])>=7
    assert r['gate']['readyForControlledGlueTest'] is False
    assert r['runtimeVerified'] is False
    data=(p/'sct-candidate'/sct_candidate.FILTER_MODULE).with_suffix('.py').read_text()
    assert 'spark.sql(' in data and data.count('spark.sql(')==3
    assert 'CAST(0.10 AS DECIMAL(3,2))' in data
    assert 'WHERE `status` = \'Active\'' in data
    assert 'os.environ["FORGE_INPUT_CSV"]' in data
    assert 'os.environ["FORGE_OUTPUT_CSV"]' in data
    assert 'errorifexists' in data
    assert 'sct_utils' not in data and 'D:\\' not in data
    assert 'Salary' in data and 'Bonus' in data
    assert 'referenc' not in (p/'sct-candidate'/'glue_entry_sct_a.py').read_text().lower()
    with zipfile.ZipFile(p/'sct-candidate'/'sct_modules.zip') as z:
        assert set(z.namelist())=={'variables.py',sct_candidate.FILTER_MODULE+'.py','a_employees_active_bonus.py'}
        assert 'a_employees_active_bonus' in z.read('a_employees_active_bonus.py').decode()


def test_unknown_sct_ast_is_blocked(env):
    sid,p,r=prepared(env)
    raw=(p/'sct'/'original'/'sct_001.py')
    raw.write_text(raw.read_text()+'\n__import__("os").system("echo unsafe")\n')
    with pytest.raises(ValueError,match='changed since import'):
        cli.handle({'action':'prepare-sct','sessionId':sid})
    manifest=json.loads((p/'sct'/'manifest.json').read_text())
    manifest[1]['sha256']=hashlib.sha256(raw.read_bytes()).hexdigest()
    cli.store(p/'sct'/'manifest.json',manifest)
    with pytest.raises(ValueError,match='Unexpected SCT-generated AST'):
        cli.handle({'action':'prepare-sct','sessionId':sid})


def test_user_attestation_requires_real_csv_and_label_not_verified(env):
    sid,p,r=prepared(env)
    csvbytes=(ROOT/'fixtures'/'expected'/'ActiveEmployees.csv').read_bytes()
    with pytest.raises(ValueError,match='Explicit SSDT-run attestation'):
        cli.handle({'action':'attest-ssdt','sessionId':sid,'contentBase64':base64.b64encode(csvbytes).decode()})
    proof=cli.handle({'action':'attest-ssdt','sessionId':sid,'attestExecutedInSSDT':True,
                      'contentBase64':base64.b64encode(csvbytes).decode()})
    assert proof['status']=='USER_ATTESTED_SSDT_OUTPUT_MATCHES_EXPECTED'
    assert proof['independentlyVerifiedExecution'] is False
    assert proof['rowParity']['match']


def test_sct_deploy_fail_closed_for_missing_evidence(env,monkeypatch):
    sid,p,r=prepared(env)
    s=cli.load(sid)[1]
    s['awsConfig']={'profile':'ssis-glue-poc','region':'ap-southeast-2','bucket':'demo-bucket','prefix':'ssis-forge','glueRole':'DemoRole'}
    cli.save(p,s)
    with pytest.raises(ValueError,match='verify actual SSIS execution'):
        cli.handle({'action':'deploy','sessionId':sid,'origin':'SCT_CONVERTED_CANDIDATE','sctApproval':True})
    s=cli.load(sid)[1];s['ssisValidation']={'status':'USER_ATTESTED_SSDT_OUTPUT_MATCHES_EXPECTED'};cli.save(p,s)
    with pytest.raises(ValueError,match='actual local PySpark'):
        cli.handle({'action':'deploy','sessionId':sid,'origin':'SCT_CONVERTED_CANDIDATE','sctApproval':True})
    assert cli.load(sid)[1]['deployment']=='NOT_RUN'


def test_local_spark_failure_does_not_pass_gate(env):
    sid,p,r=prepared(env)
    class Failure:
        returncode=1;stdout=b'';stderr=b'java missing'
    check=sct_local_check.check(p/'sct-candidate',ROOT/'fixtures',p,run=lambda *a,**kw:Failure())
    assert check['localSparkParity'] is False and check['status']=='LOCAL_SPARK_EXECUTION_FAILED'


def test_real_dtexec_invocation_is_isolated_and_checked(env):
    sid,p,r=prepared(env)
    runner=env/'DTExec.exe';runner.write_bytes(b'placeholder')
    def fake_run(cmd,**kwargs):
        import xml.etree.ElementTree as ET
        root=ET.parse(cmd[2]).getroot();nested=root.findall(sct_candidate.D+'ConnectionManagers/'+sct_candidate.D+'ConnectionManager')
        for c in nested:
            if c.get(sct_candidate.D+'ObjectName')=='ActiveEmployees Output':
                out=Path(c.find(sct_candidate.D+'ObjectData/'+sct_candidate.D+'ConnectionManager').get(sct_candidate.D+'ConnectionString'))
                assert 'expected' not in str(out)
                out.write_bytes((ROOT/'fixtures'/'expected'/'ActiveEmployees.csv').read_bytes())
        return SimpleNamespace(returncode=0,stdout=b'Fake runner used IN TESTS ONLY')
    proof=ssis_verify.execute(p/'source'/'original.dtsx',ROOT/'fixtures',p,runner=str(runner),run=fake_run)
    assert proof['status']=='SSIS_DTS_EXECUTED_PARITY_VERIFIED'
    assert proof['executionType']=='ACTUAL_WINDOWS_DTEXEC' # test double, no genuine windows execution claim outside test
    assert proof['rowParity']['match']


def test_sct_glue_api_uses_generated_artifacts_not_reference(env,monkeypatch):
    sid,p,r=prepared(env)
    cfg={'profile':'ssis-glue-poc','region':'ap-southeast-2','bucket':'demo-bucket','prefix':'ssis-forge','glueRole':'DemoRole'}
    class S3:
        def __init__(self):self.objects={}
        def put_object(self,**kwargs):self.objects[kwargs['Key']]=kwargs['Body']
    class Glue:
        class exceptions:
            class EntityNotFoundException(Exception):pass
        def __init__(self):self.jobs={}
        def get_job(self,JobName):raise self.exceptions.EntityNotFoundException()
        def create_job(self,Name,**kwargs):self.jobs[Name]=kwargs
    class STS:
        def get_caller_identity(self):return {'Account':'123456789012'}
    s3=S3();glue=Glue()
    monkeypatch.setattr(cloud,'clients',lambda a,b:(s3,glue,STS(),None))
    s=cli.load(sid)[1];s['awsConfig']=cfg
    s['ssisValidation']={'status':'USER_ATTESTED_SSDT_OUTPUT_MATCHES_EXPECTED','sourceSha256':r['sourceSha256']}
    s['localCandidateValidation']={'status':'LOCAL_SCT_PYSPARK_OUTPUT_MATCHED','candidateZipSha256':r['pyModulesZipSha256']}
    cli.save(p,s)
    out=cli.handle({'action':'deploy','sessionId':sid,'origin':'SCT_CONVERTED_CANDIDATE','sctApproval':True})
    assert out['origin']=='SCT_CONVERTED_CANDIDATE'
    assert out['jobName'].startswith('ssis-sct-a-')
    assert 'sct-output' in out['outputS3']
    job=glue.jobs[out['jobName']]
    assert job['DefaultArguments']['--extra-py-files'].endswith('/sct_generated_modules.zip')
    assert job['Command']['ScriptLocation'].endswith('/sct_glue_entry.py')
    assert all('reference_glue_job' not in key for key in s3.objects)
    assert out['runtimeVerified'] is False


def test_tampering_blocks_deploy_after_review(env,monkeypatch):
    sid,p,r=prepared(env)
    cfg={'profile':'ssis-glue-poc','region':'ap-southeast-2','bucket':'demo-bucket','prefix':'ssis-forge','glueRole':'DemoRole'}
    s=cli.load(sid)[1];s['awsConfig']=cfg
    s['ssisValidation']={'status':'USER_ATTESTED_SSDT_OUTPUT_MATCHES_EXPECTED'}
    s['localCandidateValidation']={'status':'LOCAL_SCT_PYSPARK_OUTPUT_MATCHED','candidateZipSha256':r['pyModulesZipSha256']}
    cli.save(p,s)
    with (p/'sct-candidate'/'sct_modules.zip').open('ab') as fh:fh.write(b'changed')
    with pytest.raises(cloud.CloudError,match='changed after approval'):
        cli.handle({'action':'deploy','sessionId':sid,'origin':'SCT_CONVERTED_CANDIDATE','sctApproval':True})
