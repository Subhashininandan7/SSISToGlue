import json
import sys
from pathlib import Path
from unittest.mock import patch
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from unsupported_process_ai import Workflow, sha

FIX=ROOT/'AI_Demo_Files'
CODE='from pyspark.sql import functions as F\n\ndef transform(spark, input_prefix, output_prefix):\n    df=spark.read.option("header","true").csv(input_prefix+"/Employees.csv")\n    df.write.mode("overwrite").option("header","true").csv(output_prefix+"/ActiveEmployees.csv")\n'

def ready(tmp_path):
    w=Workflow(tmp_path)
    w.analyze((FIX/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
      (FIX/'original-conversion-output (4).zip').read_bytes(),
      (FIX/'transform.ps1').read_bytes(),{}, {})
    w.propose(approve_cost=True,approve_transmission=True,
       transport=lambda _:json.dumps({'code':CODE,'explanation':'review-only'}))
    w.approve(sha(CODE.encode()),True)
    return w

def test_spark_stdout_can_contain_multiple_json_objects(tmp_path):
    w=ready(tmp_path)
    def run(cmd,**kwargs):
        Path(cmd[3]).write_text(json.dumps({'status':'OUTPUT_GENERATED','outputs':[{'name':'ActiveEmployees.csv','actualRows':3}]}))
        return type('Completed',(),{'returncode':0,'stdout':'{"progress":1}\n{"progress":2}\n','stderr':'Spark logs'})()
    with patch('unsupported_process_ai.subprocess.run',side_effect=run):
        result=w.validate()
    assert result['status']=='OUTPUT_GENERATED'
    assert result['deployAllowed'] is False
    assert json.loads((tmp_path/'manifest.json').read_text())['status']=='LOCAL_OUTPUT_GENERATED'

def test_missing_structured_result_fails_closed(tmp_path):
    w=ready(tmp_path)
    mocked=type('Completed',(),{'returncode':0,'stdout':'{"status":"MATCH"}','stderr':''})()
    with patch('unsupported_process_ai.subprocess.run',return_value=mocked):
        result=w.validate()
    assert result['status']=='FAILED'
    assert 'did not produce' in result['error']
    assert json.loads((tmp_path/'manifest.json').read_text())['status']=='RUNTIME_VALIDATION_FAILED'

def test_malformed_structured_result_fails_closed(tmp_path):
    w=ready(tmp_path)
    def run(cmd,**kwargs):
        Path(cmd[3]).write_text('{"ok":true}\n{"more":true}')
        return type('Completed',(),{'returncode':0,'stdout':'','stderr':''})()
    with patch('unsupported_process_ai.subprocess.run',side_effect=run):
        result=w.validate()
    assert result['status']=='FAILED'
    assert 'Invalid local Spark runner result' in result['error']
