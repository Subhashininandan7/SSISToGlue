"""Mocked Bedrock patch request and local artifacts. NO REAL BEDROCK/SSIS/GLUE EXECUTION."""
import base64
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import bedrock_patch as bp
import cli,sct_candidate


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'HOME',tmp_path/'home')
    monkeypatch.setattr(cli,'FIXTURES',ROOT/'fixtures')
    sid=cli.new('A')['id']
    source=ROOT/'ssis-packages'/'A_Employees_Active_Bonus_FIXED.dtsx'
    cli.submit_source({'sessionId':sid,'fileName':source.name,'contentBase64':base64.b64encode(source.read_bytes()).decode()})
    p,s=cli.load(sid)
    cli.record_sct_output(p,s,(ROOT/'evidence'/'ScenarioA_Unfixed_ActualSCT_Output.zip').read_bytes(),'REAL_SCT_BATCH_CLI')
    cli.store(p/'sct'/'auto-result.json',{'exitCode':0,'pythonModules':3})
    cli.prepare_sct_candidate({'sessionId':sid})
    return p,sid


class FakeBedrock:
    def __init__(self,sql=None):self.calls=[];self.sql=sql
    def converse(self,**kw):
        self.calls.append(kw)
        prompt=json.loads(kw['messages'][0]['content'][0]['text'])
        assert 'D:\\' not in str(prompt)
        assert 's3://' not in str(prompt)
        assert 'from pyspark' not in str(prompt)
        source=prompt['sourceSql']
        proposal=self.sql or source.replace("WHERE `status` = 'Active'", "WHERE COALESCE(`status`, '') = 'Active'")
        return {'output':{'message':{'content':[{'text':json.dumps({'target':prompt['target'],
            'replacementSql':proposal,'explanation':'Preserves null-safe active selection',
            'parityTests':['run source SSIS and local PySpark CSV parity']})}]}},
            'usage':{'inputTokens':110,'outputTokens':100}}


def fail_status(p,sid):
    s=cli.load(sid)[1]
    s['localCandidateValidation']={'status':'LOCAL_SPARK_EXECUTION_FAILED',
        'failureCode':'SPARK_SQL_ANALYSIS_FAILURE'}
    cli.save(p,s)


def test_healthy_candidate_does_not_request_billed_ai(prepared,monkeypatch):
    p,sid=prepared
    result=cli.ai_patch_issues({'sessionId':sid})
    assert result['status']=='NO_UNRESOLVED_RUNTIME_ISSUE'
    assert result['eligible']==[]
    # Even if UI requests model call, it must return without a boto3 session.
    result=cli.ai_patch_propose({'sessionId':sid,'approveModelCost':True,'approveCodeTransmission':True,'target':'ACTIVE_FILTER'})
    assert result['status']=='NO_UNRESOLVED_RUNTIME_ISSUE'
    assert not (p/'bedrock'/'patch-proposal.json').exists()


def test_infrastructure_failure_is_not_a_code_patch_issue(prepared):
    p,sid=prepared
    s=cli.load(sid)[1]
    s['localCandidateValidation']={'status':'LOCAL_SPARK_EXECUTION_FAILED',
        'failureCode':'ENVIRONMENT_OR_DEPENDENCY_FAILURE'}
    cli.save(p,s)
    r=cli.ai_patch_issues({'sessionId':sid})
    assert r['status']=='NOT_AI_REPAIRABLE_RUNTIME_FAILURE' and not r['eligible']


def test_patch_requires_consent_and_proposes_reviewable_single_sql_diff(prepared,monkeypatch):
    p,sid=prepared;fail_status(p,sid)
    with pytest.raises(ValueError,match='charges AND transmission'):
        cli.ai_patch_propose({'sessionId':sid,'target':'ACTIVE_FILTER','approveModelCost':True})
    import boto3
    fake=FakeBedrock()
    monkeypatch.setattr(boto3,'Session',lambda **kw:SimpleNamespace(client=lambda service:fake))
    result=cli.ai_patch_propose({'sessionId':sid,'approveModelCost':True,
        'approveCodeTransmission':True,'target':'ACTIVE_FILTER'})
    assert result['status']=='AI_PATCH_PROPOSED_REVIEW_REQUIRED'
    assert result['verification']['pythonSyntax'] is True
    assert result['verification']['localPySparkParity'] is False
    assert result['usage']['inputTokens']==110
    assert len(fake.calls)==1
    assert '+\t' in result['diff'] or '+    ' in result['diff'] or '+\t' in (p/'bedrock'/'patch-diff.txt').read_text()
    assert (p/'bedrock'/'patch-proposal.json').is_file()
    pre=json.loads((p/'sct-candidate'/'preflight.json').read_text())
    assert 'aiPatches' not in pre
    assert cli.load(sid)[1]['bedrockPatch']['status']=='AI_PROPOSED_NOT_APPLIED'


