"""Execute repaired SCT modules locally in real PySpark, if installed.

Only controlled Scenario A: local input is staged, local output is isolated;
SSIS source and the original SCT output are untouched. A failed Spark run is a
hard blocker, never represented as a successful conversion.
"""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from scenarios import read_csv
from validation import compare
from sct_candidate import sha


def check(candidate_dir,fixtures,workspace,*,run=None):
    candidate_dir=Path(candidate_dir);fixtures=Path(fixtures);workspace=Path(workspace)
    prep=json.loads((candidate_dir/'preflight.json').read_text(encoding='utf-8'))
    if prep.get('status')!='SCT_SCENARIO_A_PREFLIGHT_READY_NOT_RUN':
        raise ValueError('SCT preflight must complete first')
    if sha((candidate_dir/'sct_modules.zip').read_bytes())!=prep['pyModulesZipSha256']:
        raise ValueError('SCT candidate ZIP changed since preflight')
    output=workspace/'local-sct-output'
    output.mkdir(parents=True,exist_ok=True)
    local=output/'ActiveEmployees.csv'
    if local.exists():raise ValueError('Local candidate output already exists; a fresh session is required')
    result_file=output/'spark-result.json'
    runner=Path(__file__).with_name('spark_runner_a.py')
    if not runner.is_file():raise ValueError('Missing local Spark test runner')
    cmd=[sys.executable,str(runner),str(candidate_dir/'sct_modules.zip'),str(fixtures/'input'/'Employees.csv'),str(local),str(result_file)]
    invoke=run or subprocess.run
    try:
        process=invoke(cmd,capture_output=True,timeout=240,check=False,cwd=str(candidate_dir))
    except subprocess.TimeoutExpired:
        return {'status':'LOCAL_SPARK_TIMEOUT','localSparkParity':False}
    (output/'spark-process.log').write_bytes((process.stdout or b'')[-100_000:]+b'\n'+(process.stderr or b'')[-100_000:])
    if process.returncode!=0:
        # Distinguish actual Spark SQL failures from missing Java, Python or Spark.
        # The detailed log stays local; only a non-sensitive failure code can be sent to Bedrock.
        stderr=(process.stderr or b'')[-100_000:].decode('utf-8','replace').lower()
        if any(mark in stderr for mark in ('modulenotfounderror','no module named','java_gateway_exited','java gateway process exited',
                                           'java_home is not set','java missing','winerror 2','classnotfoundexception')):
            failure_code='ENVIRONMENT_OR_DEPENDENCY_FAILURE'
        elif any(mark in stderr for mark in ('analysisexception','parseexception','cannot resolve',
                                             'syntax error at or near','[unresolved_column]','[parse_syntax_error]')):
            failure_code='SPARK_SQL_ANALYSIS_FAILURE'
        else:
            failure_code='UNCLASSIFIED_LOCAL_EXECUTION_FAILURE'
        return {'status':'LOCAL_SPARK_EXECUTION_FAILED','failureCode':failure_code,
                'localSparkParity':False,'exitCode':process.returncode,
                'log':'local-sct-output/spark-process.log'}
    if not result_file.is_file():raise ValueError('Spark process exited without verified results file')
    runner_result=json.loads(result_file.read_text())
    if not local.is_dir():raise ValueError('PySpark did not generate expected CSV output directory')
    parts=list(local.glob('part-*.csv'))
    if not parts or len(parts)>25:raise ValueError('Spark did not generate bounded CSV part files')
    rows=[]
    for item in parts:
        if item.stat().st_size>2_000_000:raise ValueError('Spark output too large')
        with item.open(encoding='utf-8-sig',newline='') as f:
            rows.extend(csv.DictReader(f))
    parity=compare(read_csv(fixtures/'expected'/'ActiveEmployees.csv'),rows)
    return {'status':'LOCAL_SCT_PYSPARK_OUTPUT_MATCHED' if parity['match'] else 'LOCAL_SCT_PYSPARK_OUTPUT_MISMATCH',
            'localSparkParity':bool(parity['match']),'rows':len(rows),
            'pySparkVersion':runner_result.get('pysparkVersion'),
            'rowParity':parity,'candidateZipSha256':prep['pyModulesZipSha256'],
            'outputPath':str(local),'runtime':'REAL_LOCAL_PYSPARK_NOT_AWS_GLUE'}
