"""Windows AWS SCT Batch adapter adapted from Migration Studio's factory.py.

Real output only. A reviewed script is generated automatically from a locally stored
SSIS source; its existence/exit code never by itself establishes a valid conversion.

The SCT template was observed working in the earlier Studio environment, but AWS
has not guaranteed SSIS-to-Glue coverage for every SCT Batch CLI version.
"""
from __future__ import annotations

import io
import os
import re
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

MAX_ZIP_TOTAL = 30_000_000
MAX_FILE = 8_000_000
MAX_FILES = 400
_ALLOWED = {'.py', '.txt', '.csv', '.json', '.xml', '.sql', '.pdf'}


def discover_runner(environ=None, platform=None):
    environ = environ if environ is not None else os.environ
    platform = platform if platform is not None else sys.platform
    if platform != 'win32':
        return {'available': False, 'platform': platform, 'reason': 'AWS SCT Batch conversion requires Windows in this demo.',
                'cliSupport': 'SSIS_TO_GLUE_UNVERIFIED_ON_THIS_MACHINE'}
    candidates = [environ.get('SCT_BATCH_CMD', ''),
                  r'C:\Program Files\AWS Schema Conversion Tool\app\RunSCTBatch.cmd',
                  r'C:\Program Files (x86)\AWS Schema Conversion Tool\app\RunSCTBatch.cmd',
                  shutil.which('RunSCTBatch.cmd') or '']
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate.strip('"'))
        if path.is_file() and path.name.casefold() == 'runsctbatch.cmd':
            jar = path.parent / 'AWSSchemaConversionToolBatch.jar'
            return {'available': jar.is_file(), 'runner': str(path.resolve()),
                    'jarFound': jar.is_file(), 'platform': platform,
                    'reason': 'Installed batch launcher and JAR found.' if jar.is_file() else 'Batch launcher exists but the AWS SCT Batch JAR is missing.',
                    'cliSupport': 'SSIS_TO_GLUE_UNVERIFIED_UNTIL_REAL_ARTIFACTS'}
    return {'available': False, 'platform': platform, 'reason':
            'RunSCTBatch.cmd not found in the standard SCT installation paths or SCT_BATCH_CMD.',
            'cliSupport': 'SSIS_TO_GLUE_UNVERIFIED_ON_THIS_MACHINE'}


def short_work_root(environ=None, platform=None):
    environ = environ if environ is not None else os.environ
    platform = platform if platform is not None else sys.platform
    configured = environ.get('SSIS_FORGE_SCT_WORK_DIR', '').strip()
    if configured:
        root = Path(configured)
    elif platform == 'win32':
        # Short path avoids deep SCT package output/Windows MAX_PATH problems.
        drive = environ.get('SYSTEMDRIVE', 'C:')
        root = Path('D:\\SFW' if Path('D:\\').is_dir() else drive + '\\SFW')
    else:
        raise RuntimeError('SCT Batch is available only on Windows in this demo')
    if any(x in str(root) for x in ('"', '%', '!', '&', '|', '^', '\n', '\r', "'")):
        raise ValueError('SCT work directory has unsupported batch/script characters')
    if len(str(root)) > 50:
        raise ValueError('SCT work root is too long; configure a short SSIS_FORGE_SCT_WORK_DIR, e.g. D:\\SFW')
    root.mkdir(parents=True, exist_ok=True)
    probe = root / 'write_test.txt'
    probe.write_text('ok\n', encoding='ascii')
    if probe.read_text(encoding='ascii') != 'ok\n':
        raise OSError('SCT workspace could not be read back')
    probe.unlink()
    return root


def safe_sct_value(text):
    if any(c in text for c in ("'", '\r', '\n', '\x00')):
        raise ValueError('SCT source/project path contains an unsupported script character')
    return text.replace('/', '\\')


def create_scenario(project_name, source_folder, project_folder, output_folder, report_folder):
    """Original Studio's SSIS_SOURCE -> virtual Glue scripted conversion workflow."""
    n, src, project, output, report = (safe_sct_value(str(v)) for v in
                                    (project_name, source_folder, project_folder, output_folder, report_folder))
    return (f"CreateProject\n    -name: '{n}'\n    -directory: '{project}'\n/\n\n"
            f"AddSource\n    -name: 'SSIS_SOURCE'\n    -vendor: 'SSIS'\n    -host: '{src}'\n/\n\n"
            "AddServerMapping\n    -sourceTreePath: 'ETL.SSIS_SOURCE'\n    -targetTreePath: 'ETL.<Glue (virtual)>'\n/\n\n"
            "CreateReport\n    -treePath: 'ETL.SSIS_SOURCE.Packages'\n/\n\n"
            f"SaveReportPDF\n    -file: '{report}\\SSIS_Assessment_Report.pdf'\n/\n\n"
            f"SaveReportCSV\n    -directory: '{report}'\n/\n\n"
            "Convert\n    -treePath: 'ETL.SSIS_SOURCE.Packages'\n/\n\n"
            f"SaveToLocalFolder\n    -treePath: 'ETL.<Glue (virtual)>.Package scripts'\n    -directory: '{output}'\n/\n\n"
            "SaveProject\n/\n")


