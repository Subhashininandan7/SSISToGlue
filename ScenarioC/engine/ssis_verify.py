"""Windows-only dtexec smoke check for the CONTROLLED Scenario A package.
This provides real execution evidence only when dtexec ran and real output matched.
"""
from __future__ import annotations
import csv
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from sct_candidate import contract_for_package, CandidateBlocked, D
from validation import compare
from scenarios import read_csv


def discover_dtexec():
    if sys.platform!='win32':return None
    candidates=[shutil.which('dtexec.exe')]
    program=os.environ.get('ProgramFiles',r'C:\Program Files')
    for ver in ('160','170','150'):
        candidates.append(str(Path(program)/'Microsoft SQL Server'/ver/'DTS'/'Binn'/'DTExec.exe'))
    return next((str(Path(c)) for c in candidates if c and Path(c).is_file()),None)


def isolated_package(source_file,input_csv,output_csv,path):
    contract_for_package(source_file)
    tree=ET.parse(source_file)
    r=tree.getroot()
    for conn in r.findall(D+'ConnectionManagers/'+D+'ConnectionManager'):
        sub=conn.find(D+'ObjectData/'+D+'ConnectionManager')
        if conn.get(D+'ObjectName')=='Employees Input':sub.set(D+'ConnectionString',str(input_csv))
        elif conn.get(D+'ObjectName')=='ActiveEmployees Output':sub.set(D+'ConnectionString',str(output_csv))
    tree.write(path,encoding='utf-8',xml_declaration=True)


def execute(source_file, fixtures, session_folder, *,runner=None,run=None,timeout=180):
    source_file=Path(source_file);fixtures=Path(fixtures);session_folder=Path(session_folder)
    contract_for_package(source_file)
    # Only execute the exact distributed, read-only audited Scenario A fixture.
    baseline=Path(__file__).resolve().parent.parent/'ssis-packages'/'A_Employees_Active_Bonus_FIXED.dtsx'
    if hashlib.sha256(source_file.read_bytes()).digest()!=hashlib.sha256(baseline.read_bytes()).digest():
        raise CandidateBlocked('Local SSIS execution is restricted to the exact supplied Scenario A FIXED fixture; use a matching uploaded file')
    cmd=runner if runner is not None else discover_dtexec()
    if not cmd or not Path(cmd).is_file():
        return {'status':'BLOCKED_DTEXEC_NOT_INSTALLED','ssdtRuntimeVerified':False,
                'nextStep':'Install the SSIS runtime/dtexec, or execute in SSDT and submit the resulting output with explicit provenance.'}
    input_file=fixtures/'input'/'Employees.csv'
    if not input_file.is_file():raise ValueError('Missing Employees.csv')
    target=session_folder/'ssis-validation'
    target.mkdir(parents=True,exist_ok=True)
    out_csv=target/'ActiveEmployees_SSIS.csv'
    if out_csv.exists(): raise ValueError('An SSIS output already exists in this session; create a new session to avoid stale data')
    run_file=target/'isolated_for_dtexec.dtsx'
    isolated_package(source_file,input_file.resolve(),out_csv.resolve(),run_file)
    invoke=run or subprocess.run
    try:
        result=invoke([str(cmd),'/FILE',str(run_file),'/REPORTING','E'],
                      timeout=timeout,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                      stderr=subprocess.STDOUT,check=False)
    except subprocess.TimeoutExpired:
        return {'status':'SSIS_EXECUTION_TIMEOUT','ssdtRuntimeVerified':False}
    output=result.stdout or b''
    (target/'dtexec.log').write_bytes(output[:250_000])
    if result.returncode!=0 or not out_csv.is_file():
        return {'status':'SSIS_EXECUTION_FAILED','ssdtRuntimeVerified':False,
                'exitCode':result.returncode,'hasOutput':out_csv.is_file(),
                'log':'ssis-validation/dtexec.log'}
    actual=read_csv(out_csv)
    oracle=read_csv(fixtures/'expected'/'ActiveEmployees.csv')
    parity=compare(oracle,actual)
    return {'status':'SSIS_DTS_EXECUTED_PARITY_VERIFIED' if parity['match'] else 'SSIS_EXECUTED_OUTPUT_MISMATCH',
            'sourceSha256':hashlib.sha256(source_file.read_bytes()).hexdigest(),
            'ssdtRuntimeVerified':bool(parity['match']), 'executionType':'ACTUAL_WINDOWS_DTEXEC',
            'exitCode':result.returncode,'outputSha256':hashlib.sha256(out_csv.read_bytes()).hexdigest(),
            'rowParity':parity,'outputFile':str(out_csv),'log':'ssis-validation/dtexec.log'}
