"""Regression guards for the portable runtime layer, which does not touch engine logic."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'DemoWeb'


def test_runtime_uses_local_appdata_and_never_assumes_user_drive():
    code = (WEB / 'PortableRuntime.cs').read_text(encoding='utf8')
    assert 'Environment.SpecialFolder.LocalApplicationData' in code
    assert '"MigrationForge", "Runtime"' in code
    assert 'Directory.CreateDirectory(temp)' in code
    assert 'Directory.CreateDirectory(spark)' in code
    assert 'MIGRATION_FORGE_SPARK_TEMP' in code
    assert r'D:\Hadoop' not in code
    assert r'D:\MigrationForgeSparkTemp' not in code


def test_runtime_checks_and_official_downloads_are_explicit():
    code = (WEB / 'PortableRuntime.cs').read_text(encoding='utf8')
    for term in ('FindExecutable', 'PythonPath', 'JavaPath', 'AwsPath', 'HadoopHome',
                 'ProbeAsync', 'EnsureScratch', 'LocalSparkReady'):
        assert term in code
    assert 'python.org/downloads/windows/' in code
    assert 'adoptium.net/' in code
    assert 'docs.aws.amazon.com/cli/' in code
    assert 'SchemaConversionTool' in code
    assert 'spark.apache.org/' in code
    assert 'Process.Start(start)' in code
    assert 'UseShellExecute = false' in code


def test_python_process_inherits_local_environment_without_mutating_visual_studio():
    src = (WEB / 'Program.cs').read_text(encoding='utf8')
    assert 'app.MapGet("/api/runtime/check"' in src
    assert 'ConfigureLocalSpark(psi)' in src
    assert 'PortableRuntime.EnsureScratch()' in src
    assert 'PortableRuntime.JavaPath()' in src
    assert 'PortableRuntime.HadoopHome()' in src
    assert 'psi.Environment["SPARK_LOCAL_DIRS"] = local;' in src
    assert 'psi.Environment["PYSPARK_PYTHON"] = python;' in src
    assert 'Environment.SetEnvironmentVariable' not in src
    assert r'D:\Hadoop' not in src


def test_runtime_ui_and_install_pages_are_separate_from_workflow():
    html = (WEB / 'wwwroot' / 'index.html').read_text(encoding='utf8')
    js = (WEB / 'wwwroot' / 'runtime-setup.js').read_text(encoding='utf8')
    assert 'runtime-open' in html
    assert 'runtime-results' in html
    assert 'runtime-setup.js?v=303' in html
    assert "'/api/runtime/check'" in js
    assert 'expectedUrls' in js
    assert "rel = 'noopener noreferrer'" in js
    assert 'unified.js?v=298' in html
