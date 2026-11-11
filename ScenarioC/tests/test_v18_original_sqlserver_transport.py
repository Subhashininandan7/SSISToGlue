"""Real SCT CLI Scenario B fixture, no live database/AWS calls."""
import ast,hashlib,json,zipfile
from pathlib import Path
from types import SimpleNamespace
import pytest
from quickflow import construct,stage,checks,Blocked,make_entry
from jdbc_glue_config import validate,validate_and_probe,JdbcConfigError

REAL=Path(__file__).resolve().parents[1]/'evidence'/'ScenarioB_ActualSCT_Output.zip'

def session(tmp_path):
    p=tmp_path/'0123456789abcdef';d=p/'sct'/'original';d.mkdir(parents=True)
    manifest=[]
    with zipfile.ZipFile(REAL) as z:
        for i,n in enumerate(k for k in z.namelist() if '/0. create-body-script/' in k and k.endswith('.py')):
            b=z.read(n);file=f'sct_{i:03}.py';(d/file).write_bytes(b)
            manifest.append({'file':file,'originalPath':n,'sha256':hashlib.sha256(b).hexdigest()})
    (p/'sct'/'manifest.json').write_text(json.dumps(manifest))
    return p

def test_real_b_preserves_live_sql_server_and_corrects_join(tmp_path):
    p=session(tmp_path)
    r=construct(p,preserve_sql_server=True)
    assert r['preserveSqlServer'] is True and not r['csvLookupDemo']
    assert r['blockers']==[]
    assert set(r['inputs'])=={'Orders.csv','Customers.csv'}
    assert set(r['outputs'])=={'ValidOrders_SSIS.csv','RejectedOrders_SSIS.csv'}
    mods={x['name']:x['source'] for x in r['modules']}
    assert len(mods)==4
    assert 'stage_customers(connection)' in mods['b_orders_customer_lookup']
    assert 'spark.read.format("jdbc")' in mods['lookup_x0020_orders_x0020_and_x0020_route_x0020_rejects']
    assert 'FROM dbo.DemoForgeCustomers' in mods['lookup_x0020_orders_x0020_and_x0020_route_x0020_rejects']
    assert 'os.environ["MIGRATION_INPUT_PREFIX"]' in mods['lookup_x0020_orders_x0020_and_x0020_route_x0020_rejects']
    assert 'stmt.executeUpdate(_SQL_DELETE)' in mods['sct_sql_server_stage']
    assert 'sqlconn.rollback()' in mods['sct_sql_server_stage']
    assert 'sqlconn.commit()' in mods['sct_sql_server_stage']
    assert 'prepareStatement(_SQL_INSERT)' in mods['sct_sql_server_stage']
    assert 'Customers.csv' in mods['sct_sql_server_stage']
    assert 'LEFT' not in mods['sct_sql_server_stage']
    for code in mods.values():ast.parse(code)
    report=stage(p,r)
    assert not report['blockers']
    entry=make_entry(r)
    assert 'secretsmanager' in entry and "connection={'SOURCE':" not in entry
    assert 'jdbc_secret_arn' in entry
    with zipfile.ZipFile(p/'quick'/'corrected_scripts.zip') as z:
        assert 'modules/sct_sql_server_stage.py' in z.namelist()
        assert 'SCT_BEFORE_AFTER.diff' in z.namelist()
        assert 'SQL Server' in z.read('REPAIR_PROVENANCE.txt').decode()

def test_unapproved_sql_still_blocks(tmp_path):
    r=construct(session(tmp_path))
    assert any('specify connection' in x for x in r['blockers'])
    assert any('Destructive SQL' in x for x in r['blockers'])

def test_pinned_sql_transport_rejects_ai_modifications(tmp_path):
    r=construct(session(tmp_path),preserve_sql_server=True)
    r['modules'][1]['source']+='\n# changed\n'
    assert any('Reviewed JDBC source changed' in x for x in checks(r))

