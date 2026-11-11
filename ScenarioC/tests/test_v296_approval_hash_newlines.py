"""Windows approval byte-parity regression and legacy-session repair."""
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import test_v295_process_glue as base
import process_glue as pg
from unsupported_process_ai import sha, read_json, approved_candidate_bytes, RemediationBlocked


def test_approval_writes_exact_reviewed_utf8_bytes(tmp_path):
    base.setup(tmp_path)
    assert (tmp_path/'candidate.py').read_bytes()==base.CODE.encode('utf-8')
    assert sha((tmp_path/'candidate.py').read_bytes())==read_json(tmp_path/'manifest.json')['approvedCodeSha256']


def test_legacy_windows_crlf_approved_candidate_restored_before_cloud(tmp_path):
    base.setup(tmp_path)
    expected=base.CODE.encode('utf-8')
    (tmp_path/'candidate.py').write_bytes(expected.replace(b'\n',b'\r\n'))
    assert sha((tmp_path/'candidate.py').read_bytes())!=sha(expected)
    code=approved_candidate_bytes(tmp_path)
    assert code==expected
    assert (tmp_path/'candidate.py').read_bytes()==expected
    assert read_json(tmp_path/'approval-normalization.json')['restoredExactApprovedBytes']
    s3,glue,sts,logs=base.S3(),base.Glue(),base.STS(),base.Logs()
    deployed=pg.deploy(tmp_path,'f'*16,base.CFG,approve=True,client_factory=lambda *_:(s3,glue,sts,logs))
    assert deployed['approvedCodeSha256']==sha(expected)


def test_legacy_crlf_validates_on_existing_session(tmp_path,monkeypatch):
    base.setup(tmp_path)
    expected=base.CODE.encode()
    (tmp_path/'candidate.py').write_bytes(expected.replace(b'\n',b'\r\n'))
    # Approval can be verified and normalized without needing new Bedrock calls.
    assert approved_candidate_bytes(tmp_path)==expected


@pytest.mark.parametrize('mutate',[
    lambda data: data+b'\n# unreviewed',
    lambda data: data.replace(b'Active',b'Inactive'),
    lambda data: data.replace(b'\n',b'\r\n')+b'\r\n',
])
def test_modified_candidate_is_never_silently_reapproved(tmp_path,mutate):
    base.setup(tmp_path)
    (tmp_path/'candidate.py').write_bytes(mutate(base.CODE.encode()))
    with pytest.raises(RemediationBlocked,match='hash mismatch'):
        pg.deploy(tmp_path,'a'*16,base.CFG,approve=True,client_factory=lambda *_:pytest.fail('Cloud contacted'))


def test_tampered_proposal_fails_even_if_candidate_matches(tmp_path):
    base.setup(tmp_path)
    from unsupported_process_ai import write_json
    p=read_json(tmp_path/'proposal.json')
    p['code']=p['code']+'\n# changed by attacker'
    write_json(tmp_path/'proposal.json',p)
    with pytest.raises(RemediationBlocked,match='proposal integrity mismatch'):
        approved_candidate_bytes(tmp_path)
