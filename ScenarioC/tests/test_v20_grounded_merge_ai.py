"""Regression on the user's actual corrected-scripts artifact, NOT invented ETL output."""
import hashlib,json,zipfile,sys,types,ast
from pathlib import Path
import pytest
from quickflow import construct,stage,propose_bedrock,accept,Blocked,checks
from semantic_merge import (metadata,describe_runtime_contract,canonical_assignment,
                            validate_proposal,SemanticBlocked,unresolved_frames)

ROOT=Path(__file__).resolve().parents[1]
ZIP=ROOT/'evidence'/'ScenarioB_V2_Actual_Corrected_SCT.zip'
DTSX=ROOT/'ssis-packages'/'B_CSV_Customer_Order_Join_REPAIRED_V2.dtsx'
NAME='lookup_x0020_orders_x0020_and_x0020_route_x0020_rejects'

def source():
    with zipfile.ZipFile(ZIP) as z:return z.read('modules/'+NAME+'.py').decode('utf-8')

def proposed():
    code=source();contract=describe_runtime_contract(code,metadata(DTSX))
    line='\t'+canonical_assignment(contract)+'\n'
    anchor='\tcsv_customer_merge_join.createOrReplaceTempView('
    assert anchor in code
    return code.replace(anchor,line+anchor,1)

def setup_session(tmp_path):
    (tmp_path/'source').mkdir();(tmp_path/'source'/'original.dtsx').write_bytes(DTSX.read_bytes())
    folder=tmp_path/'sct'/'original';folder.mkdir(parents=True)
    manifest=[]
    with zipfile.ZipFile(ZIP) as z:
        for i,name in enumerate(sorted(n for n in z.namelist() if n.startswith('modules/') and n.endswith('.py'))):
            content=z.read(name); target='sct_%03d.py'%i;(folder/target).write_bytes(content)
            manifest.append({'file':target,'originalPath':'0. create-body-script/0. pkg.'+Path(name).name,'sha256':hashlib.sha256(content).hexdigest()})
    (tmp_path/'sct'/'manifest.json').write_text(json.dumps(manifest))
    (tmp_path/'sct'/'auto-result.json').write_text('{}')
    return tmp_path

def test_genuine_original_metadata_proves_keys_and_output_lineage():
    contract=describe_runtime_contract(source(),metadata(DTSX))
    assert contract['keys']==['CustomerID','CustomerID']
    assert contract['joinType']=='left'
    assert [x['name'] for x in contract['outputs']]==['OrderID','CustomerID','Quantity','UnitPrice','CustomerName']
    assert contract['frames']==['orders_x0020_csv','customers_x0020_csv']
    assert unresolved_frames(source())==['csv_customer_merge_join']
    assert validate_proposal(source(),proposed(),contract)['joinType']=='left'

@pytest.mark.parametrize('bad',[
    lambda x:x.replace('"left").select(', '"inner").select('),
    lambda x:x.replace('ss_right.customerid','ss_right.customername'),
    lambda x:x.replace('"ss_right.customername").alias("customername")','"ss_right.customerid").alias("customername")'),
    lambda x:x.replace('"customername").alias("customername")','"customername").alias("notcustomername")'),
    lambda x:x.replace('CUSTOMER_NOT_FOUND','FAKE_REASON'),
    lambda x:x.replace('spark.read.csv(', 'spark.read.json(',1),
])
def test_bad_bedrock_proposals_rejected(bad):
    contract=describe_runtime_contract(source(),metadata(DTSX))
    with pytest.raises(SemanticBlocked):validate_proposal(source(),bad(proposed()),contract)

def test_real_zip_reports_missing_join_and_blocks_deployment(tmp_path):
    p=setup_session(tmp_path);data=construct(p)
    assert any('Undefined SCT DataFrame receiver: csv_customer_merge_join' in x for x in data['blockers'])
    assert any('25042' in x for x in data['blockers'])
    stage(p,data)
    assert (p/'quick'/'corrected_scripts.zip').is_file()

class FakeRuntime:
    def __init__(self,code):self.code=code;self.prompts=[]
    def converse(self,**kw):
        self.prompts.append(kw)
        assert 'originalSSISMergeJoinMetadata' in kw['messages'][0]['content'][0]['text']
        return {'output':{'message':{'content':[{'text':json.dumps({'patches':[{'module':NAME,'assignment':self.code,'explanation':'Restore source-proven left join'}]})}]}},'usage':{'inputTokens':123,'outputTokens':234}}