def run_batch(script, runner, log_file, timeout_seconds=1800, platform=None):
    platform = platform if platform is not None else sys.platform
    if platform != 'win32':
        raise RuntimeError('This SCT Batch launcher requires Windows')
    script, runner = Path(script), Path(runner)
    if not script.is_file() or script.stat().st_size < 50:
        raise FileNotFoundError('Generated SCT scenario file missing')
    if not runner.is_file() or runner.name.casefold() != 'runsctbatch.cmd':
        raise FileNotFoundError('AWS SCT launcher missing')
    for value in (str(script), str(runner)):
        if any(c in value for c in ('"', '%', '!', '&', '|', '^', '\r', '\n')):
            raise ValueError('Unsafe Windows batch launcher path')
    wrapper = script.parent / 'launch_sct.cmd'
    wrapper.write_text('@echo off\ncd /d "' + str(runner.parent) + '"\n'
                       'if not exist "' + str(script) + '" exit /b 40\n'
                       'call "' + str(runner) + '" --pathtoscts "' + str(script)
                       + '" --messagelevel INFO --userarguments "-Djdk.xml.xpathExprOpLimit=256"\n'
                       'exit /b %ERRORLEVEL%\n', encoding='ascii')
    log_file = Path(log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open('wb') as log:
        try:
            result = subprocess.run(['cmd.exe', '/d', '/c', str(wrapper)], stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    timeout=timeout_seconds, cwd=str(script.parent), check=False)
        except subprocess.TimeoutExpired:
            return 124
    return result.returncode


def archive_output(folder):
    """Return a real ZIP of actual generated artifacts; never synthesize code."""
    folder = Path(folder)
    if not folder.is_dir():
        return None, 0
    files = sorted((p for p in folder.rglob('*') if p.is_file() and not p.is_symlink()
                    and p.suffix.lower() in _ALLOWED), key=lambda p: str(p).lower())
    if len(files) > MAX_FILES or sum(p.stat().st_size for p in files) > MAX_ZIP_TOTAL:
        raise ValueError('SCT generated output exceeds archive limits')
    pyfiles = [p for p in files if p.suffix.lower() == '.py' and p.stat().st_size > 0]
    if not pyfiles:
        return None, 0
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as dest:
        for file in files:
            if file.stat().st_size > MAX_FILE:
                raise ValueError('SCT artifact exceeds individual file size limit')
            dest.writestr(file.relative_to(folder).as_posix(), file.read_bytes())
    return archive.getvalue(), len(pyfiles)


def convert(source_file, source_name, session_id, runner, *, stage_root=None, runner_fn=None,
            platform=None, environ=None, timeout_seconds=1800):
    """Perform one real SCT Batch attempt and return evidence (not a parity claim).

    runner_fn is injectable only from Python tests; no UI parameter selects a fake runner.
    """
    platform = platform if platform is not None else sys.platform
    if platform != 'win32':
        raise RuntimeError('SCT Batch is unavailable on this operating system')
    runner = Path(runner)
    if not runner.is_file() or runner.name.casefold() != 'runsctbatch.cmd':
        raise FileNotFoundError('AWS SCT Batch launcher was not verified')
    if not (runner.parent / 'AWSSchemaConversionToolBatch.jar').is_file():
        raise FileNotFoundError('AWS SCT Batch engine JAR is missing')
    src = Path(source_file)
    if not src.is_file() or src.suffix.lower() != '.dtsx':
        raise ValueError('Upload an original SSIS .dtsx first')
    root = Path(stage_root) if stage_root is not None else short_work_root(environ=environ, platform=platform)
    root.mkdir(parents=True, exist_ok=True)
    stage = root / (session_id[:8] + '_' + secrets.token_hex(3))
    # Short, fresh and single-use stage: output cannot be inherited from an old run.
    stage.mkdir(exist_ok=False)
    input_folder, output, report, project = (stage / name for name in ('input', 'output', 'reports', 'project'))
    for directory in (input_folder, output, report, project):
        directory.mkdir()
    name = Path(str(source_name).replace('\\', '/')).name
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}\.dtsx', name, flags=re.IGNORECASE):
        name = 'uploaded.dtsx'
    shutil.copyfile(src, input_folder / name)
    scenario = stage / 'workflow.scts'
    content = create_scenario('Forge_' + session_id[:8], input_folder, project, output, report)
    scenario.write_text(content, encoding='utf-8')
    if scenario.read_text(encoding='utf-8') != content:
        raise RuntimeError('Generated SCT scenario could not be verified on disk')
    log = stage / 'sct.log'
    call = runner_fn or run_batch
    code = call(scenario, runner, log, timeout_seconds=timeout_seconds)
    archive, py_count = archive_output(output)
    log_text = log.read_text(encoding='utf-8', errors='replace') if log.is_file() else ''
    status = ('CLI_OUTPUT_OBSERVED_UNVERIFIED_RUNTIME' if code == 0 and archive else
              'CLI_OUTPUT_WITH_ERRORS_REVIEW_ONLY' if archive else
              'CLI_FAILED_NO_PYTHON_OUTPUT_GUI_IMPORT_REQUIRED' if code != 0 else
              'CLI_EXIT_ZERO_NO_PYTHON_OUTPUT_GUI_IMPORT_REQUIRED')
    return {'method': 'REAL_SCT_BATCH_CLI', 'status': status, 'exitCode': code,
            'pythonModules': py_count, 'outputBytes': len(archive) if archive else 0,
            'logTail': log_text[-10_000:], 'archive': archive,
            'scenario': content, 'workDirectory': str(stage),
            'warnings': ['SCT exit status and Python files do not establish SSIS/Glue parity.'],
            'sourceFilename': name}
