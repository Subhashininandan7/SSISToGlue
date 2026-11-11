from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from quickflow import repair_strategy_summary

def test_simple_package_does_not_need_ai():
    report=repair_strategy_summary({'modules':[{'name':'simple','source':'def run(): pass'}], 'blockers':[]})
    assert report['nextAction']=='REVIEW_STATIC_CANDIDATE'
    assert report['strategies']==[]

def test_generic_defect_does_not_claim_join():
    report=repair_strategy_summary({'modules':[{'name':'broken','source':'def broken(: pass'}], 'blockers':['Python syntax error']})
    assert report['strategies'][0]['type']=='NON_SEMANTIC_STATIC_DEFECTS'
    assert all(x['type']!='SSIS_MERGE_JOIN' for x in report['strategies'])

def test_ui_not_hardwired_to_scenario_b():
    ui=(Path(__file__).resolve().parents[1]/'DemoWeb/wwwroot/index.html').read_text()
    assert 'Generate AI fixes where needed' in ui
    assert 'Generate one-line Merge Join proposal' not in ui
    assert 'For the new CSV-only Scenario B' not in ui
