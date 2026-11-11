"""Single user workflow on top of real per-package bulk API."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def test_exactly_one_five_step_interface():
    html=(ROOT/'DemoWeb/wwwroot/index.html').read_text()
    assert html.count('class="stage')==5
    assert 'id="mode-single"' not in html
    assert 'id="mode-bulk"' not in html
    assert 'id="bulk-workspace"' not in html
    assert 'src="unified.js?v=298"' in html
    assert 'src="app.js"' not in html and 'src="bulk.js"' not in html
    assert 'id="source-folder" type="file" webkitdirectory directory multiple' in html

def test_all_operations_use_existing_package_isolated_bulk_engine():
    js=(ROOT/'DemoWeb/wwwroot/unified.js').read_text()
    for action in ['convert','analyze','ai-propose','ai-accept','aws','deploy','run','poll','validate']:
        assert f"'{action}'" in js
    assert "call('bulk-step'" in js
    assert "all('convert'" in js
    assert "all('analyze'" in js
    assert "all('deploy'" in js
    assert "all('run'" in js

def test_ai_is_review_only_and_approvals_are_required():
    js=(ROOT/'DemoWeb/wwwroot/unified.js').read_text()
    assert "status==='AI_PATCH_REVIEW_ONLY'" in js
    assert "if(!$('approve-diffs').checked)" in js
    assert 'approveExactDiff:true' in js
    assert "if(!$('deploy-approval').checked)" in js
    assert "if(!$('run-approval').checked)" in js
    assert 'recoverProposals()' in js

def test_real_csv_comparison_not_fake_sql_parity():
    html=(ROOT/'DemoWeb/wwwroot/index.html').read_text()
    js=(ROOT/'DemoWeb/wwwroot/unified.js').read_text()
    assert 'SQL parity is not yet supported' in html
    assert "p.glueStatus!=='SUCCEEDED'" in js
    assert "r.result?.status==='MATCH'" in js
    assert 'reference file' in js