def test_model_dml_and_semantic_deviation_refused(prepared):
    p,sid=prepared;folder=p/'sct-candidate';fail_status(p,sid)
    base=bp.detect_targets(folder,{'status':'LOCAL_SPARK_EXECUTION_FAILED',
        'failureCode':'SPARK_SQL_ANALYSIS_FAILURE'})
    assert len(base['eligible'])==2
    code=bp._candidate_file(folder).read_text()
    src=bp._sql_call_nodes(code)[0].value
    for bad in ["DROP TABLE active_x0020_filter",src.replace("'Active'","'Inactive'"),
                src+"; DELETE FROM customers", "SELECT * FROM active_x0020_filter WHERE 1=1"]:
        with pytest.raises(bp.PatchBlocked):bp._replace_sql_literal(code,'ACTIVE_FILTER',bad)
    before=bp._sql_call_nodes(code)[2].value
    with pytest.raises(bp.PatchBlocked):bp._replace_sql_literal(code,'BONUS_DERIVATION',before.replace('0.10','0.99'))


def test_approved_patch_rehashes_zip_clears_runtime_proof_and_blocks_deploy(prepared,monkeypatch):
    p,sid=prepared;fail_status(p,sid);folder=p/'sct-candidate'
    monkeypatch.setattr(cli,'check_local_sct',lambda *a,**kw:{'status':'LOCAL_SPARK_EXECUTION_FAILED','failureCode':'ENVIRONMENT_OR_DEPENDENCY_FAILURE','localSparkParity':False})
    fake=FakeBedrock();candidate=bp.propose(folder,cli.load(sid)[1]['localCandidateValidation'],
                                           'ACTIVE_FILTER','amazon.nova-lite-v1:0','ap-southeast-2',fake)
    s=cli.load(sid)[1];s['bedrockPatch']={'status':'AI_PROPOSED_NOT_APPLIED'}
    s['awsConfig']={'profile':'ssis-glue-poc','region':'ap-southeast-2',
                     'bucket':'demo-bucket','prefix':'ssis-forge','glueRole':'DemoRole'}
    s['ssisValidation']={'status':'USER_ATTESTED_SSDT_OUTPUT_MATCHES_EXPECTED'}
    s['localCandidateValidation']={'status':'LOCAL_SCT_PYSPARK_OUTPUT_MATCHED',
                                    'candidateZipSha256':candidate['baseZipSha256']}
    cli.save(p,s)
    with pytest.raises(ValueError,match='Review the generated diff'):
        cli.ai_patch_accept({'sessionId':sid,'baseZipSha256':candidate['baseZipSha256']})
    with pytest.raises(ValueError,match='fingerprint mismatch'):
        cli.ai_patch_accept({'sessionId':sid,'approveExactDiff':True,'baseZipSha256':'0'*64})
    out=cli.ai_patch_accept({'sessionId':sid,'approveExactDiff':True,'baseZipSha256':candidate['baseZipSha256']})
    assert out['status']=='AI_PATCH_APPLIED_BUT_DEPLOYMENT_BLOCKED'
    assert out['automaticLocalValidation']['localSparkParity'] is False
    assert out['candidateZipSha256']!=candidate['baseZipSha256']
    with zipfile.ZipFile(folder/'sct_modules.zip') as z:
        assert 'COALESCE' in z.read(sct_candidate.FILTER_MODULE+'.py').decode()
        assert set(z.namelist())=={'a_employees_active_bonus.py',sct_candidate.FILTER_MODULE+'.py','variables.py'}
    pre=json.loads((folder/'preflight.json').read_text())
    assert pre['aiPatches'][0]['origin']=='BEDROCK_APPROVED_EXPRESSION_PATCH'
    assert pre['pyModulesZipSha256']==out['candidateZipSha256']
    assert cli.load(sid)[1]['localCandidateValidation']['status']=='LOCAL_SPARK_EXECUTION_FAILED'
    with pytest.raises(ValueError,match='run actual local PySpark'):
        cli.deploy({'sessionId':sid,'origin':'SCT_CONVERTED_CANDIDATE','sctApproval':True})
    # A second approval is not allowed, and prior certified hashes cannot be replayed.
    with pytest.raises(ValueError,match='No unapproved'):
        cli.ai_patch_accept({'sessionId':sid,'approveExactDiff':True,'baseZipSha256':candidate['baseZipSha256']})


def test_ai_patch_rejects_sql_paths_in_prompt_and_stale_proposal(prepared):
    p,sid=prepared;folder=p/'sct-candidate'
    with pytest.raises(bp.PatchBlocked,match='confidential'):
        bp._redaction_guard('SELECT password FROM my_table WHERE url = "s3://bucket"')
    code=bp._candidate_file(folder).read_text()
    with pytest.raises(bp.PatchBlocked,match='Invalid|Unsafe|unsupported'):
        bp._replace_sql_literal(code,'ACTIVE_FILTER','SELECT * FROM active_x0020_filter; DROP TABLE x')
    assert not (p/'bedrock'/'patch-applied.json').exists()


def test_model_response_must_be_strict_json_target(prepared):
    p,sid=prepared;folder=p/'sct-candidate'
    local={'status':'LOCAL_SCT_PYSPARK_OUTPUT_MISMATCH'}
    with pytest.raises(bp.PatchBlocked,match='valid JSON'):
        bp.propose(folder,local,'ACTIVE_FILTER','amazon.nova-lite-v1:0','ap-southeast-2',
            SimpleNamespace(converse=lambda **k:{'output':{'message':{'content':[{'text':'Here is your fix'}]}}}))
    assert not (p/'bedrock'/'patch-proposal.json').exists()


