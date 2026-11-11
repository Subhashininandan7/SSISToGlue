"""Regression guard: AWS setup is additive and doesn't alter the migration engine."""
from pathlib import Path
import json

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/'DemoWeb'

def test_wizard_and_backend_routes():
    markup=(WEB/'wwwroot/index.html').read_text()
    csharp=(WEB/'Program.cs').read_text()
    assert 'id="aws-setup-overlay"' in markup
    for token in ('aws-profile','aws-region','aws-bucket','aws-prefix','aws-role','aws-model','aws-connect','aws-test','aws-reconnect'):
        assert f'id="{token}"' in markup
    for route in ('/api/aws-setup','/api/aws-setup/connect','/api/aws-setup/test'):
        assert route in csharp
    assert 'app.MapPost("/api/action"' in csharp

def test_no_credentials_in_config_template():
    settings=json.loads((WEB/'appsettings.json').read_text())['AwsSetup']
    assert set(settings)=={'Profile','Region','S3Bucket','S3Prefix','GlueRole','BedrockModel','LoginMethod'}
    assert not ({'password','secretAccessKey','accessKeyId','token'} & set(settings))

def test_session_login_uses_browser_and_credential_provider():
    source=(WEB/'AwsSetup.cs').read_text()
    assert 'aws login --profile' in source
    assert 'aws sso login --profile' in source
    assert 'sts", "get-caller-identity' in source
    assert 'Environment.SpecialFolder.UserProfile' in source
    assert 'Credential' not in ''.join(settings for settings in [])
