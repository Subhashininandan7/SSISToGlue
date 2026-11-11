"""Bedrock contract regression for generated helper defs and F2 output.

Synthetic responses: do not imply live AWS was exercised.
"""
import json
import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
from unsupported_process_ai import (Workflow, inspect_python, normalize_model_entrypoint,
    normalize_source_fixed_point,parse_bedrock_proposal, GeneratedCodeRejected,sha)
FIX=ROOT/'AI_Demo_Files'
SOURCE=(FIX/'transform.ps1').read_text(encoding='utf-8')

CODE='''from pyspark.sql import functions as F

def calculate_bonus(df):
    return df.withColumn("Bonus", F.format_number(F.col("Salary").cast("decimal(18,2)") * F.lit("0.10"), 2))

def transform(spark, input_prefix, output_prefix):
    df = spark.read.option("header", "true").csv(input_prefix+"/Employees.csv")
    calculate_bonus(df).write.mode("overwrite").option("header", "true").csv(output_prefix+"/ActiveEmployees.csv")
'''

def setup(tmp_path):
    w=Workflow(tmp_path)
    w.analyze((FIX/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
        (FIX/'original-conversion-output (4).zip').read_bytes(),
        (FIX/'transform.ps1').read_bytes(), {}, {})
    return w

def test_one_transform_with_one_safe_helper_is_valid():
    assert inspect_python(CODE)

def test_source_contract_requires_f2_and_local_fix_is_scoped():
    fixed,changes=normalize_source_fixed_point(CODE,SOURCE)
    assert changes == [{'column':'Bonus','precision':2,'reason':'PowerShell source-defined ungrouped fixed-point output'}]
    assert 'format_number(' not in fixed
    assert "cast('decimal(38,2)').cast('string')" in fixed
    assert 'format_string(' not in fixed
    assert inspect_python(fixed)

def test_end_to_end_propose_one_call_normalizes_numeric_with_safe_helper(tmp_path):
    prompts=[]
    w=setup(tmp_path)
    r=w.propose(transport=lambda p: prompts.append(p) or json.dumps({'code':CODE,'explanation':'from PowerShell'}),
        approve_cost=True,approve_transmission=True)
    assert len(prompts)==1
    assert r['status']=='AI_PATCH_REVIEW_ONLY'
    assert r['validationAttempts'][0]['localNormalization']['fixedPointColumns']==['Bonus']
    proposal=json.loads((tmp_path/'proposal.json').read_text())
    assert "cast('decimal(38,2)').cast('string')" in proposal['code'] and 'format_number(' not in proposal['code']
    assert proposal['codeSha256']==sha(proposal['code'].encode())
    assert not (tmp_path/'candidate.py').exists()

def test_single_alternative_name_normalized_only_if_signature_matches():
    code='def migrate(spark, input_prefix, output_prefix):\n    return None\n'
    fixed,changed=normalize_model_entrypoint(code)
    assert changed and 'def transform(' in fixed and inspect_python(fixed)
    bad='def migrate(data):\n    return data\n'
    assert normalize_model_entrypoint(bad)==(bad,False)

def test_plain_python_with_one_alternative_entry_is_extractable():
    raw='```python\ndef migrate(spark, input_prefix, output_prefix):\n    return None\n```'
    proposal=parse_bedrock_proposal(raw)
    fixed,changed=normalize_model_entrypoint(proposal['code'])
    assert changed and inspect_python(fixed)

def test_duplicate_transform_remains_rejected():
    bad='def transform(spark,input_prefix,output_prefix):\n    pass\ndef transform(spark,input_prefix,output_prefix):\n    pass\n'
    with pytest.raises(GeneratedCodeRejected): inspect_python(bad)

def test_multiple_non_transform_functions_not_guessed():
    bad='def migrate(spark,input_prefix,output_prefix):\n    pass\ndef migrate_two(spark,input_prefix,output_prefix):\n    pass\n'
    assert normalize_model_entrypoint(bad)==(bad,False)

def test_unrelated_field_and_incorrect_precision_not_silently_rewritten():
    bad=CODE.replace('"Bonus"','"Other"')
    assert normalize_source_fixed_point(bad,SOURCE)==(bad,[])
    bad2=CODE.replace('F.lit("0.10"), 2)', 'F.lit("0.10"), 3)')
    assert normalize_source_fixed_point(bad2,SOURCE)==(bad2,[])

def test_reject_untrusted_extra_top_level_code_and_imports():
    with pytest.raises(GeneratedCodeRejected): inspect_python(CODE+'\nprint("Hello")\n')
    with pytest.raises(GeneratedCodeRejected): inspect_python('import os\n'+CODE)


def test_direct_function_import_is_rewritten_consistently():
    code=CODE.replace('from pyspark.sql import functions as F', 'from pyspark.sql.functions import format_number as fmt')
    code=code.replace('F.format_number(', 'fmt(')
    fixed,changes=normalize_source_fixed_point(code,SOURCE)
    assert changes and "cast('decimal(38,2)').cast('string')" in fixed
    assert 'fmt(' not in fixed and inspect_python(fixed)

def test_direct_function_without_alias_is_rewritten_consistently():
    code=CODE.replace('from pyspark.sql import functions as F', 'from pyspark.sql.functions import format_number')
    code=code.replace('F.format_number(', 'format_number(')
    fixed,changes=normalize_source_fixed_point(code,SOURCE)
    assert changes and "cast('decimal(38,2)').cast('string')" in fixed
    assert 'format_number(' not in fixed and inspect_python(fixed)