def test_successful_auto_parity_unlocks_ai_patch_specific_gate(prepared,monkeypatch):
    p,sid=prepared;fail_status(p,sid);folder=p/'sct-candidate'
    candidate=bp.propose(folder,cli.load(sid)[1]['localCandidateValidation'],
        'ACTIVE_FILTER','amazon.nova-lite-v1:0','ap-southeast-2',FakeBedrock())
    s=cli.load(sid)[1];s['bedrockPatch']={'status':'AI_PROPOSED_NOT_APPLIED'}
    s['ssisValidation']={'status':'USER_ATTESTED_SSDT_OUTPUT_MATCHES_EXPECTED'}
    cli.save(p,s)
    def fake_validated(fixture_dir,fixtures,session):
        pre=json.loads((Path(fixture_dir)/'preflight.json').read_text())
        return {'status':'LOCAL_SCT_PYSPARK_OUTPUT_MATCHED','localSparkParity':True,
                'candidateZipSha256':pre['pyModulesZipSha256']}
    monkeypatch.setattr(cli,'check_local_sct',fake_validated)
    out=cli.ai_patch_accept({'sessionId':sid,'approveExactDiff':True,
                             'baseZipSha256':candidate['baseZipSha256']})
    assert out['status']=='AI_PATCH_APPLIED_AND_LOCAL_PARITY_VERIFIED'
    assert out['readyForControlledGlueTest']
    assert cli.load(sid)[1]['bedrockPatch']['status']=='AI_PATCH_LOCAL_PARITY_PASSED'
    assert out['automaticLocalValidation']['candidateZipSha256']==out['candidateZipSha256']


def test_glue_upload_uses_approved_model_patch_zip_never_reference(prepared,monkeypatch):
    import cloud
    p,sid=prepared;fail_status(p,sid);folder=p/'sct-candidate'
    proposal=bp.propose(folder,cli.load(sid)[1]['localCandidateValidation'],
        'ACTIVE_FILTER','amazon.nova-lite-v1:0','ap-southeast-2',FakeBedrock())
    s=cli.load(sid)[1];s['bedrockPatch']={'status':'AI_PROPOSED_NOT_APPLIED'}
    s['ssisValidation']={'status':'USER_ATTESTED_SSDT_OUTPUT_MATCHES_EXPECTED'}
    cfg={'profile':'ssis-glue-poc','region':'ap-southeast-2','bucket':'demo-bucket',
         'prefix':'ssis-forge','glueRole':'DemoRole'}
    s['awsConfig']=cfg;cli.save(p,s)
    monkeypatch.setattr(cli,'check_local_sct',lambda folder,*a:{'status':'LOCAL_SCT_PYSPARK_OUTPUT_MATCHED',
        'candidateZipSha256':json.loads((Path(folder)/'preflight.json').read_text())['pyModulesZipSha256']})
    approved=cli.ai_patch_accept({'sessionId':sid,'approveExactDiff':True,
                                  'baseZipSha256':proposal['baseZipSha256']})
    class S3:
        def __init__(self):self.objects={}
        def put_object(self,**kw):self.objects[kw['Key']]=kw['Body']
    class Glue:
        class exceptions:
            class EntityNotFoundException(Exception):pass
        def __init__(self):self.jobs={}
        def get_job(self,JobName):raise self.exceptions.EntityNotFoundException()
        def create_job(self,Name,**kw):self.jobs[Name]=kw
    class Sts:
        def get_caller_identity(self):return {'Account':'123456789012'}
    s3=S3();glue=Glue()
    monkeypatch.setattr(cloud,'clients',lambda *a:(s3,glue,Sts(),None))
    result=cli.deploy({'sessionId':sid,'origin':'SCT_CONVERTED_CANDIDATE','sctApproval':True})
    assert result['origin']=='SCT_CONVERTED_CANDIDATE'
    assert result['repairOrigin']=='APPROVED_BEDROCK_PLUS_DETERMINISTIC'
    assert result['modulesSha256']==approved['candidateZipSha256']
    staged=s3.objects[next(k for k in s3.objects if k.endswith('sct_generated_modules.zip'))]
    assert staged==(folder/'sct_modules.zip').read_bytes()
    assert all('reference_glue_job' not in k for k in s3.objects)
    assert 'Bedrock SQL patch' in glue.jobs[result['jobName']]['Description']


def test_local_spark_error_categorizer_does_not_mislabel_java_missing(prepared):
    from sct_local_check import check
    p,sid=prepared
    class Result:
        returncode=1;stdout=b'';stderr=b'ModuleNotFoundError: No module named pyspark'
    result=check(p/'sct-candidate',ROOT/'fixtures',p,run=lambda *a,**kw:Result())
    assert result['failureCode']=='ENVIRONMENT_OR_DEPENDENCY_FAILURE'
    assert result['localSparkParity'] is False
