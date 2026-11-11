"""Regression for 3.0.9 repeated Column-as-callable proposal failures.

No AWS call and no Spark installation required: static analysis and bounded
repair feedback are tested deterministically.
"""
import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from unsupported_process_ai import (inspect_python, GeneratedCodeRejected,
                                    _runtime_category, preflight_local, Workflow)


def candidate(expression):
    return ('from pyspark.sql import functions as F\n\n'
            'def transform(spark, input_prefix, output_prefix):\n'
            '    df = spark.read.option("header", "true").csv(input_prefix + "/Rows.csv")\n'
            f'    out = df.withColumn("Value", {expression})\n'
            '    out.write.mode("overwrite").option("header", "true").csv(output_prefix + "/Output.csv")\n')


@pytest.mark.parametrize('expr', [
    'F.col("Name")()',
    'F.col("Name").strip()',
    'F.col("Name").lower()',
    'F.col("Salary").cast("decimal(18,2)")()',
])
def test_deterministically_invalid_column_calls_rejected_before_spark(expr):
    with pytest.raises(GeneratedCodeRejected, match='Spark Column'):
        inspect_python(candidate(expr))


@pytest.mark.parametrize('expr', [
    'F.trim(F.col("Name"))',
    'F.lower(F.col("Name"))',
    'F.col("Name").cast("string").alias("Value")',
    'F.when(F.col("Salary") > 0, F.col("Salary")).otherwise(F.lit(0))',
    'F.col("Name").startswith("A")',
])
def test_legitimate_spark_expressions_still_pass(expr):
    assert inspect_python(candidate(expr)) is True


def test_typeerror_column_callable_classifies_as_generated_code():
    assert _runtime_category("TypeError: 'Column' object is not callable") == 'CODE_RUNTIME'


def test_preflight_preserves_failed_generated_location_for_model_feedback(tmp_path, monkeypatch):
    import unsupported_process_ai as ai
    root = tmp_path / 'session'
    (root / 'input').mkdir(parents=True)
    (root / 'input' / 'Rows.csv').write_text('Value\n1\n')
    (root / 'manifest.json').write_text(json.dumps({'inputs': {'Rows.csv': ['Value']}}))
    class Proc:
        returncode = 1
    def fake_run(cmd, **kwargs):
        Path(cmd[3]).write_text(json.dumps({
            'status': 'FAILED', 'exceptionType': 'TypeError',
            'error': "'Column' object is not callable",
            'generatedLocation': {'line': 7, 'expression': "df.withColumn('Value', F.col('Salary')())"},
        }))
        return Proc()
    monkeypatch.setattr(ai.subprocess, 'run', fake_run)
    result = preflight_local(root, candidate('F.col("Name")'))
    assert result['category'] == 'CODE_RUNTIME'
    assert 'line 7' in result['reason']
    assert 'failing expression' in result['reason']


def test_ai_retry_corrects_failing_column_call_using_static_evidence(tmp_path):
    source = ROOT / 'AI_Demo_Files'
    flow = Workflow(tmp_path)
    flow.analyze((source/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
        (source/'original-conversion-output (4).zip').read_bytes(),
        (source/'transform.ps1').read_bytes(), {}, {})
    prompts = []
    def transport(prompt):
        prompts.append(prompt)
        code = candidate('F.col("Name").strip()' if len(prompts)==1 else 'F.trim(F.col("Name"))')
        return json.dumps({'code': code, 'explanation': 'source-grounded string transformation'})
    result = flow.propose(transport=transport, approve_cost=True, approve_transmission=True)
    assert len(prompts) == 2
    assert result['status'] == 'AI_PATCH_REVIEW_ONLY'
    assert 'Spark Column' in prompts[1]
    assert result['validationAttempts'][0]['phase'] == 'AST_REJECTED'
    assert result['validationAttempts'][1]['phase'] == 'RUNTIME_UNVERIFIED'
