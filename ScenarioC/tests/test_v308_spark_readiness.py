"""Regression: portable Spark preflight must fail before Bedrock, not burn retries."""
from pathlib import Path
import sys
import json
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'engine'))
import unsupported_process_ai as ai


def test_backend_includes_java_tmp_option_and_inherited_env():
    src=(ROOT/'DemoWeb'/'Program.cs').read_text()
    assert 'ConfigureLocalSpark(psi);' in src
    assert 'psi.Environment["TEMP"] = temp;' in src
    assert 'psi.Environment["TMP"] = temp;' in src
    assert 'psi.Environment["TMPDIR"] = temp;' in src
    assert 'psi.Environment["SPARK_LOCAL_DIRS"] = local;' in src
    assert 'psi.Environment["SPARK_SUBMIT_OPTS"]' in src
    assert '-Djava.io.tmpdir=' in src
    assert 'psi.Environment["JAVA_HOME"] = home;' in src


def test_readiness_returns_pass_when_spark_starts(monkeypatch):
    monkeypatch.setattr(ai.subprocess, 'run', lambda *a,**k: Mock(returncode=0,stdout='MIGRATION_FORGE_SPARK_READY\n',stderr='warning'))
    assert ai.check_spark_readiness()['verified'] is True


def test_readiness_fails_with_actionable_java_root_cause(monkeypatch):
    stderr='''at Utils$.createTempDir(Utils.scala:250)\nCaused by: java.nio.file.AccessDeniedException: C:\\temp\\abc\n'''
    monkeypatch.setattr(ai.subprocess, 'run', lambda *a,**k: Mock(returncode=1,stdout='',stderr=stderr))
    result=ai.check_spark_readiness()
    assert result['status']=='FAILED'
    assert result['category']=='ENVIRONMENT'
    assert 'AccessDeniedException' in result['reason']
    assert 'Utils.scala' not in result['reason']
    assert 'C:\\temp' not in result['reason']


def test_spark_java_trace_is_environment_error():
    assert ai._runtime_category('Py4JJavaError org.apache.spark.util.SparkFileUtils.createTempDir')=='ENVIRONMENT'


def test_readiness_check_is_before_paid_bedrock_request():
    code=(ROOT/'engine'/'unsupported_process_ai.py').read_text()
    start=code.index('def propose(')
    readiness=code.index('readiness = check_spark_readiness()',start)
    invoked=code.index('raw,usage=invoke(prompt)',start)
    assert readiness < invoked
    assert 'Bedrock was not invoked' in code


def test_runner_retains_root_cause_before_stack_truncation():
    code=(ROOT/'engine'/'unsupported_process_runner.py').read_text()
    assert "'rootCause':root_cause" in code
    assert 'trace[-1800:]' in code
