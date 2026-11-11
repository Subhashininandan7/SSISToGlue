"""Regression: real v2.2 Scenario B post-approval ZIP reported a false
'AI changed SCT statements' error because checks used the raw SCT source,
not the deterministic cleaned, S3-mapped pre-AI working copy.
"""
import hashlib
import json
import sys
import types
import zipfile
from pathlib import Path
import pytest
from test_v20_grounded_merge_ai import setup_session, NAME, source, DTSX
from quickflow import (construct, stage, propose_bedrock, accept, checks, digest)
from semantic_merge import metadata, describe_runtime_contract, canonical_assignment


class Model:
    def __init__(self, assignment):
        self.assignment=assignment
    def converse(self,**kwargs):
        return {'output':{'message':{'content':[{'text':json.dumps({'patches':[
            {'module':NAME,'assignment':self.assignment,'explanation':'reviewed insertion'}
        ]})}]}},'usage':{}}


def approved_working_session(tmp_path,monkeypatch):
    session=setup_session(tmp_path)
    # The user's genuine SCT scripts have already been cleaned in the test ZIP.
    # Recreate the earlier stage by adding an unused SCT helper to the source
    # artifact; deterministic repair must remove it *before* AI approval.
    manifest_path=session/'sct'/'manifest.json'
    manifest=json.loads(manifest_path.read_text())
    original=session/'sct'/'original'
    for item in manifest:
        file=original/item['file']
        if NAME in item['originalPath']:
            contents=file.read_bytes()
            contents=b'from sct_utils import cast\n'+contents
            file.write_bytes(contents)
            item['sha256']=hashlib.sha256(contents).hexdigest()
            break
    else:
        raise AssertionError('SCT data flow module not in evidence')
    manifest_path.write_text(json.dumps(manifest))
    data=construct(session)
    assert any('25042' in b for b in data['blockers'])
    assert any('Undefined SCT DataFrame' in b for b in data['blockers'])
    # The recorded session's manifest includes both staged CSV inputs and outputs.
    data['inputs']=['Customers.csv','Orders.csv']
    data['outputs']=['RejectedOrders_SSIS.csv','ValidOrders_SSIS.csv']
    data['blockers']=checks(data)
    stage(session,data)
    assignment=canonical_assignment(describe_runtime_contract(source(),metadata(DTSX)))
    model=Model(assignment)
    monkeypatch.setitem(sys.modules,'boto3',types.SimpleNamespace(
        Session=lambda **kwargs: types.SimpleNamespace(client=lambda name:model)))
    proposal=propose_bedrock(session,{'modelId':'amazon.nova-lite-v1:0'},True,True)
    assert proposal['patchCount']==1
    approved=accept(session,proposal['baseHash'],True)
    data=json.loads((session/'quick'/'working.json').read_text())
    return session,approved,data


def test_real_sct_zip_pinned_clean_baseline_clears_only_resolved_marker(tmp_path,monkeypatch):
    session,approved,data=approved_working_session(tmp_path,monkeypatch)
    assert approved['blockers']==[]
    assert checks(data)==[]
    module=next(m for m in data['modules'] if m['name']==NAME)
    assert 'import os' in module['semanticBaselineSource']
    assert 'MIGRATION_INPUT_PREFIX' in module['semanticBaselineSource']
    assert module['originalSource'] != module['semanticBaselineSource']
    assert '25042' in module['source'] # SCT audit comment retained, not treated as unresolved
    assert module['source'].count('csv_customer_merge_join = ')==1
    report=json.loads((session/'quick'/'report.json').read_text())
    assert report['blockers']==[]
    with zipfile.ZipFile(session/'quick'/'corrected_scripts.zip') as archive:
        assert archive.read('modules/'+NAME+'.py').decode()==module['source']
        provenance=archive.read('REPAIR_PROVENANCE.txt').decode()
        assert not provenance.split('BLOCKERS\n',1)[1].strip()


def test_legacy_v22_approved_session_recovers_only_default_csv_baseline(tmp_path,monkeypatch):
    _,_,data=approved_working_session(tmp_path,monkeypatch)
    module=next(m for m in data['modules'] if m['name']==NAME)
    module.pop('semanticBaselineSource')
    proof=data['semanticValidated'][NAME]
    proof.pop('preAiBaselineSha256')
    proof.pop('originalSctSourceSha256')
    assert checks(data)==[] # Source-derived legacy baseline is reconstructed and verified exactly
    data['preserveSqlServer']=True
    assert any('No pinned pre-AI baseline' in x for x in checks(data))


@pytest.mark.parametrize('edit',[
    lambda m:m.__setitem__('source',m['source'].replace('"left").select(', '"inner").select(')),
    lambda m:m.__setitem__('source',m['source'].replace('customername").alias(', 'wrongname").alias(')),
    lambda m:m.__setitem__('source',m['source'].replace('Severity CRITICAL','Severity INFO')),
    lambda m:m.__setitem__('source',m['source']+'\n# extra unreviewed statement'),
    lambda m:m.__setitem__('semanticBaselineSource',m['semanticBaselineSource']+'\n# altered baseline'),
    lambda m:m.__setitem__('originalSource',m['originalSource']+'\n# altered original evidence'),
])
def test_postapproval_modifications_still_rejected(tmp_path,monkeypatch,edit):
    _,_,data=approved_working_session(tmp_path,monkeypatch)
    mod=next(m for m in data['modules'] if m['name']==NAME)
    edit(mod)
    assert any('semantic repair proof invalid' in b for b in checks(data))


def test_unresolved_extra_unsupported_component_remains_blocked(tmp_path,monkeypatch):
    _,_,data=approved_working_session(tmp_path,monkeypatch)
    module=next(m for m in data['modules'] if m['name']==NAME)
    module['source'] += '\n# [25042 - another unsupported component]' 
    blockers=checks(data)
    assert any('SCT unsupported component marker' in b for b in blockers)
    assert any('semantic repair proof invalid' in b for b in blockers)


def test_rerun_analyze_does_not_erase_approved_patch_or_request_bedrock(tmp_path,monkeypatch):
    (tmp_path/'sessions'/'1234567890abcdef').mkdir(parents=True)
    session,_,data=approved_working_session(tmp_path/'sessions'/'1234567890abcdef',monkeypatch)
    import cli
    monkeypatch.setattr(cli,'HOME',tmp_path)
    (session/'session.json').write_text(json.dumps({
        'id':'1234567890abcdef', 'scenario':'CUSTOM','history':[],
        'quickAnalysis':'BLOCKED_PENDING_REPAIR'
    }))
    result=cli.quick_analyze({'sessionId':'1234567890abcdef'})
    assert result['blockers']==[]
    assert result['status']=='STATIC_REVIEW_COMPLETE'
    saved=json.loads((session/'quick'/'working.json').read_text())
    assert saved['semanticValidated'][NAME]
    assert 'csv_customer_merge_join = ' in next(m['source'] for m in saved['modules'] if m['name']==NAME)
