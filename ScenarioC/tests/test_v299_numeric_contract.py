import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from unsupported_process_ai import inspect_reference_numeric_contract, GeneratedCodeRejected, inspect_source_format_contract


def source(expression):
    return f'''from pyspark.sql import functions as F
def transform(spark, input_prefix, output_prefix):
    df = spark.read.csv(input_prefix, header=True)
    df = df.withColumn("Bonus", {expression})
    df.write.mode("overwrite").option("header", True).csv(output_prefix)
'''


def test_numeric_reference_rejects_grouping_formatting():
    code=source('F.format_number(F.col("Salary") * F.lit("0.10"), 2)')
    with pytest.raises(GeneratedCodeRejected,match='ungrouped numeric'):
        inspect_reference_numeric_contract(code, {'ActiveEmployees.csv':b'Bonus\n5000.00\n6500.00\n'})


def test_numeric_cast_accepted():
    code=source('(F.col("Salary").cast("decimal(18,2)") * F.lit("0.10").cast("decimal(3,2)")).cast("decimal(18,2)")')
    assert inspect_reference_numeric_contract(code,{'other.csv':b'Bonus\n5000.00\n'})


def test_source_specified_grouped_string_remains_valid():
    code=source('F.format_number(F.col("Salary"), 2)')
    assert inspect_reference_numeric_contract(code, {'x.csv':b'Bonus\n"5,000.00"\n'})


def test_no_baseline_does_not_invent_contract():
    assert inspect_reference_numeric_contract(source('F.format_number(F.col("Salary"), 2)'), {})


def test_unrelated_format_number_is_not_rejected():
    code=source('F.format_number(F.col("Salary"), 2)')
    assert inspect_reference_numeric_contract(code,{'x.csv':b'OtherNumeric\n123.00\n'})


def test_source_fixed_point_rejects_format_number_without_baseline():
    script="Bonus = ($salary * [decimal]0.10).ToString('F2', [System.Globalization.CultureInfo]::InvariantCulture)"
    code=source('F.format_number(F.col("Salary"), 2)')
    with pytest.raises(GeneratedCodeRejected,match='PowerShell'):
        inspect_source_format_contract(code,script)


def test_source_other_field_does_not_invent_bonus_contract():
    script="Total = ($salary).ToString('F2')"
    assert inspect_source_format_contract(source('F.format_number(F.col("Salary"), 2)'),script)


def test_generic_bedrock_retry_from_original_script_without_baseline(tmp_path):
    import json
    from unsupported_process_ai import Workflow
    fix=ROOT/'AI_Demo_Files'
    wf=Workflow(tmp_path)
    wf.analyze((fix/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
               (fix/'original-conversion-output (4).zip').read_bytes(),
               (fix/'transform.ps1').read_bytes(),{}, {})
    bad=source('F.format_number(F.col("Salary") * F.lit("0.1"), 3)')
    good=source('(F.col("Salary").cast("decimal(18,2)") * F.lit("0.10").cast("decimal(3,2)")).cast("decimal(18,2)")')
    prompts=[]
    def model(prompt):
        prompts.append(prompt)
        return json.dumps({'code':bad if len(prompts)==1 else good,'explanation':'Source based translation'})
    result=wf.propose(transport=model,approve_cost=True,approve_transmission=True)
    assert len(prompts)==2
    assert 'ungrouped fixed-point' in prompts[1]
    assert result['codeSha256']
    assert result['validationAttempts'][0]['phase']=='AST_REJECTED'
    assert result['validationAttempts'][1]['status']=='VALIDATED'
    assert not (tmp_path/'candidate.py').exists()
