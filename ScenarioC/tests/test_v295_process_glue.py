"""Regression: cloud deployment is real, hash gated, and parity is not invented."""
import io, json, sys
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import process_glue as pg
from unsupported_process_ai import Workflow,sha,read_json,write_json,RemediationBlocked
FIX=ROOT/'AI_Demo_Files'
CODE='''from pyspark.sql import functions as F

def transform(spark, input_prefix, output_prefix):
    df = spark.read.option("header", "true").csv(input_prefix + "/Employees.csv")
    df.filter(F.col("Status") == "Active").write.mode("overwrite").option("header", "true").csv(output_prefix + "/ActiveEmployees.csv")
'''
class Missing(Exception):pass
class S3:
    def __init__(self):self.files={};self.uploads=[]
    def put_object(self,**k):self.files[k['Key']]=k['Body'];self.uploads.append(k)
    def get_object(self,**k):return {'Body':io.BytesIO(self.files[k['Key']])}
    def get_paginator(self,what):
        obj=self
        class Pages:
            def paginate(self,**kwargs):return [{'Contents':[{'Key':key,'Size':len(value)} for key,value in obj.files.items() if key.startswith(kwargs['Prefix'])]}]
        return Pages()
class Glue:
    exceptions=SimpleNamespace(EntityNotFoundException=Missing)
    def __init__(self):self.jobs={};self.runs=[];self.state='SUCCEEDED'
    def get_job(self,JobName):
        if JobName not in self.jobs:raise Missing()
        return self.jobs[JobName]
    def create_job(self,Name,**k):self.jobs[Name]=k
    def start_job_run(self,JobName):self.runs.append(JobName);return {'JobRunId':'jr_123456789'}
    def get_job_run(self,**kw):return {'JobRun':{'JobRunState':self.state}}
class STS:
    def get_caller_identity(self):return {'Account':'123456789012','Arn':'arn:aws:sts::123456789012:assumed-role/Test/Session'}
class Logs:
    def filter_log_events(self,**kw):return {'events':[]}

