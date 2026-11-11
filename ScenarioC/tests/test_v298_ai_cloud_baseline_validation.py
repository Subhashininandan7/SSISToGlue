"""Scenario C uses inspected cloud output; A/B stays on SCT validator."""
import base64
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import bulk,cli,process_glue
import test_v295_process_glue as fixture
from unsupported_process_ai import read_json


def create_cloud(tmp_path,monkeypatch,rows=b'EmployeeID,Status\n101,Active\n'):
    old=cli.HOME;cli.HOME=tmp_path/'data'
    pid=bulk.create(cli,{})['id'];name='C_Unsupported_Execute_Process_AI_Demo.dtsx'
    bulk.add(cli,{'portfolioId':pid,'fileName':name,'contentBase64':base64.b64encode((fixture.FIX/name).read_bytes()).decode()})
    entry=bulk.status(cli,{'portfolioId':pid})['packages'][0]
    ai=cli.session_path(entry['sessionId'])/'process-ai'
    fixture.setup(ai)
    plan=bulk._read(cli,pid)
    plan['packages'][0].update(processAIKind='EXECUTE_PROCESS_25029',state='LOCAL_OUTPUT_GENERATED',blockers=['SCT 25029'])
    bulk._save(cli,bulk._path(cli,pid),plan)
    s3,glue,sts,logs=fixture.S3(),fixture.Glue(),fixture.STS(),fixture.Logs()
    clients=lambda *a:(s3,glue,sts,logs)
    monkeypatch.setattr(process_glue.cloud,'clients',clients)
    def action(op,**kw):
        return bulk.step(cli,{'portfolioId':pid,'packageName':name,'operation':op,**fixture.CFG,**kw})
    action('aws');action('deploy',approvePortfolioDeployment=True);action('run',approvePortfolioExecution=True)
    s3.files[f'demo-outputs/{entry["sessionId"]}/approved-ai/output/ActiveEmployees.csv/part-0000.csv']=rows
    action('poll')
    return old,pid,name,ai,s3,action


def test_ai_output_is_registered_and_trusted_baseline_matches(tmp_path,monkeypatch):
    old,pid,name,ai,s3,action=create_cloud(tmp_path,monkeypatch)
    try:
        state=bulk.status(cli,{'portfolioId':pid})['packages'][0]
        assert state['outputs']==['ActiveEmployees.csv']
        assert state['state']=='GLUE_OUTPUT_GENERATED'
        ref=base64.b64encode(b'Status,EmployeeID\nActive,101\n').decode()
        res=action('validate',outputName='ActiveEmployees.csv',contentBase64=ref)
        assert res['result']['status']=='MATCH'
        assert res['state']=='OUTPUTS_MATCH'
        proof=read_json(ai/'cloud-validation.json')
        assert proof['jobName']==state['jobName']
        assert proof['runId']==state['runId']
        again=bulk.status(cli,{'portfolioId':pid})['packages'][0]
        assert again['state']=='OUTPUTS_MATCH'
        assert again['validation']['ActiveEmployees.csv']['verified'] is True
    finally:cli.HOME=old


def test_missing_baseline_never_claims_match(tmp_path,monkeypatch):
    old,pid,name,ai,s3,action=create_cloud(tmp_path,monkeypatch)
    try:
        with pytest.raises(ValueError,match='independent baseline'):
            action('validate',outputName='ActiveEmployees.csv')
        state=bulk.status(cli,{'portfolioId':pid})['packages'][0]
        assert state['state']!='OUTPUTS_MATCH'
    finally:cli.HOME=old


def test_wrong_name_and_mismatch_fail_closed(tmp_path,monkeypatch):
    old,pid,name,ai,s3,action=create_cloud(tmp_path,monkeypatch)
    try:
        ref=base64.b64encode(b'EmployeeID,Status\n999,Active\n').decode()
        with pytest.raises(Exception,match='not declared'):
            action('validate',outputName='Unknown.csv',contentBase64=ref)
        result=action('validate',outputName='ActiveEmployees.csv',contentBase64=ref)
        assert result['result']['status']=='DATA_MISMATCH'
        assert result['state']!='OUTPUTS_MATCH'
    finally:cli.HOME=old


def test_cloud_identity_or_code_mismatch_fails_closed(tmp_path,monkeypatch):
    old,pid,name,ai,s3,action=create_cloud(tmp_path,monkeypatch)
    try:
        proof=read_json(ai/'cloud-status.json')
        proof['runId']='jr_changed'
        (ai/'cloud-status.json').write_text(json.dumps(proof),encoding='utf-8')
        with pytest.raises(Exception,match='different Glue job/run'):
            action('validate',outputName='ActiveEmployees.csv',contentBase64=base64.b64encode(b'EmployeeID,Status\n101,Active\n').decode())
    finally:cli.HOME=old


def test_single_existing_validation_button_discovers_ai_output():
    js=(ROOT/'DemoWeb/wwwroot/unified.js').read_text(encoding='utf-8')
    assert "(p.cloudOutputs||[]).map(x=>x?.output)" in js
    assert "'validate'" in js
    assert "No inspected CSV outputs" in js
    html=(ROOT/'DemoWeb/wwwroot/index.html').read_text(encoding='utf-8')
    assert html.count('id="validate"')==1
