"""Regression: selecting a new folder must not append to an automatically restored portfolio."""
from pathlib import Path
import re
import base64
import cli
import pytest
ROOT=Path(__file__).resolve().parents[1]
JS=(ROOT/'DemoWeb/wwwroot/unified.js').read_text('utf-8')
HTML=(ROOT/'DemoWeb/wwwroot/index.html').read_text('utf-8')

def test_fresh_start_not_automatic_resume():
    assert 'show(0);restore().catch' in JS
    assert 'new folder always creates a separate portfolio' in JS
    assert "$('restore').onclick=()=>wrapped(restore)" in JS
    assert 'Start new migration from folder' in HTML

def test_folder_upload_always_creates_independent_portfolio():
    upload=JS.split("$('upload').onclick=",1)[1].split("$('restore').onclick=",1)[0]
    assert "portfolio=await call('bulk-create')" in upload
    assert 'if(!portfolio?.id)' not in upload
    assert 'reuseMatching:true' in upload # Only for duplicate files within same new portfolio
    assert 'portfolio.packages.length' in upload

def test_old_portfolio_is_persisted_when_new_created(tmp_path,monkeypatch):
    monkeypatch.setattr(cli,'HOME',tmp_path)
    old=cli.handle({'action':'bulk-create'})
    package=ROOT/'ssis-packages'/'A_Employees_Active_Bonus_FIXED.dtsx'
    req={'action':'bulk-add','portfolioId':old['id'],'fileName':package.name,
         'contentBase64':base64.b64encode(package.read_bytes()).decode('ascii')}
    cli.handle(req)
    new=cli.handle({'action':'bulk-create'})
    assert old['id'] != new['id']
    assert len(cli.handle({'action':'bulk-status','portfolioId':old['id']})['packages']) == 1
    assert cli.handle({'action':'bulk-status','portfolioId':new['id']})['packages'] == []
