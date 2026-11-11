from __future__ import annotations
import base64
import csv
import io
import json
import os
import sys
import zipfile
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import cli,scenarios,validation,repair,cloud

@pytest.fixture
def site(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'HOME',tmp_path/'state')
    monkeypatch.setattr(cli,'FIXTURES',ROOT/'fixtures')
    return tmp_path

@pytest.mark.parametrize('scenario,expected', [('A',{'ActiveEmployees.csv':3}),
  ('B',{'ValidOrders.csv':3,'RejectedOrders.csv':2}),('C',{'DimCustomerHistory.csv':5})])
def test_sample_reference_output(scenario,expected):
    for name,count in expected.items():
        rows=scenarios.read_csv(ROOT/'fixtures'/'expected'/name)
        assert len(rows)==count
    if scenario=='A':
        rows=scenarios.read_csv(ROOT/'fixtures'/'expected'/'ActiveEmployees.csv')
        assert [(r['EmployeeName'],r['Bonus']) for r in rows]==[
             ('Asha','5000.00'),('Chitra','6500.00'),('Dev','7050.00')]
    if scenario=='B':
        rows=scenarios.read_csv(ROOT/'fixtures'/'expected'/'RejectedOrders.csv')
        assert [r['OrderID'] for r in rows]==['O12','O14']
    if scenario=='C':
        rows=scenarios.read_csv(ROOT/'fixtures'/'expected'/'DimCustomerHistory.csv')
        assert len([r for r in rows if r['IsCurrent']=='1'])==4
        assert next(r for r in rows if r['CustomerID']=='C01' and r['IsCurrent']=='0')['EffectiveTo']=='2026-11-08'

def test_scd2_idempotent_second_run(site):
    d=ROOT/'fixtures'/'input'
    first=site/'history1.csv';second=site/'history2.csv'
    scenarios.output_c(d/'DimCustomer.csv',d/'CustomerChanges.csv',first)
    result=scenarios.output_c(first,d/'CustomerChanges.csv',second)
    assert result['inserted']==0 and result['expired']==0
    assert first.read_bytes()==second.read_bytes()

def test_scd2_duplicate_change_fails(site):
    d=ROOT/'fixtures'/'input';changes=site/'bad.csv'
    scenarios.write_csv(changes,['CustomerID','CustomerName','City'],[['C01','Ann','A'],['C01','Ann','B']])
    with pytest.raises(ValueError,match='Duplicate'):scenarios.output_c(d/'DimCustomer.csv',changes,site/'out.csv')

def test_reference_parity_and_multiplicity():
    results={name:scenarios.read_csv(ROOT/'fixtures'/'expected'/name) for name in scenarios.SCENARIOS['B']['outputs']}
    assert validation.compare_scenario(ROOT/'fixtures','B',results)['verified']
    bad={k:list(v) for k,v in results.items()};bad['ValidOrders.csv'].append(dict(bad['ValidOrders.csv'][0]))
    assert not validation.compare_scenario(ROOT/'fixtures','B',bad)['verified']

def test_repair_invalid_sct_syntax_and_safe_blocking():
    text="from pyspark.sql import SparkSession\nframe.'customerid'\n"
    result=repair.repair_text(text)
    assert result['syntaxPass']
    assert "frame['customerid']" in result['code']
    assert not result['deployApproved']
    assert result['originalSha256']!=result['candidateSha256']

def test_repair_denies_unresolved_driver():
    txt="x='specify driver'\ny=spark.read.format('jdbc').option('query','delete from foo').load()"
    result=repair.repair_text(txt)
    assert 'BLOCK_SPECIFY_DRIVER' in result['blockers']
    assert 'JDBC_READ_SQL_MUTATION_REVIEW' in result['blockers']
    assert not result['deployApproved']

def test_new_session_and_no_mock_aws(site):
    session=cli.handle({'action':'new','scenario':'A'})
    assert session['id']
    assert session['deployment']=='NOT_RUN'
    assert session['parity']=='NOT_RUN'
    assert cli.handle({'action':'session','sessionId':session['id']})['id']==session['id']
    with pytest.raises(ValueError,match='Verify AWS'):cli.handle({'action':'deploy','sessionId':session['id'],'origin':'INDEPENDENT_REFERENCE_NOT_SCT','referenceApproval':True})

def test_cli_cannot_claim_supported_without_ssis_upload(site):
    sid=cli.handle({'action':'new','scenario':'A'})['id']
    with pytest.raises(ValueError,match='Manual .scts entry retired'):cli.handle({'action':'cli','sessionId':sid,'batchExecutable':'fake','scriptScts':'fake'})

