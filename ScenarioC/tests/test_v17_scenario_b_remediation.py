"""Tests against the user's *real* SCT CLI output for Scenario B."""
import ast,hashlib,json,zipfile
from pathlib import Path
import pytest
from quickflow import construct,stage,Blocked,static_review

REAL=Path(__file__).resolve().parents[1]/'evidence'/'ScenarioB_ActualSCT_Output.zip'

def setup(tmp_path):
    p=tmp_path/'0123456789abcdef';s=p/'sct'/'original';s.mkdir(parents=True)
    manifest=[]
    with zipfile.ZipFile(REAL) as z:
        for i,n in enumerate(x for x in z.namelist() if '/0. create-body-script/' in x and x.endswith('.py')):
            b=z.read(n);f=f'sct_{i:03}.py';(s/f).write_bytes(b)
            manifest.append({'file':f,'originalPath':n,'sha256':hashlib.sha256(b).hexdigest()})
    (p/'sct'/'manifest.json').write_text(json.dumps(manifest))
    return p

def test_b_real_sct_syntax_fixed_but_database_remains_blocked(tmp_path):
    r=construct(setup(tmp_path))
    assert any('Syntax: corrected SCT quoted' in e for e in r['edits'])
    assert any('specify connection' in b for b in r['blockers'])
    assert any('Destructive SQL' in b for b in r['blockers'])
    assert all(ast.parse(m['source']) for m in r['modules'])
    assert 'Customers.csv' not in r['inputs']

def test_b_approved_csv_lookup_adapter_yields_reviewable_sct_candidate(tmp_path):
    p=setup(tmp_path);r=construct(p,csv_lookup_demo=True)
    assert r['csvLookupDemo'] is True
    assert r['inputs']==['Customers.csv','Orders.csv']
    assert len(r['outputs'])==2
    assert not r['blockers']
    for m in r['modules']:
        assert not static_review(m['source'],{x['name'] for x in r['modules']})
        ast.parse(m['source'])
    src='\n'.join(m['source'] for m in r['modules'])
    assert 'lookup_customerid' in src
    assert 'col("lookup_customerid").isNull()' in src
    assert 'DecimalType(18,2)' in src
    assert 'No SQL Server is accessed' in src
    assert 'DELETE FROM dbo.DemoForgeCustomers' not in src
    assert 'spark.read.format("jdbc")' not in src
    report=stage(p,r)
    assert not report['blockers']
    with zipfile.ZipFile(p/'quick'/'corrected_scripts.zip') as z:
        assert 'sct_glue_entry.py' in z.namelist()
        assert 'REPAIR_PROVENANCE.txt' in z.namelist()

def test_b_adapter_rejects_unreviewed_topology(tmp_path):
    p=setup(tmp_path)
    manifest=json.loads((p/'sct'/'manifest.json').read_text())
    x=p/'sct'/'original'/manifest[1]['file']
    text=x.read_text().replace('CUSTOMER_NOT_FOUND','UNRECOGNIZED_PATH')
    x.write_text(text)
    manifest[1]['sha256']=hashlib.sha256(x.read_bytes()).hexdigest()
    (p/'sct'/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(Blocked):construct(p,csv_lookup_demo=True)

def test_sct_original_hash_enforced(tmp_path):
    p=setup(tmp_path);f=p/'sct'/'original'/'sct_000.py';f.write_text('print(1)')
    with pytest.raises(Blocked,match='hash changed'):construct(p,csv_lookup_demo=True)
