"""Regression tests for response envelope and local-child Spark setup."""
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from unsupported_process_ai import parse_bedrock_proposal, GeneratedCodeRejected, Workflow

VALID_CODE = '''from pyspark.sql import functions as F

def transform(spark, input_prefix, output_prefix):
    df = spark.read.option("header", "true").csv(input_prefix + "/Employees.csv")
    df.filter(F.col("Status") == "Active").write.mode("overwrite").option("header", "true").csv(output_prefix + "/ActiveEmployees.csv")
'''
ANSWER = {'code': VALID_CODE, 'explanation': 'Mapped using source logic'}

@pytest.mark.parametrize('format_answer', [
    lambda s: s,
    lambda s: '```json\n' + s + '\n```',
    lambda s: 'The translation follows.\n' + s + '\nEnd of response.',
    lambda s: json.dumps(s),
])
def test_valid_envelopes(format_answer):
    assert parse_bedrock_proposal(format_answer(json.dumps(ANSWER))) == ANSWER

@pytest.mark.parametrize('invalid', [
    '', 'not JSON', '{"code": "unfinished',
    json.dumps({'code': 'hello'}),
    json.dumps(ANSWER) + '\n' + json.dumps(ANSWER),
])
def test_invalid_or_ambiguous_rejected(invalid):
    with pytest.raises(GeneratedCodeRejected):
        parse_bedrock_proposal(invalid)

def test_workflow_accepts_fenced_bedrock_json(tmp_path):
    fix=ROOT/'AI_Demo_Files'; wf=Workflow(tmp_path)
    wf.analyze((fix/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
               (fix/'original-conversion-output (4).zip').read_bytes(),
               (fix/'transform.ps1').read_bytes(),{}, {})
    p=wf.propose(transport=lambda _: '```json\n'+json.dumps(ANSWER)+'\n```',
                 approve_cost=True, approve_transmission=True)
    assert p['status']=='AI_PATCH_REVIEW_ONLY'

def test_spark_environment_is_process_local_and_configured():
    src=(ROOT/'DemoWeb'/'Program.cs').read_text(encoding='utf-8')
    assert 'ConfigureLocalSpark(psi);' in src
    assert 'psi.Environment["TEMP"] = temp;' in src
    assert 'psi.Environment["TMP"] = temp;' in src
    assert 'psi.Environment["SPARK_LOCAL_DIRS"] = local;' in src
    assert 'psi.Environment["HADOOP_HOME"] = hadoop;' in src
    assert 'psi.Environment["AWS_PROFILE"] = aws.Profile;' in src
    assert 'psi.Environment["AWS_DEFAULT_REGION"] = aws.Region;' in src