def test_reject_unsafe_source_format(site):
    sid=cli.handle({'action':'new','scenario':'A'})['id']
    with pytest.raises(ValueError,match='Not recognized'):
        cli.handle({'action':'source','sessionId':sid,'contentBase64':base64.b64encode(b'<Example/>').decode()})

def sct_archive(paths):
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:
        for name,data in paths.items():z.writestr(name,data)
    return base64.b64encode(buffer.getvalue()).decode()

def test_import_sct_then_analyze(site):
    sid=cli.handle({'action':'new','scenario':'B'})['id']
    z=sct_archive({'0. create-body-script/0. package.x.py':"x=frame.'id'\n",'1. create-script/empty.py':''})
    res=cli.handle({'action':'import','sessionId':sid,'contentBase64':z})
    assert res['scripts']==1
    assert res['status']=='SCT_GUI_OUTPUT_IMPORTED_REVIEW_ONLY'
    assert res['method']=='SCT_GUI_OUTPUT_IMPORT'
    out=cli.handle({'action':'repair','sessionId':sid})
    assert out['modules'][0]['syntaxPass']
    assert "frame['id']" in (cli.session_path(sid)/'candidates'/'candidate_1.py').read_text()
    assert cli.handle({'action':'session','sessionId':sid})['deployment']=='NOT_RUN'

def test_zip_slip_rejected(site):
    sid=cli.handle({'action':'new','scenario':'A'})['id']
    with pytest.raises(ValueError,match='Unsafe archive path'):
        cli.handle({'action':'import','sessionId':sid,'contentBase64':sct_archive({'../../steal.py':'print(1)'})})

def test_bedrock_needs_consent(site):
    sid=cli.handle({'action':'new','scenario':'A'})['id']
    with pytest.raises(ValueError,match='approvals'):
        cli.handle({'action':'bedrock','sessionId':sid})

def test_imported_sct_cannot_be_deployed_even_with_approval(site):
    sid=cli.handle({'action':'new','scenario':'A'})['id']
    with pytest.raises(ValueError,match='review-only'):
        cli.handle({'action':'deploy','sessionId':sid,'origin':'SCT_IMPORTED','referenceApproval':True})

@pytest.mark.parametrize('url',["https://example.com",'s3://bucket/../oops','s3://bad bucket/key','s3://my-bucket/'])
def test_bad_s3_urls(url):
    with pytest.raises(cloud.CloudError):cloud.parse_s3_url(url)

def test_job_name_allowlist():
    assert cloud.ALLOWED_JOB.fullmatch('ssis-demo-a-deadbeef1234abcd')
    assert not cloud.ALLOWED_JOB.fullmatch('prod-customer-write')

def test_bad_aws_config_does_not_call_network():
    with pytest.raises(cloud.CloudError):cloud.validate_settings({'s3Prefix':'s3://bucket/../oops','glueRole':'role'})

def test_glue_scripts_are_syntax_valid():
    compile((ROOT/'glue'/'unified_job.py').read_text(),'<glue>', 'exec')
    for p in (ROOT/'engine').glob('*.py'):compile(p.read_text(),str(p),'exec')

def test_no_sql_server_writes_in_demo_job():
    t=(ROOT/'glue'/'unified_job.py').read_text().lower()
    assert 'jdbc:' not in t and 'drop table' not in t and 'truncate table' not in t

def test_existing_repair_source_reused():
    from sct_generic_syntax_fixes import fix_quoted_column_access
    result,changes=fix_quoted_column_access("df.'col'\n")
    assert result.strip()=="df['col']" and len(changes)==1

class StubS3:
    def __init__(self):self.objects={}
    def put_object(self,**kwargs):self.objects[(kwargs['Bucket'],kwargs['Key'])]=kwargs['Body'];return {'ETag':'"test"'}
    def get_object(self,Bucket,Key):return {'Body':io.BytesIO(self.objects[(Bucket,Key)])}

class StubSts:
    def get_caller_identity(self):return {'Account':'123456789012','Arn':'arn:aws:iam::123456789012:user/demo'}

class StubGlue:
    class exceptions:
        class EntityNotFoundException(Exception):pass
    def __init__(self):self.jobs={};self.run_ids={}
    def get_job(self,JobName):
        if JobName not in self.jobs:raise self.exceptions.EntityNotFoundException()
        return {'Job':self.jobs[JobName]}
    def create_job(self,Name,**kwargs):self.jobs[Name]=kwargs;return {'Name':Name}
    def update_job(self,JobName,JobUpdate):self.jobs[JobName]=JobUpdate;return {'JobName':JobName}
    def start_job_run(self,JobName):
        assert JobName in self.jobs
        self.run_ids[JobName]='jr_123456789abc'
        return {'JobRunId':'jr_123456789abc'}
    def get_job_run(self,JobName,RunId,PredecessorsIncluded):
        assert self.run_ids[JobName]==RunId
        return {'JobRun':{'JobRunState':'SUCCEEDED'}}

