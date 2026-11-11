"""Offline regression tests for one-click SCT conversion, no AWS/Windows mocks presented to users."""
from __future__ import annotations
import base64
import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import cli, sct_auto


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(cli,'HOME',tmp_path)
    return tmp_path


def runner_file(tmp_path):
    app=tmp_path/'app'
    app.mkdir(parents=True)
    (app/'RunSCTBatch.cmd').write_text('@echo off\n',encoding='ascii')
    (app/'AWSSchemaConversionToolBatch.jar').write_bytes(b'fixture for discovery, not the real SCT engine')
    return app/'RunSCTBatch.cmd'


def test_runner_discovery_is_automatic_and_checks_batch_jar(tmp_path):
    runner=runner_file(tmp_path)
    d=sct_auto.discover_runner(environ={'SCT_BATCH_CMD':str(runner)},platform='win32')
    assert d['available'] is True and d['jarFound'] is True
    assert d['cliSupport']=='SSIS_TO_GLUE_UNVERIFIED_UNTIL_REAL_ARTIFACTS'
    (runner.parent/'AWSSchemaConversionToolBatch.jar').unlink()
    assert not sct_auto.discover_runner(environ={'SCT_BATCH_CMD':str(runner)},platform='win32')['available']
    assert not sct_auto.discover_runner(environ={},platform='linux')['available']


def test_auto_generated_scts_matches_original_studio_conversion_template(tmp_path):
    text=sct_auto.create_scenario('Forge_demo',tmp_path/'input',tmp_path/'project',tmp_path/'output',tmp_path/'reports')
    for command in ['CreateProject','AddSource','AddServerMapping','CreateReport','SaveReportPDF',
                    'SaveReportCSV','Convert','SaveToLocalFolder','SaveProject']:
        assert command in text
    assert "-vendor: 'SSIS'" in text and "-host: '" in text
    assert "ETL.<Glue (virtual)>.Package scripts" in text
    assert '--pathtoscts' not in text  # runtime supplies script path, not in scenario
    assert 'specify driver' not in text
    with pytest.raises(ValueError,match='unsupported'):
        sct_auto.create_scenario('bad\'name',tmp_path,tmp_path,tmp_path,tmp_path)


def test_auto_conversion_ingests_only_real_generated_code(tmp_path):
    runner=runner_file(tmp_path)
    ssis=tmp_path/'uploaded.dtsx';ssis.write_text('<not-a-claim-of-ssis-execution/>')
    calls=[]
    def fake_batch(script,batch,log,timeout_seconds):
        assert script.read_text().find("-vendor: 'SSIS'")!=-1
        assert script.parent.joinpath('input','employees.dtsx').exists()
        calls.append(script)
        # TEST RUNNER: creates a fixture only; production uses the actual SCT executable.
        output=script.parent/'output'/'Amazon Glue-2026'/'0. create-body-script'
        output.mkdir(parents=True)
        (output/'big package.x.py').write_text('print(123)\n')
        (output/'empty.py').touch()
        log.write_text('CreateProject finished\nConvert finished\nSaveToLocalFolder finished\n')
        return 0
    got=sct_auto.convert(ssis,'employees.dtsx','1234567890abcdef',runner,
                         platform='win32',stage_root=tmp_path/'stage',runner_fn=fake_batch)
    assert len(calls)==1
    assert got['method']=='REAL_SCT_BATCH_CLI'
    assert got['status']=='CLI_OUTPUT_OBSERVED_UNVERIFIED_RUNTIME'
    assert got['exitCode']==0 and got['pythonModules']==1
    with zipfile.ZipFile(io.BytesIO(got['archive'])) as z:
        assert z.read('Amazon Glue-2026/0. create-body-script/big package.x.py')==b'print(123)\n'
    assert 'SaveProject' in got['scenario']


def test_zero_exit_without_files_is_not_conversion_success(tmp_path):
    runner=runner_file(tmp_path)
    ssis=tmp_path/'uploaded.dtsx';ssis.write_bytes(b'fake test fixture')
    def empty_batch(script,runner,log,timeout_seconds):
        log.write_text('A zero exit code but no code generated')
        return 0
    res=sct_auto.convert(ssis,'employees.dtsx','1234567890abcdef',runner,platform='win32',
                         stage_root=tmp_path/'stage',runner_fn=empty_batch)
    assert res['archive'] is None and res['status']=='CLI_EXIT_ZERO_NO_PYTHON_OUTPUT_GUI_IMPORT_REQUIRED'
    assert res['pythonModules']==0


def test_failed_cli_with_real_artifacts_still_is_review_only(tmp_path):
    runner=runner_file(tmp_path)
    ssis=tmp_path/'uploaded.dtsx';ssis.write_bytes(b'fake test fixture')
    def conversion_with_errors(script,runner,log,timeout_seconds):
        output=script.parent/'output';output.mkdir(exist_ok=True)
        (output/'partial.py').write_text('x = 7\n')
        log.write_text('SCT ERROR: unresolved connection manager')
        return 1
    res=sct_auto.convert(ssis,'employees.dtsx','1234567890abcdef',runner,platform='win32',
                         stage_root=tmp_path/'stage',runner_fn=conversion_with_errors)
    assert res['pythonModules']==1
    assert res['status']=='CLI_OUTPUT_WITH_ERRORS_REVIEW_ONLY'
    assert res['exitCode']==1


