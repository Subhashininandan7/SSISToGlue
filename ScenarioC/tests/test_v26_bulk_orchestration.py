import base64
import json
import os
from pathlib import Path
import pytest
import cli
import bulk

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'HOME',tmp_path)
    return tmp_path

def payload(path):return base64.b64encode(Path(path).read_bytes()).decode()

def package(name='A_Employees_Active_Bonus_FIXED.dtsx'):
    return ROOT/'ssis-packages'/name

def setup_portfolio():
    x=cli.handle({'action':'bulk-create'})
    for name in ('A_Employees_Active_Bonus_FIXED.dtsx','B_CSV_Customer_Order_Join_REPAIRED_V2.dtsx'):
        cli.handle({'action':'bulk-add','portfolioId':x['id'],'fileName':name,'contentBase64':payload(package(name))})
    return x['id']

def test_two_real_packages_create_separate_sessions(isolated):
    pid=setup_portfolio()
    result=cli.handle({'action':'bulk-status','portfolioId':pid})
    assert len(result['packages'])==2
    assert len({e['sessionId'] for e in result['packages']})==2
    for e in result['packages']:
        assert (cli.session_path(e['sessionId'])/'source'/'original.dtsx').read_bytes()==package(e['name']).read_bytes()
        assert e['sha256']

def test_duplicate_and_invalid_rejected(isolated):
    pid=setup_portfolio()
    with pytest.raises(ValueError,match='Duplicate'):
        cli.handle({'action':'bulk-add','portfolioId':pid,'fileName':'A_Employees_Active_Bonus_FIXED.dtsx','contentBase64':payload(package())})
    with pytest.raises(ValueError,match='Invalid portfolio'):
        cli.handle({'action':'bulk-status','portfolioId':'../escape'})

def test_missing_dependency_stops_deploy(isolated,monkeypatch):
    pid=setup_portfolio();path=bulk._path(cli,pid);plan=bulk._read(cli,pid)
    plan['packages'][1]['dependencies']=['Unuploaded.dtsx'];bulk._save(cli,path,plan)
    with pytest.raises(ValueError,match='Unresolved upstream'):
        cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':plan['packages'][1]['name'],'operation':'deploy','approvePortfolioDeployment':True})

def test_cycle_detection(isolated):
    pid=setup_portfolio();path=bulk._path(cli,pid);plan=bulk._read(cli,pid)
    plan['packages'][0]['dependencies']=[plan['packages'][1]['name']]
    plan['packages'][1]['dependencies']=[plan['packages'][0]['name']]
    bulk._save(cli,path,plan)
    with pytest.raises(ValueError,match='Cyclic'):
        cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':plan['packages'][0]['name'],'operation':'analyze'})

def test_deployment_requires_approval_and_does_not_call_cloud(isolated,monkeypatch):
    pid=setup_portfolio();name=bulk._read(cli,pid)['packages'][0]['name']
    monkeypatch.setattr(cli,'quick_deploy',lambda req:pytest.fail('Cloud must not be invoked'))
    with pytest.raises(ValueError,match='Explicit approval'):
        cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':name,'operation':'deploy'})

def test_run_prevents_duplicates(isolated,monkeypatch):
    pid=setup_portfolio();p=bulk._path(cli,pid);plan=bulk._read(cli,pid)
    e=plan['packages'][0]
    # Store genuine-style local state, no cloud invocation.
    q=cli.session_path(e['sessionId'])/'quick';q.mkdir(exist_ok=True)
    (q/'status.json').write_text(json.dumps({'status':'SUCCEEDED','origin':'REAL_AWS_GLUE'}))
    monkeypatch.setattr(cli,'quick_run',lambda req:pytest.fail('Must never start duplicate job'))
    with pytest.raises(ValueError,match='Existing Glue run'):
        cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':e['name'],'operation':'run','approvePortfolioExecution':True})

def test_batch_analyze_reuses_existing_engine(isolated,monkeypatch):
    pid=setup_portfolio();name=bulk._read(cli,pid)['packages'][0]['name']
    calls=[]
    def fake(req):
        calls.append(req['sessionId'])
        return {'blockers':[],'outputs':['ActiveEmployees.csv'],'origin':'SCT_CLI'}
    monkeypatch.setattr(cli,'quick_analyze',fake)
    r=cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':name,'operation':'analyze'})
    assert r['state']=='READY_FOR_DEPLOYMENT'
    assert calls==[r['sessionId']]

def test_ai_requires_explicit_model_consent(isolated,monkeypatch):
    pid=setup_portfolio();name=bulk._read(cli,pid)['packages'][0]['name']
    def fake(req):
        assert req['approveModelCost'] is False
        assert req['approveCodeTransmission'] is False
        raise ValueError('Consent required')
    monkeypatch.setattr(cli,'quick_ai',fake)
    with pytest.raises(ValueError,match='Consent required'):
        cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':name,'operation':'ai-propose'})

def test_baseline_required_for_validation(isolated):
    pid=setup_portfolio();name=bulk._read(cli,pid)['packages'][0]['name']
    with pytest.raises(ValueError,match='independent baseline'):
        cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':name,'operation':'validate','outputName':'x.csv'})

def test_status_recovery(isolated):
    pid=setup_portfolio();assert cli.handle({'action':'bulk-latest'})['id']==pid

def test_xml_parsing_does_not_imply_success(isolated):
    pid=setup_portfolio();result=cli.handle({'action':'bulk-status','portfolioId':pid})
    assert all(e['state']=='UPLOADED' for e in result['packages'])
    assert not any(e.get('glueStatus')=='SUCCEEDED' for e in result['packages'])

def test_bulk_deployment_never_uses_demo_fixture_as_hidden_fallback(isolated,monkeypatch):
    pid=setup_portfolio();e=bulk._read(cli,pid)['packages'][0]
    q=cli.session_path(e['sessionId'])/'quick';q.mkdir(exist_ok=True)
    (q/'report.json').write_text(json.dumps({'blockers':[],'inputs':['Employees.csv'],'outputs':['ActiveEmployees.csv']}))
    monkeypatch.setattr(cli,'quick_deploy',lambda req:pytest.fail('Must not deploy demo fixture'))
    with pytest.raises(ValueError,match='Missing required source files from selected folder'):
        cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':e['name'],
                    'operation':'deploy','approvePortfolioDeployment':True})

def test_attach_csv_to_selected_session(isolated):
    pid=setup_portfolio();e=bulk._read(cli,pid)['packages'][0]
    source=ROOT/'fixtures'/'input'/'Employees.csv'
    r=cli.handle({'action':'bulk-input','portfolioId':pid,'packageName':e['name'],
         'fileName':'Employees.csv','contentBase64':payload(source)})
    assert r['status']=='INPUT_CSV_UPLOADED'
    assert (cli.session_path(e['sessionId'])/'inputs'/'Employees.csv').read_bytes()==source.read_bytes()

def test_upstream_job_must_succeed_before_downstream_run(isolated,monkeypatch):
    pid=setup_portfolio();p=bulk._path(cli,pid);plan=bulk._read(cli,pid)
    downstream,upstream=plan['packages'][1],plan['packages'][0]
    downstream['dependencies']=[upstream['name']];bulk._save(cli,p,plan)
    monkeypatch.setattr(cli,'quick_run',lambda req:pytest.fail('Must not start downstream job'))
    with pytest.raises(ValueError,match='Upstream package must succeed'):
        cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':downstream['name'],
                    'operation':'run','approvePortfolioExecution':True})