class StubLogs:pass

def test_reference_cloud_sdk_payload_using_stubs(monkeypatch):
    fake_s3, fake_glue, fake_sts=StubS3(),StubGlue(),StubSts()
    monkeypatch.setattr(cloud,'clients',lambda profile,region:(fake_s3,fake_glue,fake_sts,StubLogs()))
    cfg={'profile':'ssis-glue-poc','region':'ap-southeast-2','bucket':'demo-bucket','prefix':'ssis-forge','glueRole':'DemoGlueRole'}
    result=cloud.deploy_reference(cfg,'A','deadbeef12345678',ROOT/'fixtures',ROOT/'glue'/'unified_job.py')
    assert result['status']=='AWS_JOB_CREATED_NOT_RUN'
    assert result['origin']=='INDEPENDENT_REFERENCE_NOT_SCT'
    assert result['jobName'].startswith('ssis-demo-a-')
    job=fake_glue.jobs[result['jobName']]
    assert job['Command']['Name']=='glueetl' and job['Command']['ScriptLocation'].startswith('s3://demo-bucket/')
    assert job['DefaultArguments']['--SCENARIO']=='A'
    assert job['DefaultArguments']['--AS_OF']=='2026-11-08'
    assert job['MaxRetries']==0
    assert any(key.endswith('/input/Employees.csv') for _,key in fake_s3.objects)
    assert any(key.endswith('/scripts/reference_glue_job.py') for _,key in fake_s3.objects)
    started=cloud.start(cfg,result['jobName'])
    assert started['status']=='SUBMITTED'
    checked=cloud.check(cfg,result['jobName'],started['runId'])
    assert checked['status']=='SUCCEEDED'

def test_actual_s3_output_row_reader_with_stubbed_parts(monkeypatch):
    class Paginator:
        def paginate(self,Bucket,Prefix):
            assert Bucket=='demo-bucket'
            return [{'Contents':[{'Key':Prefix+'part-00000.csv','Size':90},{'Key':Prefix+'_SUCCESS','Size':0}]}]
    class S3:
        def get_paginator(self,name):return Paginator()
        def get_object(self,Bucket,Key):return {'Body':io.BytesIO(b'EmployeeID,EmployeeName,Department,Salary,Bonus\n101,Asha,IT,50000.00,5000.00\n')}
    cfg={'bucket':'demo-bucket','prefix':'ssis-forge'}
    rows=cloud.list_output_rows(S3(),cfg,'s3://demo-bucket/ssis-forge/123/A/output','ActiveEmployees.csv')
    assert rows[0]['Bonus']=='5000.00' and len(rows)==1

def test_bedrock_payload_is_privacy_limited(site,monkeypatch):
    sid=cli.handle({'action':'new','scenario':'A'})['id']
    cli.handle({'action':'import','sessionId':sid,'contentBase64':sct_archive({'body.py':"x=frame.'id'\npassword='foo'\n"})})
    cli.handle({'action':'repair','sessionId':sid})
    prompts=[]
    class BedrockStub:
        def converse(self,**kwargs):
            prompts.append(kwargs['messages'][0]['content'][0]['text'])
            return {'output':{'message':{'content':[{'text':'{"recommendations":[]}'}]}},'usage':{'inputTokens':123,'outputTokens':13}}
    class SessionStub:
        def __init__(self,**kwargs):pass
        def client(self,service_name):return BedrockStub()
    class BotoStub:
        Session=SessionStub
    monkeypatch.setitem(sys.modules,'boto3',BotoStub())
    monkeypatch.setattr(cli,'clients',lambda profile,region:(None,None,None,None))
    res=cli.handle({'action':'bedrock','sessionId':sid,'approveModelCost':True,
       'approveMetadataTransmission':True,'profile':'ssis-glue-poc','region':'ap-southeast-2','modelId':'amazon.nova-lite-v1:0'})
    assert res['status']=='MODEL_RECOMMENDATIONS_REVIEW_ONLY'
    assert 'password' not in prompts[0] and 'foo' not in prompts[0]
    assert 'frame' not in prompts[0] and 'body.py' not in prompts[0]
    assert 'SCT_INVALID_QUOTED_COLUMN_ACCESS' in prompts[0]