def setup(tmp_path,approved=True,validated=True):
    flow=Workflow(tmp_path)
    flow.analyze((FIX/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
       (FIX/'original-conversion-output (4).zip').read_bytes(),
       (FIX/'transform.ps1').read_bytes(),{'Employees.csv':(FIX/'Employees.csv').read_bytes()},{})
    if approved:
        flow.propose(transport=lambda p:json.dumps({'code':CODE,'explanation':'Source-derived code'}),
           approve_cost=True,approve_transmission=True)
        flow.approve(sha(CODE.encode()),True)
        if validated:
            manifest=read_json(tmp_path/'manifest.json');manifest['status']='LOCAL_OUTPUT_GENERATED'
            write_json(tmp_path/'manifest.json',manifest)
            write_json(tmp_path/'local-validation-evidence.json',{'status':'OUTPUT_GENERATED','codeSha256':sha(CODE.encode()),'outputs':[{'name':'ActiveEmployees.csv','actualRows':1}]})
    return flow
CFG={'profile':'ssis-glue-poc','region':'ap-southeast-2','s3Prefix':'s3://ssis-glue-poc-bucket/demo-outputs', 'glueRole':'AWSGlueServiceRole-SSISPoc'}

def test_unapproved_and_unvalidated_never_call_cloud(tmp_path):
    for approved,validated in [(False,False),(True,False)]:
        folder=tmp_path/f'{approved}_{validated}';folder.mkdir()
        setup(folder,approved,validated)
        with pytest.raises(RemediationBlocked):pg.deploy(folder,'a'*16,CFG,approve=True,client_factory=lambda *_:pytest.fail('cloud contacted'))

def test_deploy_exact_hash_run_and_inspect_output(tmp_path):
    setup(tmp_path)
    s3,glue,sts,logs=S3(),Glue(),STS(),Logs()
    clients=lambda *args:(s3,glue,sts,logs)
    with pytest.raises(RemediationBlocked,match='Explicit approval'):pg.deploy(tmp_path,'a'*16,CFG,client_factory=clients)
    d=pg.deploy(tmp_path,'a'*16,CFG,approve=True,client_factory=clients)
    assert d['origin']=='APPROVED_BEDROCK_SCT_25029'
    assert d['approvedCodeSha256']==sha(CODE.encode())
    assert len(glue.jobs)==1 and all(x['ServerSideEncryption']=='AES256' for x in s3.uploads)
    assert glue.jobs[d['jobName']]['DefaultArguments']['--OUTPUT_PREFIX']==d['outputS3']
    with pytest.raises(RemediationBlocked,match='already deployed'):
        pg.deploy(tmp_path,'a'*16,CFG,approve=True,client_factory=clients)
    with pytest.raises(RemediationBlocked,match='Explicit Glue execution'):pg.run(tmp_path,client_factory=clients)
    run=pg.run(tmp_path,approve=True,client_factory=clients)
    assert run['status']=='SUBMITTED'
    with pytest.raises(RemediationBlocked,match='Existing Glue job run'):pg.run(tmp_path,approve=True,client_factory=clients)
    key='demo-outputs/'+'a'*16+'/approved-ai/output/ActiveEmployees.csv/part-0000.csv'
    s3.files[key]=b'EmployeeID,Status\n101,Active\n'
    r=pg.poll(tmp_path,client_factory=clients)
    assert r['status']=='SUCCEEDED_OUTPUTS_GENERATED' and r['cloudOutputValidated']
    assert r['outputs'][0]['rows']==1
    assert r['ssisParity']=='NOT_PROVEN'

def test_code_mutation_blocks_deploy_and_run(tmp_path):
    setup(tmp_path)
    (tmp_path/'candidate.py').write_text(CODE+'\n# changed')
    with pytest.raises(RemediationBlocked,match='hash mismatch'):pg.deploy(tmp_path,'a'*16,CFG,approve=True,client_factory=lambda *_:pytest.fail('remote call'))

def test_successful_glue_without_output_not_treated_as_validated(tmp_path):
    setup(tmp_path)
    s3,glue,sts,logs=S3(),Glue(),STS(),Logs();clients=lambda *a:(s3,glue,sts,logs)
    pg.deploy(tmp_path,'b'*16,CFG,approve=True,client_factory=clients)
    pg.run(tmp_path,approve=True,client_factory=clients)
    r=pg.poll(tmp_path,client_factory=clients)
    assert r['status']=='SUCCEEDED_OUTPUT_CHECK_FAILED' and not r['cloudOutputValidated']

def test_cloud_contract_mismatch_does_not_claim_success(tmp_path):
    setup(tmp_path)
    s3,glue,sts,logs=S3(),Glue(),STS(),Logs();clients=lambda *a:(s3,glue,sts,logs)
    d=pg.deploy(tmp_path,'c'*16,CFG,approve=True,client_factory=clients)
    pg.run(tmp_path,approve=True,client_factory=clients)
    key='demo-outputs/'+'c'*16+'/approved-ai/output/ActiveEmployees.csv/part-0000.csv'
    s3.files[key]=b'EmployeeID,Status\n101,Active\n102,Active\n'
    r=pg.poll(tmp_path,client_factory=clients)
    assert r['status']=='SUCCEEDED_OUTPUT_CONTRACT_MISMATCH'
    assert r['localCloudContractMatch'] is False
    assert r['cloudOutputValidated'] is False

def test_bulk_deploy_run_poll_preserves_original_sct_warning(tmp_path,monkeypatch):
    import bulk,cli,base64
    old=cli.HOME;cli.HOME=tmp_path/'data'
    try:
        pid=bulk.create(cli,{})['id']
        name='C_Unsupported_Execute_Process_AI_Demo.dtsx'
        bulk.add(cli,{'portfolioId':pid,'fileName':name,'contentBase64':base64.b64encode((FIX/name).read_bytes()).decode()})
        e=bulk.status(cli,{'portfolioId':pid})['packages'][0]
        session=cli.session_path(e['sessionId'])
        ai=session/'process-ai';setup(ai)
        plan=bulk._read(cli,pid);plan['packages'][0]['processAIKind']='EXECUTE_PROCESS_25029'
        plan['packages'][0]['blockers']=['SCT 25029: Microsoft.ExecuteProcess requires reviewed PySpark replacement']
        plan['packages'][0]['state']='LOCAL_OUTPUT_GENERATED';bulk._save(cli,bulk._path(cli,pid),plan)
        s3,glue,sts,logs=S3(),Glue(),STS(),Logs()
        clients=lambda *a:(s3,glue,sts,logs)
        monkeypatch.setattr(pg.cloud,'clients',clients)
        from cloud import identity
        def call(operation,**kw):return bulk.step(cli,{'portfolioId':pid,'packageName':name,'operation':operation,**CFG,**kw})
        r=call('aws')
        assert r['state']=='AWS_VERIFIED'
        r=call('deploy',approvePortfolioDeployment=True)
        assert r['state']=='DEPLOYED'
        e=bulk.status(cli,{'portfolioId':pid})['packages'][0]
        assert e['blockers']==[] and '25029' in e['sctWarnings'][0]
        assert e['aiCloudOrigin']=='APPROVED_BEDROCK_SCT_25029'
        r=call('run',approvePortfolioExecution=True)
        assert r['state']=='RUN_SUBMITTED'
        key=f'demo-outputs/{e["sessionId"]}/approved-ai/output/ActiveEmployees.csv/part-0000.csv'
        s3.files[key]=b'EmployeeID,Status\n101,Active\n'
        r=call('poll')
        assert r['state']=='GLUE_OUTPUT_GENERATED'
        assert r['result']['outputArchiveAvailable']
        assert (ai/'cloud-output.zip').is_file()
        observed=bulk.status(cli,{'portfolioId':pid})['packages'][0]
        assert observed['cloudOutputValidated'] and observed['glueStatus']=='SUCCEEDED'
        assert observed['cloudSSISParity']=='NOT_PROVEN'
    finally:cli.HOME=old
