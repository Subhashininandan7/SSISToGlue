"""Regression guard: profile and region from wizard are used by AWS login."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_cli_profile_region_is_configured_before_browser_login():
    source = (ROOT / "DemoWeb" / "AwsSetup.cs").read_text()
    assert 'aws configure set region {cfg.Region} --profile {cfg.Profile}' in source
    assert '&& {signIn}' in source
    assert 'aws login --profile {cfg.Profile} --region {cfg.Region}' in source
    assert 'aws sso login --profile {cfg.Profile} --region {cfg.Region}' in source

def test_strict_cli_argument_allowlist_remains_enabled():
    source = (ROOT / "DemoWeb" / "AwsSetup.cs").read_text()
    assert 'ProfilePattern.IsMatch(x.Profile' in source
    assert 'RegionPattern.IsMatch(x.Region' in source
    assert 'var error = Validate(cfg)' in source
    assert 'if (error.Length > 0) throw new ArgumentException(error)' in source

def test_migration_engine_is_not_touched():
    source = (ROOT / "DemoWeb" / "Program.cs").read_text()
    assert 'app.MapPost("/api/action"' in source
    assert 'app.MapPost("/api/aws-setup/connect"' in source
