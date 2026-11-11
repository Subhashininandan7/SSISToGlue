"""Prevent the real package-C Decimal(0.1) regression before human approval."""
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'engine'))
from unsupported_process_ai import inspect_python, GeneratedCodeRejected, Workflow


def make_code(decimal_expression):
    return ("from pyspark.sql.functions import col, format_string\n"
            "from decimal import Decimal\n\n"
            "def transform(spark, input_prefix, output_prefix):\n"
            "    df = spark.read.option('header', 'true').csv(input_prefix + '/Employees.csv')\n"
            "    df = df.withColumn('Bonus', format_string('%.2f', col('Salary') * "
            + decimal_expression + "))\n"
            "    df.write.option('header', 'true').csv(output_prefix + '/ActiveEmployees.csv')\n")


def test_exact_user_failure_is_rejected_before_approval():
    with pytest.raises(GeneratedCodeRejected, match=r'Decimal\(float\)'):
        inspect_python(make_code('Decimal(0.1)'))


def test_exact_string_decimal_is_not_falsely_rejected():
    assert inspect_python(make_code("Decimal('0.10')"))


def test_alias_module_float_rejected():
    code = make_code('Decimal(0.1)').replace('from decimal import Decimal', 'import decimal as dec').replace('Decimal(0.1)', 'dec.Decimal(0.1)')
    with pytest.raises(GeneratedCodeRejected, match=r'Decimal\(float\)'):
        inspect_python(code)


def test_model_must_regenerate_instead_of_offering_broken_diff(tmp_path):
    src = ROOT / 'AI_Demo_Files'
    flow = Workflow(tmp_path)
    flow.analyze((src/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
                 (src/'original-conversion-output (4).zip').read_bytes(),
                 (src/'transform.ps1').read_bytes(), {}, {})
    prompts = []
    def transport(prompt):
        prompts.append(prompt)
        code = make_code('Decimal(0.1)' if len(prompts) == 1 else "Decimal('0.10')")
        return json.dumps({'code':code,'explanation':'test'})
    proposal = flow.propose(transport=transport, approve_cost=True, approve_transmission=True)
    assert len(prompts) == 2
    assert 'Decimal(float)' in prompts[1]
    assert proposal['validationAttempts'][0]['phase'] == 'AST_REJECTED'
    assert 'Decimal(0.1)' not in json.loads((tmp_path/'proposal.json').read_text())['code']
    assert not (tmp_path/'candidate.py').exists()