def test_auto_convert_unavailable_honestly_returns_gui_fallback(site, monkeypatch):
    sid=cli.handle({'action':'new','scenario':'A'})['id']
    src=ROOT/'ssis-packages'/'A_Employees_Active_Bonus.dtsx'
    req={'action':'source','sessionId':sid,'fileName':src.name,'contentBase64':base64.b64encode(src.read_bytes()).decode()}
    cli.handle(req)
    monkeypatch.setattr(cli.sct_auto,'discover_runner',lambda:{'available':False,'reason':'No SCT installation'})
    res=cli.handle({'action':'convert-auto','sessionId':sid})
    assert res['status']=='SCT_CLI_UNAVAILABLE_GUI_IMPORT_AVAILABLE'
    assert res['method']=='NONE'
    assert not (cli.session_path(sid)/'sct'/'manifest.json').exists()
    assert cli.handle({'action':'session','sessionId':sid})['sourcePackage']=='UPLOADED_UNVERIFIED_SSIS_RUNTIME'


def test_auto_convert_success_preserves_cli_provenance_and_oneclick_repair(site, monkeypatch, tmp_path):
    sid=cli.handle({'action':'new','scenario':'A'})['id']
    sample=ROOT/'ssis-packages'/'A_Employees_Active_Bonus.dtsx'
    cli.handle({'action':'source','sessionId':sid,'fileName':sample.name,
                'contentBase64':base64.b64encode(sample.read_bytes()).decode()})
    runner=runner_file(tmp_path)
    monkeypatch.setattr(cli.sct_auto,'discover_runner',lambda:{'available':True,'runner':str(runner),'reason':'Found'})
    def run(source_file,source_name,session_id,runner_path):
        assert source_name==sample.name
        assert Path(source_file).is_file()
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w') as z:z.writestr('0. create-body-script/sample.py',"df.'EmployeeID'\n")
        stage=tmp_path/'stage';stage.mkdir()
        (stage/'sct.log').write_text('Authentic SCT log for unit-test stub')
        return {'method':'REAL_SCT_BATCH_CLI','status':'CLI_OUTPUT_OBSERVED_UNVERIFIED_RUNTIME',
                'exitCode':0,'pythonModules':1,'outputBytes':len(b.getvalue()),
                'logTail':'Convert finished','archive':b.getvalue(),'scenario':'CreateProject\n/\n',
                'workDirectory':str(stage),'warnings':[],'sourceFilename':source_name}
    monkeypatch.setattr(cli.sct_auto,'convert',run)
    res=cli.handle({'action':'convert-auto','sessionId':sid})
    assert res['status']=='CLI_ARTIFACTS_IMPORTED_FOR_REVIEW'
    assert res['importedScripts']==1
    p=cli.session_path(sid)
    assert (p/'sct'/'auto-scenario.scts').is_file()
    assert 'unit-test stub' in (p/'sct'/'auto-sct.log').read_text()
    assert json.loads((p/'sct'/'manifest.json').read_text())[0]['provenance']=='REAL_SCT_BATCH_CLI'
    assert (p/'sct'/'original-conversion-output.zip').exists()
    assert cli.handle({'action':'session','sessionId':sid})['conversionMethod']=='REAL_SCT_BATCH_CLI'
    reviewed=cli.handle({'action':'repair','sessionId':sid})
    assert reviewed['modules'][0]['syntaxPass']
    assert reviewed['runtimeReady'] is False


def test_gui_import_cannot_masquerade_as_cli(site):
    sid=cli.handle({'action':'new','scenario':'B'})['id']
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:z.writestr('generated.py','print(1)\n')
    res=cli.handle({'action':'import','sessionId':sid,'contentBase64':base64.b64encode(b.getvalue()).decode()})
    assert res['method']=='SCT_GUI_OUTPUT_IMPORT'
    s=cli.handle({'action':'session','sessionId':sid})
    assert s['conversionMethod']=='SCT_GUI_OUTPUT_IMPORT'
    assert 'GUI' in s['conversion']
    assert 'CLI_' not in s['conversion']


def test_ui_has_one_conversion_step_for_one_or_many_packages():
    html=(ROOT/'DemoWeb/wwwroot/index.html').read_text()
    js=(ROOT/'DemoWeb/wwwroot/unified.js').read_text()
    assert '<button id="convert" class="primary">Convert all packages</button>' in html
    assert 'id="source-folder" type="file" webkitdirectory directory multiple' in html
    assert 'id="scts"' not in html and 'id="batch"' not in html
    assert "'bulk-step'" in js and "'convert'" in js
    assert 'SCT' in html
    assert '"sct-cli-output"' in (ROOT/'DemoWeb/Program.cs').read_text()
