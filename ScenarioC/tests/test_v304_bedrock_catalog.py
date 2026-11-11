"""Regression checks for AWS-region model discovery and service diagnostics."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'DemoWeb'

def test_catalog_is_live_for_profile_region_and_not_hardcoded():
    source=(WEB/'AwsSetup.cs').read_text(encoding='utf8')
    assert 'ListBedrockChoices' in source
    assert '"list-foundation-models"' in source
    assert '"list-inference-profiles"' in source
    assert '"inferenceProfileId"' in source
    assert '"ON_DEMAND"' in source
    assert '"inputModalities"' in source
    assert '"outputModalities"' in source
    assert '"ACTIVE"' in source

def test_ui_has_two_synchronized_selects_and_refresh():
    html=(WEB/'wwwroot/index.html').read_text(encoding='utf8')
    js=(WEB/'wwwroot/aws-setup.js').read_text(encoding='utf8')
    assert '<select id="aws-model">' in html
    assert '<select id="model">' in html
    assert 'aws-refresh-models' in html
    assert '/api/aws-setup/bedrock-models?' in js
    assert "$('model').value=$('aws-model').value" in js
    assert "$('aws-model').value=$('model').value" in js

def test_model_catalog_is_read_only_and_no_invocation():
    source=(WEB/'AwsSetup.cs').read_text(encoding='utf8')
    start=source.index('public static async Task<object> ListBedrockChoices')
    end=source.index('public static async Task<object> Test(')
    snippet=source[start:end]
    assert 'RunAws' in snippet
    assert '"converse"' not in snippet.lower()
    assert 'invoke-model' not in snippet.lower()

def test_bedrock_errors_reveal_sanitized_service_code():
    src=(ROOT/'engine/cli.py').read_text(encoding='utf8')
    assert "type(e).__name__ == 'ClientError'" in src
    assert "'errorType':'AwsServiceError'" in src
    assert '[REDACTED]' in src
