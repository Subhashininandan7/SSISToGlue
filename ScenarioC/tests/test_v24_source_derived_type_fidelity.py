"""v2.5 regression: automatic source-proven numeric fixes with pinned proofs."""
import json,zipfile
from test_v23_approved_semantic_baseline import approved_working_session, NAME
from quickflow import checks, stage

def test_source_types_applied_without_individual_approval(tmp_path,monkeypatch):
    session,approved,data=approved_working_session(tmp_path,monkeypatch)
    assert approved['blockers']==[]
    assert checks(data)==[]
    assert data['typeValidated'][NAME]['mode']=='AUTOMATIC_SOURCE_PROVEN'
    mod=next(m for m in data['modules'] if m['name']==NAME)
    assert 'CAST((`quantity` * `unitprice`) AS DECIMAL(18,2))' in mod['source']
    assert '.cast("double")' in mod['source']
    assert '.cast("int")' in mod['source']
    assert 'csv_customer_merge_join = orders_x0020_csv.alias(' in mod['source']
    assert '25042' in mod['source']
    with zipfile.ZipFile(session/'quick'/'corrected_scripts.zip') as z:
        assert z.read('modules/'+NAME+'.py').decode()==mod['source']

def test_rejected_type_tampering(tmp_path,monkeypatch):
    _,_,data=approved_working_session(tmp_path,monkeypatch)
    mod=next(m for m in data['modules'] if m['name']==NAME)
    mod['source']=mod['source'].replace('DECIMAL(18,2)','DECIMAL(10,0)')
    assert any('type fidelity approval invalid' in b for b in checks(data))

def test_reanalysis_idempotent(tmp_path,monkeypatch):
    session,_,data=approved_working_session(tmp_path,monkeypatch)
    old={m['name']:m['source'] for m in data['modules']}
    stage(session,data)
    assert {m['name']:m['source'] for m in data['modules']}==old
    assert checks(data)==[]

def test_automatic_type_proof_independent_of_expected_fixtures(tmp_path,monkeypatch):
    session,_,data=approved_working_session(tmp_path,monkeypatch)
    expected=session/'fixtures'/'expected';expected.mkdir(parents=True)
    (expected/'ValidOrders.csv').write_text('fake,999\n')
    assert checks(data)==[]
    assert data['typeValidated'][NAME]['mode']=='AUTOMATIC_SOURCE_PROVEN'
