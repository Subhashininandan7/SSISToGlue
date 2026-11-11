"""Offline synthetic rename tests. The input baseline ZIP is genuine earlier
SCT CLI output; the _fixed variant here is SIMULATED, not a new SCT execution.
"""
import base64
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import cli, sct_candidate


def simulated_fixed_sct_zip(*, changed=False, mixed=False):
    base=ROOT/'evidence'/'ScenarioA_Unfixed_ActualSCT_Output.zip'
    old='a_employees_active_bonus'
    new='a_employees_active_bonus_fixed'
    stream=io.BytesIO()
    with zipfile.ZipFile(base) as original, zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as output:
        for name in original.namelist():
            if 'create-body-script/' not in name or not name.endswith('.py') or not original.getinfo(name).file_size:
                continue
            target_name=name.replace(old+'.',new+'.')
            if name.endswith('.'+old+'.py'):
                target_name=target_name.replace('.'+old+'.py','.'+new+'.py')
            if mixed and 'variables.py' in target_name:
                target_name=target_name.replace(new+'.','a_employees_active_bonus.')
            contents=original.read(name).decode('utf-8-sig')
            if name.endswith('.'+old+'.py'):
                contents=contents.replace('def '+old+'(connection: dict):','def '+new+'(connection: dict):')
            if 'filter_x0020' in name:
                contents=contents.replace(r'\expected\ActiveEmployees_SSIS.csv',r'\ssis-output\ActiveEmployees_SSIS.csv')
                if changed:
                    contents += '\n__import__("os").system("echo bad")\n'
            output.writestr(target_name,contents)
    return stream.getvalue()

@pytest.fixture
def new_fixed_session(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'HOME',tmp_path/'home')
    monkeypatch.setattr(cli,'FIXTURES',ROOT/'fixtures')
    sid=cli.new('A')['id']
    path=ROOT/'ssis-packages'/'A_Employees_Active_Bonus_FIXED.dtsx'
    cli.submit_source({'sessionId':sid,'fileName':path.name,
                       'contentBase64':base64.b64encode(path.read_bytes()).decode()})
    return sid


def setup_cli_conversion(sid,blob):
    p,s=cli.load(sid)
    cli.record_sct_output(p,s,blob,'REAL_SCT_BATCH_CLI')
    cli.store(p/'sct'/'auto-result.json',{'exitCode':0,'pythonModules':3,'method':'REAL_SCT_BATCH_CLI'})
    return p


def test_fixed_filename_sct_modules_can_prepare_without_rerun(new_fixed_session):
    sid=new_fixed_session
    folder=setup_cli_conversion(sid,simulated_fixed_sct_zip())
    result=cli.prepare_sct_candidate({'sessionId':sid})
    assert result['status']=='SCT_SCENARIO_A_PREFLIGHT_READY_NOT_RUN'
    assert result['sctGeneratedPackageStem']=='a_employees_active_bonus_fixed'
    assert result['uploadedSourceFileName']=='A_Employees_Active_Bonus_FIXED.dtsx'
    assert any(x['rule']=='NORMALIZE_CORRECTED_PACKAGE_COORDINATOR_NAME' for x in result['edits'])
    with zipfile.ZipFile(folder/'sct-candidate'/'sct_modules.zip') as z:
        assert 'a_employees_active_bonus.py' in z.namelist()
        assert 'a_employees_active_bonus_fixed.py' not in z.namelist()
        code=z.read('a_employees_active_bonus.py').decode('utf-8')
        assert 'def a_employees_active_bonus(connection: dict):' in code
        assert 'filter_x0020_active' in code
    assert result['checks']['orchestrationPreserved']
    assert result['gate']['readyForControlledGlueTest'] is False


def test_unrecognized_transformation_remains_blocked(new_fixed_session):
    sid=new_fixed_session
    setup_cli_conversion(sid,simulated_fixed_sct_zip(changed=True))
    with pytest.raises(sct_candidate.CandidateBlocked,match='Unexpected SCT-generated AST'):
        cli.prepare_sct_candidate({'sessionId':sid})


def test_mixed_package_script_names_remain_blocked(new_fixed_session):
    sid=new_fixed_session
    setup_cli_conversion(sid,simulated_fixed_sct_zip(mixed=True))
    with pytest.raises(sct_candidate.CandidateBlocked,match='Mixed SCT package stems'):
        cli.prepare_sct_candidate({'sessionId':sid})


def test_sct_filename_mismatch_does_not_permit_arbitrary_package(new_fixed_session):
    sid=new_fixed_session
    p=setup_cli_conversion(sid,simulated_fixed_sct_zip())
    state=cli.load(sid)[1]
    state['originalFileName']='UnrelatedPackage.dtsx'
    cli.save(p,state)
    with pytest.raises(sct_candidate.CandidateBlocked,match='Unsupported Scenario A filename'):
        cli.prepare_sct_candidate({'sessionId':sid})


def test_latest_session_restores_existing_work_without_new_conversion(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'HOME',tmp_path/'home')
    assert cli.handle({'action':'latest-session'})['status']=='NO_PREVIOUS_SESSION'
    sid=cli.new('A')['id']
    p=cli.session_path(sid)
    s=cli.load(sid)[1]
    s['conversion']='SCT_BATCH_CLI_ARTIFACTS_OBSERVED_REVIEW_ONLY'
    cli.save(p,s)
    recovered=cli.handle({'action':'latest-session'})
    assert recovered['id']==sid
    assert recovered['conversion']=='SCT_BATCH_CLI_ARTIFACTS_OBSERVED_REVIEW_ONLY'
    assert list((tmp_path/'home'/'sessions').iterdir())==[p]
