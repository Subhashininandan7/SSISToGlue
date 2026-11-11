"""Check authentic assessment is requested, with no simulated report fallback."""
from pathlib import Path
from sct_auto import create_scenario

def test_sct_report_commands_are_real_batch_instructions():
    script=create_scenario('Example','D:\\source','D:\\project','D:\\output','D:\\reports')
    assert 'CreateReport' in script
    assert 'SaveReportPDF' in script and 'SSIS_Assessment_Report.pdf' in script
    assert 'SaveReportCSV' in script
    assert script.index('CreateReport') < script.index('Convert')

def test_sct_links_only_in_package_results_after_conversion_and_generic_validation_visible():
    root=Path(__file__).resolve().parents[1]
    html=(root/'DemoWeb/wwwroot/index.html').read_text()
    js=(root/'DemoWeb/wwwroot/unified.js').read_text()
    assert 'SCT logs, original output and genuine assessment reports appear' in html
    assert "if(p.sctCompleted)" in js
    assert "['sct-assessment','SCT assessment']" in js
    assert 'id="validate"' in html
    assert "'validate'" in js
    assert 'id="type-preview"' not in html
    assert 'id="type-apply"' not in html

def test_completed_sct_run_retains_only_real_report_files(tmp_path,monkeypatch):
    import sys,zipfile,io,json
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
    import cli
    monkeypatch.setattr(cli,'HOME',tmp_path)
    session=cli.new('CUSTOM')
    p=tmp_path/'sessions'/session['id']
    source=p/'source'/'original.dtsx';source.parent.mkdir(exist_ok=True)
    source.write_text('<stub/>')
    session['sourcePackage']='UPLOADED_UNVERIFIED_SSIS_RUNTIME'
    session['originalFileName']='sample.dtsx';cli.save(p,session)
    work=tmp_path/'genuine_sct_work';(work/'reports').mkdir(parents=True)
    (work/'sct.log').write_text('SCT Batch 1.0 CreateReport SaveReportPDF SaveReportCSV')
    (work/'reports'/'SSIS_Assessment_Report.pdf').write_bytes(b'%PDF-1.4\n% only fake bytes for unit test\n')
    (work/'reports'/'SCT_Report.csv').write_bytes(b'Object,Status\nA,Converted\n')
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:z.writestr('Amazon Glue/sample.py', 'print(1)\n')
    monkeypatch.setattr(cli.sct_auto,'discover_runner',lambda:{'available':True,'runner':'C:/fake/RunSCTBatch.cmd'})
    monkeypatch.setattr(cli.sct_auto,'convert',lambda *a,**kw:{
        'workDirectory':str(work),'archive':archive.getvalue(),'scenario':'CreateReport',
        'method':'REAL_SCT_BATCH_CLI','status':'CLI_OUTPUT_OBSERVED_UNVERIFIED_RUNTIME',
        'exitCode':0,'pythonModules':1,'outputBytes':len(archive.getvalue()),'logTail':'SCT Batch',
        'warnings':[],'sourceFilename':'sample.dtsx'})
    converted=cli.auto_convert({'sessionId':session['id']})
    assert converted['assessment']['status']=='REAL_SCT_REPORT_AVAILABLE'
    assert converted['importedScripts']==1
    with zipfile.ZipFile(p/'sct'/'assessment-original.zip') as z:
        assert z.read('SCT_Report.csv')==b'Object,Status\nA,Converted\n'
    assert (p/'sct'/'assessment-original.pdf').read_bytes().startswith(b'%PDF')
    loaded=cli.quick_conversion_status({'sessionId':session['id']})
    assert loaded['completed'] and len(loaded['assessment']['files'])==2


def test_sct_without_reports_does_not_fake_assessment(tmp_path,monkeypatch):
    import sys,zipfile,io
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
    import cli
    monkeypatch.setattr(cli,'HOME',tmp_path)
    session=cli.new('CUSTOM');p=tmp_path/'sessions'/session['id']
    (p/'source').mkdir();(p/'source'/'original.dtsx').write_text('<stub/>')
    session['sourcePackage']='UPLOADED_UNVERIFIED_SSIS_RUNTIME';cli.save(p,session)
    work=tmp_path/'run';work.mkdir();(work/'sct.log').write_text('No assessment produced')
    archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w') as z:z.writestr('example.py','print(1)\n')
    monkeypatch.setattr(cli.sct_auto,'discover_runner',lambda:{'available':True,'runner':'fake'})
    monkeypatch.setattr(cli.sct_auto,'convert',lambda *a,**kw:{'workDirectory':str(work),'archive':archive.getvalue(),
      'scenario':'CreateReport','method':'REAL_SCT_BATCH_CLI','status':'CLI_OUTPUT_OBSERVED_UNVERIFIED_RUNTIME',
      'exitCode':0,'pythonModules':1,'outputBytes':len(archive.getvalue()),'logTail':'no report','warnings':[]})
    r=cli.auto_convert({'sessionId':session['id']})
    assert r['assessment']['status']=='NOT_GENERATED_BY_SCT'
    assert not (p/'sct'/'assessment-original.zip').exists()
