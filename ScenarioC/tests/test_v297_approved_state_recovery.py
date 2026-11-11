"""Approved artifacts take precedence over transient failed AI attempts."""
import base64
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import bulk,cli
import test_v295_process_glue as fixtures
from unsupported_process_ai import read_json

def test_failed_reproposal_state_recovers_from_exact_approved_evidence(tmp_path):
    old=cli.HOME
    cli.HOME=tmp_path/'isolated'
    try:
        pid=bulk.create(cli,{})['id']
        name='C_Unsupported_Execute_Process_AI_Demo.dtsx'
        bulk.add(cli,{'portfolioId':pid,'fileName':name,'contentBase64':base64.b64encode((fixtures.FIX/name).read_bytes()).decode()})
        e=bulk.status(cli,{'portfolioId':pid})['packages'][0]
        ai=cli.session_path(e['sessionId'])/'process-ai'
        fixtures.setup(ai)
        plan=bulk._read(cli,pid)
        plan['packages'][0].update(processAIKind='EXECUTE_PROCESS_25029',state='ERROR_AI_PROPOSE',lastError='Bedrock did not return valid JSON')
        bulk._save(cli,bulk._path(cli,pid),plan)
        recovered=bulk.status(cli,{'portfolioId':pid})['packages'][0]
        assert recovered['state']=='LOCAL_OUTPUT_GENERATED'
        assert recovered['lastError'] is None
        # Repeat model request reuses the approved hash; does not contact Bedrock.
        r=bulk.step(cli,{'portfolioId':pid,'packageName':name,'operation':'ai-propose'})
        assert r['result']['status']=='ALREADY_APPROVED_AND_VALIDATED'
        assert r['state']=='LOCAL_OUTPUT_GENERATED'
        assert read_json(ai/'manifest.json')['status']=='LOCAL_OUTPUT_GENERATED'
    finally:cli.HOME=old

def test_unapproved_failure_does_not_fake_recovery(tmp_path):
    old=cli.HOME;cli.HOME=tmp_path/'isolated'
    try:
        pid=bulk.create(cli,{})['id'];name='C_Unsupported_Execute_Process_AI_Demo.dtsx'
        bulk.add(cli,{'portfolioId':pid,'fileName':name,'contentBase64':base64.b64encode((fixtures.FIX/name).read_bytes()).decode()})
        e=bulk.status(cli,{'portfolioId':pid})['packages'][0]
        ai=cli.session_path(e['sessionId'])/'process-ai'
        fixtures.setup(ai,approved=False)
        plan=bulk._read(cli,pid)
        plan['packages'][0].update(processAIKind='EXECUTE_PROCESS_25029',state='ERROR_AI_PROPOSE',lastError='Bedrock malformed JSON')
        bulk._save(cli,bulk._path(cli,pid),plan)
        recovered=bulk.status(cli,{'portfolioId':pid})['packages'][0]
        assert recovered['state']=='ERROR_AI_PROPOSE'
    finally:cli.HOME=old

def test_ui_routes_unsupported_packages_and_avoids_duplicate_ai():
    js=(ROOT/'DemoWeb/wwwroot/unified.js').read_text()
    assert "|| p.unsupportedProcessAI || p.processAIKind==='EXECUTE_PROCESS_25029'" in js
    assert "let r=await all('deploy',p=>eligible(p)&&verified.has(p.name))" in js
    assert "if(p.unsupportedProcessAI&&['LOCAL_OUTPUT_GENERATED','LOCAL_PARITY_MATCH'].includes(p.processAIStatus))return false;" in js

def test_reanalysis_never_overwrites_approved_candidate(tmp_path):
    from unsupported_process_ai import Workflow,sha,RemediationBlocked
    import pytest
    fixtures.setup(tmp_path)
    approved=(tmp_path/'candidate.py').read_bytes()
    original=(fixtures.FIX/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes()
    sct=(fixtures.FIX/'original-conversion-output (4).zip').read_bytes()
    script=(fixtures.FIX/'transform.ps1').read_bytes()
    result=Workflow(tmp_path).analyze(original,sct,script,{}, {})
    assert result['status']=='LOCAL_OUTPUT_GENERATED'
    assert (tmp_path/'candidate.py').read_bytes()==approved
    with pytest.raises(RemediationBlocked,match='Source evidence changed'):
        Workflow(tmp_path).analyze(original+b'changed',sct,script,{}, {})
