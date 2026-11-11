import hashlib,json,zipfile
from pathlib import Path
import pytest
from quickflow import construct,stage,static_review,choose_entry,Blocked,accept

REAL=Path(__file__).resolve().parents[1]/'evidence'/'ScenarioA_Unfixed_ActualSCT_Output.zip'

def sample(tmp_path):
    p=tmp_path/'session';src=p/'sct'/'original';src.mkdir(parents=True)
    manifest=[]
    with zipfile.ZipFile(REAL) as z:
        for i,n in enumerate(x for x in z.namelist() if x.endswith('.py') and z.getinfo(x).file_size):
            b=z.read(n);file=f'sct_{i:03d}.py';(src/file).write_bytes(b)
            manifest.append({'file':file,'originalPath':n,'sha256':hashlib.sha256(b).hexdigest()})
    (p/'sct'/'manifest.json').write_text(json.dumps(manifest))
    return p

def test_actual_sct_sample_generic_no_hardcoded_names(tmp_path):
    p=sample(tmp_path)
    data=construct(p)
    assert data['inputs']==['Employees.csv']
    assert data['outputs']==['ActiveEmployees_SSIS.csv']
    assert data['blockers']==[]
    assert len(data['modules'])==3
    assert all('sct_utils' not in m['source'] for m in data['modules'])
    assert any('MIGRATION_INPUT_PREFIX' in m['source'] for m in data['modules'])
    assert any('MIGRATION_OUTPUT_PREFIX' in m['source'] for m in data['modules'])
    report=stage(p,data)
    with zipfile.ZipFile(p/'quick'/'corrected_scripts.zip') as z:
        assert 'sct_glue_entry.py' in z.namelist()
        assert 'sct_modules.zip' in z.namelist()
        assert len([x for x in z.namelist() if x.startswith('modules/')])==3
    assert report['blockers']==[]

@pytest.mark.parametrize('name', ['foo.exe','../../escape.py','not python.py'])
def test_unsafe_module_names_block(name,tmp_path):
    p=sample(tmp_path)
    manifest=json.loads((p/'sct'/'manifest.json').read_text())
    manifest[0]['originalPath']=name
    (p/'sct'/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(Blocked):construct(p)

def test_block_unknown_import_and_exec():
    assert static_review('import suspicious_lib\n',set())
    assert static_review('import os\nos.system("echo hi")\n',set())
    assert static_review('eval("1+1")\n',set())


def test_no_guessed_entry():
    with pytest.raises(Blocked):choose_entry([{'name':'a','source':'def run(): pass'}])

def test_unapproved_ai_patch_rejected(tmp_path):
    p=sample(tmp_path);stage(p,construct(p))
    with pytest.raises(Blocked):accept(p,'invalid',False)

def test_generic_deployment_uploads_real_sct_entry_not_reference(tmp_path,monkeypatch):
    import quickflow,cloud
    p=tmp_path/'0123456789abcdef';p.mkdir()
    # Fixture input staged under the exact basename from the genuine SCT code.
    inp=p/'inputs';inp.mkdir();(inp/'Employees.csv').write_text('employeeid,employeeName,salary,status\n101,Ravi,50000,Active\n')
    report=stage(p,construct(sample(tmp_path/'other')))
    seen={'objects':[], 'jobs':[]}
    class S3:
        def put_object(self,**kw):seen['objects'].append(kw)
    class Glue:
        class exceptions:
            class EntityNotFoundException(Exception):pass
        def get_job(self,**kw):raise self.exceptions.EntityNotFoundException()
        def create_job(self,**kw):seen['jobs'].append(kw)
    class STS:
        def get_caller_identity(self):return {'Account':'123456789012'}
    monkeypatch.setattr(cloud,'clients',lambda profile,region:(S3(),Glue(),STS(),None))
    cfg={'profile':'ssis-glue-poc','region':'ap-southeast-2','bucket':'demo-bucket',
         'prefix':'sct-demo','glueRole':'test-role'}
    ret=quickflow.cloud_deploy(p,cfg,tmp_path)
    assert ret['origin']=='SCT_DERIVED'
    assert ret['scriptS3'].endswith('/scripts/sct_entry.py')
    assert len(seen['jobs'])==1
    assert seen['jobs'][0]['Command']['ScriptLocation']==ret['scriptS3']
    assert len(seen['objects'])==3
    assert all('reference' not in x['Key'] for x in seen['objects'])
