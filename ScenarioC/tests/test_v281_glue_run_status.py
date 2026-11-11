"""Regression: a persisted Glue submission must be pollable, never rerun."""
import json
import pytest
import cli
import bulk
from test_v26_bulk_orchestration import setup_portfolio

@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, 'HOME', tmp_path)
    return tmp_path

def recorded(isolated):
    pid=setup_portfolio()
    name=bulk._read(cli,pid)['packages'][0]['name']
    e=bulk._read(cli,pid)['packages'][0]
    q=cli.session_path(e['sessionId'])/'quick';q.mkdir(exist_ok=True)
    submission={'status':'SUBMITTED','jobName':'ssis-auto-0123456789abcdef',
                'runId':'jr_real_submission','origin':'REAL_AWS_GLUE'}
    (q/'run.json').write_text(json.dumps(submission))
    return pid,name,q

def test_submitted_job_is_visible_and_pollable(isolated, monkeypatch):
    pid,name,q=recorded(isolated)
    p=cli.handle({'action':'bulk-status','portfolioId':pid})['packages'][0]
    assert p['glueStatus']=='SUBMITTED' and p['runId']=='jr_real_submission'
    assert p['jobName']=='ssis-auto-0123456789abcdef'
    monkeypatch.setattr(cli,'quick_poll',lambda req: {
        'status':'SUCCEEDED','jobName':'ssis-auto-0123456789abcdef',
        'runId':'jr_real_submission','origin':'REAL_AWS_GLUE'})
    r=cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':name,'operation':'poll'})
    assert r['state']=='GLUE_SUCCEEDED'
    assert r['result']['status']=='SUCCEEDED'

def test_already_submitted_run_never_restarts(isolated, monkeypatch):
    pid,name,q=recorded(isolated)
    monkeypatch.setattr(cli,'quick_run',lambda req:pytest.fail('Duplicate AWS job!'))
    with pytest.raises(ValueError,match='Existing Glue run'):
        cli.handle({'action':'bulk-step','portfolioId':pid,'packageName':name,
                    'operation':'run','approvePortfolioExecution':True})

def test_poll_status_overrides_submission_only_when_same_run(isolated):
    pid,name,q=recorded(isolated)
    (q/'status.json').write_text(json.dumps({'status':'RUNNING','runId':'jr_real_submission',
        'jobName':'ssis-auto-0123456789abcdef'}))
    p=cli.handle({'action':'bulk-status','portfolioId':pid})['packages'][0]
    assert p['glueStatus']=='RUNNING'
    (q/'status.json').write_text(json.dumps({'status':'SUCCEEDED','runId':'jr_wrong',
        'jobName':'ssis-auto-0123456789abcdef'}))
    p=cli.handle({'action':'bulk-status','portfolioId':pid})['packages'][0]
    assert p['glueStatus']=='SUBMITTED'

def test_no_submitted_file_means_no_fake_run(isolated):
    pid=setup_portfolio()
    for p in cli.handle({'action':'bulk-status','portfolioId':pid})['packages']:
        assert not p.get('runId')
        assert not p.get('glueStatus')
