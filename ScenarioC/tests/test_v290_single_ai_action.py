from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
html=(ROOT/'DemoWeb/wwwroot/index.html').read_text()
js=(ROOT/'DemoWeb/wwwroot/unified.js').read_text()

def test_only_one_ai_generation_button():
    assert html.count('id="ai"')==1
    assert html.count('Generate AI fixes where needed')==1
    assert 'id="ai-local-validate"' not in html
    assert 'Validate approved unsupported-task repair locally' not in html

def test_review_approval_remains_and_triggers_validation():
    assert 'id="apply"' in html
    assert "$('ai-local-validate').onclick" not in js
    assert "await step(p,'ai-accept'" in js
    assert "await step(current,'ai-local-validate')" in js
    assert js.index("await step(p,'ai-accept'")<js.index("await step(current,'ai-local-validate')")
    assert "if(current?.processAIKind==='EXECUTE_PROCESS_25029')" in js
    assert "LOCAL_VALIDATION_FAILED" in js

def test_existing_ai_generation_and_normal_deployment_path_retained():
    assert "await all('ai-propose',p=>needsAi(p)" in js
    assert "let r=await all('deploy',p=>eligible(p)&&verified.has(p.name))" in js
    assert "!!p.quickAnalysis" in js
