from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
js=(ROOT/'DemoWeb/wwwroot/unified.js').read_text()
engine=(ROOT/'engine/bulk.py').read_text()

def test_button_does_not_require_quick_analysis_for_sct_25029():
 assert "return !!(p.sctImported||p.sctCompleted" in js
 assert "if(p.quickAnalysis)return false" in js
 assert "diagnostics:ordered().filter" in js
 assert "appVersion:" in js

def test_missing_sct_artifacts_have_actionable_error():
 assert "No original SCT conversion ZIP for this package" in engine
