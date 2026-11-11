"""Bedrock prompt must be driven by original evidence, not scenario names."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
from unsupported_process_ai import Workflow
ROOT=Path(__file__).resolve().parents[1]
FILES=ROOT/'AI_Demo_Files'
CODE='''from pyspark.sql import functions as F\n\ndef transform(spark, input_prefix, output_prefix):\n    df=spark.read.option("header","true").csv(input_prefix + "/Transactions.csv")\n    df.write.mode("overwrite").option("header","true").csv(output_prefix + "/TransactionsClean.csv")\n'''

def test_source_driven_prompt_no_hardcoded_contract(tmp_path):
    wf=Workflow(tmp_path)
    custom_script=b'''$rows = Import-Csv "Transactions.csv"\n$rows | Export-Csv "TransactionsClean.csv" -NoTypeInformation'''
    wf.analyze((FILES/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
               (FILES/'original-conversion-output (4).zip').read_bytes(),
               custom_script,{}, {},script_name='transform.ps1')
    seen=[]
    wf.propose(approve_cost=True,approve_transmission=True,
       transport=lambda p:(seen.append(p) or json.dumps({'code':CODE,'explanation':'source-driven'})))
    prompt=seen[0]
    assert 'Transactions.csv' in prompt
    assert 'TransactionsClean.csv' in prompt
    # Original task descriptions may contain those strings; the PROMPT itself must
    # not enforce those names, and source disagreements must be reported.
    assert 'Executable source statements take priority' in prompt
    assert 'Do not assume the package name' in prompt
    assert 'No executable top-level statements' in prompt
    assert 'string' in prompt.lower() and 'cast' in prompt.lower()
    assert 'Spark .csv(path) writes a DIRECTORY' in prompt
    assert '25029' in prompt
    assert 'APPROVED_PENDING_RUNTIME_PARITY' not in prompt

def test_prompt_includes_original_metadata_and_no_example_rows(tmp_path):
    wf=Workflow(tmp_path)
    wf.analyze((FILES/'C_Unsupported_Execute_Process_AI_Demo.dtsx').read_bytes(),
               (FILES/'original-conversion-output (4).zip').read_bytes(),
               (FILES/'transform.ps1').read_bytes(),
               {'Employees.csv':(FILES/'Employees.csv').read_bytes()}, {})
    seen=[]
    wf.propose(approve_cost=True,approve_transmission=True,
       transport=lambda p:(seen.append(p) or json.dumps({'code':CODE,'explanation':'review only'})))
    assert 'Where-Object' in seen[0]
    assert 'Microsoft.ExecuteProcess' in seen[0]
    assert '25029' in seen[0]
    assert 'Ravi' not in seen[0]
    assert 'approvedExternalSource' in seen[0]