def test_sql_adapter_rejects_unreviewed_stage(tmp_path):
    p=session(tmp_path)
    manifest=json.loads((p/'sct/manifest.json').read_text())
    target=p/'sct/original'/manifest[0]['file']
    target.write_bytes(target.read_bytes().replace(b'BULK INSERT',b'EXECUTE DANGEROUS'))
    manifest[0]['sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
    (p/'sct/manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(Blocked):construct(p,preserve_sql_server=True)

def config():
    return {'glueConnectionName':'sqlserver-private-connection',
       'jdbcSecretArn':'arn:aws:secretsmanager:ap-southeast-2:123456789012:secret:sqlserver/demo-Abc123',
       'jdbcJarS3':'s3://ssis-glue-poc-bucket/drivers/mssql-jdbc-13.6.0.jre11.jar',
       'region':'ap-southeast-2','profile':'ssis-glue-poc'}

def test_requires_network_secret_and_jar():
    for omit in ('glueConnectionName','jdbcSecretArn'):
        c=config();c.pop(omit)
        with pytest.raises(JdbcConfigError):validate(c)
    c=config();c['jdbcSecretArn']='arn:aws:secretsmanager:us-east-1:123456789012:secret:sqlserver/demo'
    with pytest.raises(JdbcConfigError):validate(c)


def test_cloud_preflight_uses_real_api_metadata(monkeypatch):
    class FakeGlue:
        def get_connection(self,**kw):
            assert kw['Name']=='sqlserver-private-connection'
            return {'Connection':{'PhysicalConnectionRequirements':{'SubnetId':'subnet-a','SecurityGroupIdList':['sg-1']}}}
    class FakeS3:
        def head_object(self,**kw):
            assert kw['Key'].endswith('.jar')
    class FakeSecrets:
        def describe_secret(self,**kw):
            assert kw['SecretId']==config()['jdbcSecretArn']
            return {}
    class Session:
        def __init__(self,**kw):pass
        def client(self,name):assert name=='secretsmanager';return FakeSecrets()
    import sys
    monkeypatch.setitem(sys.modules,'boto3',SimpleNamespace(Session=Session))
    assert validate_and_probe(config(),FakeGlue(),FakeS3())['jdbcJarS3'].endswith('.jar')

def test_deploy_passes_vpc_connection_secret_and_jar(monkeypatch,tmp_path):
    import quickflow,sys
    from types import SimpleNamespace
    from pathlib import Path
    p=session(tmp_path);r=construct(p,preserve_sql_server=True);stage(p,r)
    # Cloud test doubles only: never pretend AWS/SQL executed.
    class NotFound(Exception):pass
    class Glue:
        exceptions=SimpleNamespace(EntityNotFoundException=NotFound)
        def get_job(self,**kw):raise NotFound()
        def create_job(self,**kw):
            self.kw=kw
    class S3:
        def __init__(self):self.uploaded={}
        def put_object(self,**kw):self.uploaded[kw['Key']]=kw['Body']
    class Sts:
        def get_caller_identity(self):return {'Account':'123456789012'}
    glue=Glue();s3=S3()
    monkeypatch.setattr(sys.modules['cloud'] if 'cloud' in sys.modules else __import__('cloud'),'clients',lambda *args:(s3,glue,Sts(),None))
    import jdbc_glue_config
    monkeypatch.setattr(jdbc_glue_config,'validate_and_probe',lambda cfg,g,s:validate(cfg))
    from pathlib import Path
    fixtures=Path(__file__).resolve().parents[1]/'fixtures'
    cfg={**config(),'bucket':'ssis-glue-poc-bucket','prefix':'ssis-migrations','glueRole':'AWSGlueServiceRole-SSISPoc'}
    out=quickflow.cloud_deploy(p,cfg,fixtures)
    assert out['origin']=='SCT_DERIVED' and out['sqlServerMode'] is True
    assert glue.kw['Connections']['Connections']==['sqlserver-private-connection']
    assert glue.kw['DefaultArguments']['--extra-jars'].endswith('.jar')
    assert glue.kw['DefaultArguments']['--jdbc_secret_arn']==config()['jdbcSecretArn']
    assert 'sct_modules.zip' in glue.kw['DefaultArguments']['--extra-py-files']
    assert len([x for x in s3.uploaded if '/input/' in x])==2
    assert all(isinstance(x,bytes) for x in s3.uploaded.values())