def test_mock_bedrock_review_approval_and_deploy_gate(tmp_path,monkeypatch):
    p=setup_session(tmp_path)
    data=construct(p);data['inputs']=['Customers.csv','Orders.csv'];data['outputs']=['ValidOrders_SSIS.csv','RejectedOrders_SSIS.csv'];data['blockers']=checks(data);stage(p,data)
    runtime=FakeRuntime(canonical_assignment(describe_runtime_contract(source(),metadata(DTSX))))
    fake=types.SimpleNamespace(Session=lambda **kw:types.SimpleNamespace(client=lambda name:runtime))
    monkeypatch.setitem(sys.modules,'boto3',fake)
    settings={'profile':'test','region':'ap-southeast-2','modelId':'amazon.nova-lite-v1:0'}
    res=propose_bedrock(p,settings,True,True)
    assert res['patchCount']==1
    assert res['status']=='AI_PATCH_REVIEW_ONLY'
    with pytest.raises(Blocked,match='approve'):
        accept(p,res['baseHash'],False)
    approved=accept(p,res['baseHash'],True)
    assert approved['blockers']==[]
    work=json.loads((p/'quick'/'working.json').read_text())
    assert checks(work)==[]
    assert work['semanticValidated'][NAME]['joinType']=='left'
    # Invalidate proof: a post-approval manual source change must fail closed.
    for m in work['modules']:
        if m['name']==NAME:m['source']=m['source'].replace('"left").select(', '"inner").select(')
    assert any('semantic repair proof invalid' in v for v in checks(work))


def test_bedrock_wrong_join_rejected_before_proposal_file(tmp_path,monkeypatch):
    p=setup_session(tmp_path);stage(p,construct(p))
    runtime=FakeRuntime(canonical_assignment(describe_runtime_contract(source(),metadata(DTSX))).replace('"left").select(', '"inner").select('))
    monkeypatch.setitem(sys.modules,'boto3',types.SimpleNamespace(Session=lambda **kw:types.SimpleNamespace(client=lambda name:runtime)))
    with pytest.raises(Blocked,match='Merge Join assignment rejected'):
        propose_bedrock(p,{'modelId':'amazon.nova-lite-v1:0'},True,True)
    assert not (p/'quick'/'proposal.json').exists()

# V2.1: Bedrock must return a single expression, never the modified Python file.
from semantic_merge import insert_scoped_assignment

def test_assignment_insertion_preserves_every_original_byte_and_scope():
    before=source(); contract=describe_runtime_contract(before,metadata(DTSX))
    assignment=canonical_assignment(contract)
    after, proof=insert_scoped_assignment(before,assignment,contract)
    assert proof['joinType']=='left'
    assert after.count(assignment)==1
    inserted='\t'+assignment+('\r\n' if '\r\n' in before else '\n')
    assert after.replace(inserted,'',1)==before
    assert not unresolved_frames(after)
    assert '25042' in after  # retained as provenance comment, NOT executable
    compile(after,'converted.py','exec')

@pytest.mark.parametrize('bad',[ 
    lambda x:x.replace('"left"','"inner"'),
    lambda x:x.replace('ss_right.customerid','ss_right.orderid'),
    lambda x:x.replace('"customername"','"wrongname"'),
    lambda x:x+'\nimport os',
    lambda x:'import os; '+x,
    lambda x:x+' # commentary',
    lambda x:'',
])
def test_scoped_assignment_rejects_semantic_changes_and_extra_statements(bad):
    original=source(); contract=describe_runtime_contract(original,metadata(DTSX))
    with pytest.raises(SemanticBlocked):
        insert_scoped_assignment(original,bad(canonical_assignment(contract)),contract)

class BogusRuntime:
    def __init__(self,payload):self.payload=payload
    def converse(self,**kw):
        return {'output':{'message':{'content':[{'text':json.dumps(self.payload)}]}},'usage':{}}

def test_bedrock_complete_module_is_rejected_without_proposal(tmp_path,monkeypatch):
    p=setup_session(tmp_path);stage(p,construct(p))
    fake=BogusRuntime({'patches':[{'module':NAME,'code':proposed()}]})
    monkeypatch.setitem(sys.modules,'boto3',types.SimpleNamespace(Session=lambda **kw:types.SimpleNamespace(client=lambda name:fake)))
    with pytest.raises(Blocked,match='unrequested module or fields'):
        propose_bedrock(p,{'modelId':'amazon.nova-lite-v1:0'},True,True)
    assert not (p/'quick'/'proposal.json').exists()

def test_reviewed_patch_is_one_line_and_approval_rechecks_exact_diff(tmp_path,monkeypatch):
    p=setup_session(tmp_path);stage(p,construct(p))
    assignment=canonical_assignment(describe_runtime_contract(source(),metadata(DTSX)))
    fake=BogusRuntime({'patches':[{'module':NAME,'assignment':assignment}]})
    monkeypatch.setitem(sys.modules,'boto3',types.SimpleNamespace(Session=lambda **kw:types.SimpleNamespace(client=lambda name:fake)))
    proposal=propose_bedrock(p,{'modelId':'amazon.nova-lite-v1:0'},True,True)
    assert proposal['patchCount']==1
    additions=[x for x in proposal['diff'].splitlines() if x.startswith('+') and not x.startswith('+++')]
    deletions=[x for x in proposal['diff'].splitlines() if x.startswith('-') and not x.startswith('---')]
    assert len(additions)==1 and not deletions
    assert additions[0][1:].strip()==assignment
    body=json.loads((p/'quick'/'proposal.json').read_text())
    assert body['patches'][0]['assignmentOnly']
    body['patches'][0]['code']=body['patches'][0]['code'].replace('"left"','"inner"')
    (p/'quick'/'proposal.json').write_text(json.dumps(body))
    with pytest.raises(Blocked,match='no longer matches the reviewed diff'):
        accept(p,proposal['baseHash'],True)
