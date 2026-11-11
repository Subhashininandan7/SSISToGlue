"""Real package metadata, source-only discovery, provenance and session-resume tests."""
import base64
import hashlib
from pathlib import Path
import pytest
import cli
import bulk
ROOT=Path(__file__).resolve().parents[1]

def encoded(path): return base64.b64encode(path.read_bytes()).decode()

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'HOME',tmp_path)
    return tmp_path

def test_sources_are_inferred_from_actual_component_references():
    a=ROOT/'ssis-packages'/'A_Employees_Active_Bonus_FIXED.dtsx'
    b=ROOT/'ssis-packages'/'B_CSV_Customer_Order_Join_REPAIRED_V2.dtsx'
    refs,_=bulk._input_references(a.read_bytes())
    assert [r['name'] for r in refs]==['Employees.csv']
    assert 'ActiveEmployees' not in str(refs)
    refs,_=bulk._input_references(b.read_bytes())
    assert {r['name'] for r in refs}=={'Orders.csv','Customers.csv'}
    assert 'ValidOrders_SSIS.csv' not in str(refs)

def test_source_folder_discovery_stages_exact_inputs_and_reuses_session(isolated):
    p=cli.handle({'action':'bulk-create'});pid=p['id']
    ssis=ROOT/'ssis-packages'/'B_CSV_Customer_Order_Join_REPAIRED_V2.dtsx'
    req={'action':'bulk-add','portfolioId':pid,'fileName':ssis.name,
         'relativePath':'BulkRoot/ssis/'+ssis.name,'contentBase64':encoded(ssis)}
    result=cli.handle(req)
    assert result['relativePath'].startswith('BulkRoot/')
    assert {r['name'] for r in result['inputReferences']}=={'Orders.csv','Customers.csv'}
    sid=result['sessionId']
    for name in ('Orders.csv','Customers.csv'):
        f=ROOT/'fixtures'/'input'/name
        response=cli.handle({'action':'bulk-input','portfolioId':pid,
           'packageName':ssis.name,'fileName':name,
           'relativePath':'BulkRoot/fixtures/input/'+name,
           'resolutionMethod':'ORIGINAL_PATH_SUFFIX','contentBase64':encoded(f)})
        assert response['source']=='SELECTED_FOLDER'
        assert response['sha256']==hashlib.sha256(f.read_bytes()).hexdigest()
        assert (cli.session_path(sid)/'inputs'/name).read_bytes()==f.read_bytes()
    again=cli.handle({**req,'reuseMatching':True})
    assert again['reused'] is True and again['sessionId']==sid
    status=cli.handle({'action':'bulk-status','portfolioId':pid})
    assert status['packages'][0]['inputResolution']['Orders.csv']['relativePath']=='BulkRoot/fixtures/input/Orders.csv'

def test_upload_rejects_nonreferenced_and_unsafe_folder_inputs(isolated):
    p=cli.handle({'action':'bulk-create'});pid=p['id']
    ssis=ROOT/'ssis-packages'/'A_Employees_Active_Bonus_FIXED.dtsx'
    cli.handle({'action':'bulk-add','portfolioId':pid,'fileName':ssis.name,'contentBase64':encoded(ssis)})
    with pytest.raises(ValueError, match='not referenced'):
        cli.handle({'action':'bulk-input','portfolioId':pid,'packageName':ssis.name,
           'fileName':'Orders.csv','contentBase64':encoded(ROOT/'fixtures'/'input'/'Orders.csv')})
    with pytest.raises(ValueError, match='Unsafe'):
        cli.handle({'action':'bulk-input','portfolioId':pid,'packageName':ssis.name,
           'fileName':'Employees.csv','relativePath':'../Employees.csv',
           'contentBase64':encoded(ROOT/'fixtures'/'input'/'Employees.csv')})

def test_ui_has_folder_based_discovery_and_no_csv_upload():
    html=(ROOT/'DemoWeb/wwwroot/index.html').read_text()
    js=(ROOT/'DemoWeb/wwwroot/unified.js').read_text()
    assert 'id="source-folder" type="file" webkitdirectory' in html
    assert 'id="inputs"' not in html
    assert 'resolveInput(packageFile, ref, allFiles)' in js
    assert "call('bulk-input'" in js
    assert 'reuseMatching:true' in js
    assert "call('bulk-create')" in js
