"""Completed A/B evidence must survive a bulk AI failure while C remains new."""
import base64
import json
from pathlib import Path
import cli
import bulk
import pytest
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def saved(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'HOME',tmp_path)
    pid=cli.handle({'action':'bulk-create'})['id']
    for n in ('A_Employees_Active_Bonus_FIXED.dtsx','B_CSV_Customer_Order_Join_REPAIRED_V2.dtsx'):
        data=(ROOT/'ssis-packages'/n).read_bytes()
        cli.handle({'action':'bulk-add','portfolioId':pid,'fileName':n,'contentBase64':base64.b64encode(data).decode()})
    plan=bulk._read(cli,pid)
    a,b=plan['packages']
    a['state']='ERROR_AI_ACCEPT'
    a['lastError']='AI changed statements beyond missing join'
    a['outputs']=['ActiveEmployees_SSIS.csv']
    a['validation']={'ActiveEmployees_SSIS.csv':{'status':'MATCH','verified':True}}
    b['state']='OUTPUTS_MATCH'
    b['outputs']=['ValidOrders_SSIS.csv','RejectedOrders_SSIS.csv']
    b['validation']={n:{'status':'MATCH','verified':True} for n in b['outputs']}
    for entry in (a,b):
        q=cli.session_path(entry['sessionId'])/'quick';q.mkdir(exist_ok=True)
        (q/'run.json').write_text(json.dumps({'origin':'REAL_AWS_GLUE','jobName':'job-'+entry['name'],'runId':'jr-'+entry['name'],'status':'SUBMITTED'}))
        (q/'status.json').write_text(json.dumps({'jobName':'job-'+entry['name'],'runId':'jr-'+entry['name'],'status':'SUCCEEDED'}))
    bulk._save(cli,bulk._path(cli,pid),plan)
    return pid

def test_status_recovers_previous_verified_result(saved):
    result=cli.handle({'action':'bulk-status','portfolioId':saved})
    assert [e['state'] for e in result['packages']]==['OUTPUTS_MATCH','OUTPUTS_MATCH']
    assert result['packages'][0]['lastError']  # preserve audit evidence

def test_ai_accept_skips_completed_package(saved,monkeypatch):
    monkeypatch.setattr(cli,'quick_accept',lambda *_:pytest.fail('Must not run AI on completed package'))
    name=bulk._read(cli,saved)['packages'][0]['name']
    result=cli.handle({'action':'bulk-step','portfolioId':saved,'packageName':name,'operation':'ai-accept'})
    assert result['state']=='OUTPUTS_MATCH'
    assert result['result']['status']=='SKIPPED_ALREADY_COMPLETED'

def test_unverified_success_is_not_called_parity(saved):
    p=bulk._read(cli,saved)
    p['packages'][0]['validation']={}
    bulk._save(cli,bulk._path(cli,saved),p)
    result=cli.handle({'action':'bulk-status','portfolioId':saved})
    assert result['packages'][0]['state']=='GLUE_SUCCEEDED'
    assert result['packages'][0]['state']!='OUTPUTS_MATCH'
