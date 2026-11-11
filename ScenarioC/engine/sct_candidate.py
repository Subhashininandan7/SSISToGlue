"""Fail-closed, provenance-preserving SCT code repair for Scenario A ONLY.

The package keeps the SCT-generated entrypoint, SQL filter, derived bonus and
output DataFrame sequence. Exact known SCT defects are patched deterministically.
This never promotes a Bedrock suggestion or a standalone reference job.
"""
from __future__ import annotations
import ast
import difflib
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

class CandidateBlocked(ValueError):pass

NAMESPACE='www.microsoft.com/SqlServer/Dts'
D='{'+NAMESPACE+'}'
FILTER_MODULE='filter_x0020_active_x0020_and_x0020_add_x0020_bonus'
MAIN_MODULE='a_employees_active_bonus'
HEADER=['EmployeeID','EmployeeName','Department','Salary','Bonus']


def sha(data):return hashlib.sha256(data).hexdigest()


def contract_for_package(path):
    tree=ET.parse(path); root=tree.getroot()
    if root.get(D+'ObjectName')!='A_Employees_Active_Bonus':
        raise CandidateBlocked('Not the approved Scenario A SSIS package')
    cms=root.find(D+'ConnectionManagers')
    if cms is None: raise CandidateBlocked('No SSIS connection managers')
    c={e.get(D+'ObjectName'):e for e in cms.findall(D+'ConnectionManager')}
    if set(c)!={'Employees Input','ActiveEmployees Output'}:
        raise CandidateBlocked('Unexpected SSIS connection managers')
    strings={}
    for key,v in c.items():
        nested=v.find(D+'ObjectData/'+D+'ConnectionManager')
        if not (v.get(D+'DTSID') and v.get(D+'refId') and nested is not None):
            raise CandidateBlocked('SSIS connection identity or configuration missing')
        strings[key]=nested.get(D+'ConnectionString','')
    if not strings['Employees Input'].lower().endswith(r'fixtures\input\employees.csv'):
        raise CandidateBlocked('SSIS input does not use Scenario A CSV fixture')
    if not strings['ActiveEmployees Output'].lower().endswith(r'fixtures\ssis-output\activeemployees_ssis.csv'):
        raise CandidateBlocked('SSIS output may overwrite independent expected baseline; use the FIXED package')
    task=root.find('.//'+D+'Executable[@'+D+'ObjectName="Filter Active and Add Bonus"]')
    if task is None:raise CandidateBlocked('SSIS Data Flow Task not found')
    comps=task.findall('.//component')
    target_types=['Microsoft.FlatFileSource','Microsoft.ConditionalSplit','Microsoft.DerivedColumn','Microsoft.FlatFileDestination']
    if [x.get('componentClassID') for x in comps]!=target_types:
        raise CandidateBlocked('Unsupported Scenario A SSIS topology')
    for comp in comps:
        for conn in comp.findall('connections/connection'):
            if not any(conn.get('connectionManagerRefId')==v.get(D+'refId') and
                       conn.get('connectionManagerID')==v.get(D+'refId') for v in c.values()):
                raise CandidateBlocked('SSIS component connector reference is inconsistent')
    exprs=[x.text or '' for x in task.findall('.//property') if x.get('name')=='FriendlyExpression']
    if not any('Status == "Active"' in x for x in exprs) or not any('Salary * 0.10' in x for x in exprs):
        raise CandidateBlocked('Original SSIS filter/bonus semantics not verified')
    return {'sourceSha256':sha(Path(path).read_bytes()),'dataflowComponents':target_types,
            'input':strings['Employees Input'],'ssisOutput':strings['ActiveEmployees Output'],
            'filter':'Status == "Active"','bonus':'Salary * 0.10','outputFields':HEADER}


def module_paths(manifest, source_file_name):
    """Resolve the *actual* SCT package stem against the reviewed source filename.

    The previous v1.4 tests use an authentic earlier CLI output generated before
    the corrected fixture was renamed. Preserve that verified legacy mode.
    Corrected *_FIXED uploads may produce either canonical or _fixed modules;
    uncorrected filenames may never claim the _fixed module variant.
    """
    upload_stem=Path(str(source_file_name).replace('\\','/')).stem.lower()
    if upload_stem not in (MAIN_MODULE,MAIN_MODULE+'_fixed'):
        raise CandidateBlocked('Unsupported Scenario A filename: '+upload_stem)
    allowed={MAIN_MODULE}
    if upload_stem==MAIN_MODULE+'_fixed':allowed.add(upload_stem)
    expected={MAIN_MODULE:None,FILTER_MODULE:None,'variables':None}
    found_stem=None
    for entry in manifest:
        original=entry['originalPath'].replace('\\','/').lower()
        if not original.endswith('.py') or 'create-body-script/' not in original:
            raise CandidateBlocked('Unrecognized generated source file path: '+original)
        suffix=Path(original).name
        match=re.fullmatch(r'\d+\. (a_employees_active_bonus(?:_fixed)?)\.([a-z0-9_]+)\.py',suffix)
        if not match or match.group(1) not in allowed:
            raise CandidateBlocked('Generated SCT module does not match reviewed Scenario A package: '+suffix)
        stem,module=match.groups()
        if found_stem and stem!=found_stem:
            raise CandidateBlocked('Mixed SCT package stems detected; source ZIP is inconsistent')
        found_stem=stem
        accepted={stem:MAIN_MODULE,FILTER_MODULE:FILTER_MODULE,'variables':'variables'}
        if module not in accepted:raise CandidateBlocked('Unknown generated SCT module '+suffix)
        name=accepted[module]
        if expected[name] is not None:raise CandidateBlocked('Duplicate SCT module '+name)
        expected[name]=entry['file']
    if any(not x for x in expected.values()) or len(manifest)!=3:
        raise CandidateBlocked('Scenario A requires exactly three consistent SCT modules')
    return expected,found_stem


def verify_exact_sct_pipeline_shape(generated_by_name, generated_stem):
    """Compare to a REAL SCT Batch CLI reference trace for controlled Scenario A.
    Only the two local CSV path literals may differ after source metadata repair.
    Unknown generated transformations/code injection fail closed.
    """
    baseline_file=Path(__file__).resolve().parent.parent/'evidence'/'ScenarioA_Unfixed_ActualSCT_Output.zip'
    if not baseline_file.is_file():raise CandidateBlocked('Missing real SCT baseline evidence for safe shape verification')
    with zipfile.ZipFile(baseline_file) as z:
        actual={}
        for f in z.namelist():
            if 'create-body-script/' not in f or not f.endswith('.py') or not z.getinfo(f).file_size:continue
            k=next((key for key in (MAIN_MODULE,FILTER_MODULE,'variables') if Path(f).name.lower().endswith('.'+key+'.py')),None)
            if k is None or k in actual:raise CandidateBlocked('Unexpected SCT baseline module')
            actual[k]=z.read(f).decode('utf-8-sig')
    if set(actual)!=set(generated_by_name):raise CandidateBlocked('SCT baseline modules are incomplete')
    def normalized(source, name):
        tree=ast.parse(source)
        if name==MAIN_MODULE and generated_stem!=MAIN_MODULE:
            # Only the one known coordinator definition is allowed to change
            # its name. Its full body, imports and call graph must still match
            # the genuine SCT CLI baseline AST below.
            for node in tree.body:
                if isinstance(node,ast.FunctionDef) and node.name==generated_stem:
                    node.name=MAIN_MODULE
        for node in ast.walk(tree):
            if isinstance(node,ast.Constant) and isinstance(node.value,str) and node.value.startswith('D:'):
                if node.value.endswith('Employees.csv'):
                    node.value='__APPROVED_SCT_EMPLOYEE_SOURCE_PATH__'
                elif node.value.endswith('ActiveEmployees_SSIS.csv'):
                    node.value='__APPROVED_SCT_EMPLOYEE_DESTINATION_PATH__'
        return ast.dump(tree,include_attributes=False)
    for name,raw in generated_by_name.items():
        if normalized(raw,name)!=normalized(actual[name],name):
            raise CandidateBlocked('Unexpected SCT-generated AST in '+name+'; new remediation review required')


def require_sct_shape(text):
    ast.parse(text)
    checks={
      'read':r'spark\.read\.csv\("D:\\[^"\n]+\\Employees\.csv",\s*header="True",\s*sep=","\)',
      'filter':r'WHERE `status` == \'Active\'',
      'bonus':r'CAST\(\(`salary` \* 0\.10\) AS decimal\) AS `bonus`',
      'write':r'\.write\.mode\("Overwrite"\)\.csv\("D:\\[^"\n]+\\ActiveEmployees_SSIS\.csv",\s*header="true",\s*sep=","\)',
    }
    for code,pattern in checks.items():
        if not re.search(pattern,text):raise CandidateBlocked('Unrecognized SCT '+code+' shape; deterministic repair is not safe')
    if text.count('spark.sql(')!=3 or text.count('spark.read.csv(')!=1 or text.count('.write.mode(')!=1:
        raise CandidateBlocked('Unexpected number of SCT dataflow operations')
    if any(x in text.lower() for x in ('jdbc:','specify driver','drop table','truncate table','spark.read.format("jdbc")')):
        raise CandidateBlocked('Unsupported SQL/JDBC behavior detected')


def remove_unused_sct_boilerplate(txt):
    # The exact known generated modules contain no calls to these imports or args.
    if re.search(r'(?<!\w)(?:cast|chkParam|substParam|args|relativedelta)\s*\(',txt):
        raise CandidateBlocked('SCT helper is actually used; cannot remove its import')
    patterns=[r'^from sct_utils import (?:cast|chkParam|substParam)\s*\n',
              r'^from awsglue\.utils import getResolvedOptions\s*\n',
              r'^args = getResolvedOptions\(sys\.argv, \[\'region_name\', \'TempDir\', \'AwsIamRole\'\]\)\s*\n',
              r'^from dateutil\.relativedelta import relativedelta\s*\n']
    for pat in patterns:txt=re.sub(pat,'',txt,flags=re.MULTILINE)
    return txt


def transform_dataflow(src):
    require_sct_shape(src)
    txt=remove_unused_sct_boilerplate(src)
    edits=[]
    def swap(old,new,code):
        nonlocal txt
        if txt.count(old)!=1: raise CandidateBlocked('Expected exactly one SCT '+code+' pattern')
        txt=txt.replace(old,new);edits.append(code)
    swap('import variables','import variables\nimport os','IMPORT_SAFE_PATH_ARGUMENTS')
    source_select='col("employeeid").alias("employeeid"), col("employeename").alias("employeename"), col("department").alias("department"), col("salary").alias("salary"), col("status").alias("status")'
    explicit_source='col("EmployeeID").alias("employeeid"), col("EmployeeName").alias("employeename"), col("Department").alias("department"), col("Salary").alias("salary"), col("Status").alias("status")'
    swap(source_select,explicit_source,'BIND_ACTUAL_CSV_HEADER_CASE')
    txt,count=re.subn(r'spark\.read\.csv\("D:\\[^"\n]+\\Employees\.csv", header="True", sep=","\)',
                     'spark.read.csv(os.environ["FORGE_INPUT_CSV"], header="True", sep=",")',txt)
    if count!=1:raise CandidateBlocked('Cannot bind SCT source to staged S3 URI')
    edits.append('MAP_SOURCE_WINDOWS_PATH_TO_S3_ARGUMENT')
    # Source CSV strings must be cast to explicit decimal to avoid implicit Spark math.
    if txt.count('col("salary").alias("salary")') != 1:
        raise CandidateBlocked('Expected source and destination salary projections')
    txt=txt.replace('col("Salary").alias("salary")', 'col("Salary").cast("decimal(18,2)").alias("salary")', 1)
    edits.append('EXPLICIT_DECIMAL_SALARY_TYPE')
    swap('WHERE `status` == \'Active\'',"WHERE `status` = 'Active'",'SPARK_SQL_EQUALS_NORMALIZATION')
    swap('CAST((`salary` * 0.10) AS decimal) AS `bonus`',
         'CAST((`salary` * CAST(0.10 AS DECIMAL(3,2))) AS DECIMAL(18,2)) AS `bonus`',
         'FIX_DECIMAL_PRECISION_SCALE')
    swap('col("employeeid").alias("employeeid"), col("employeename").alias("employeename"), col("department").alias("department"), col("salary").alias("salary"), col("bonus").alias("bonus")',
         'col("employeeid").alias("EmployeeID"), col("employeename").alias("EmployeeName"), col("department").alias("Department"), col("salary").cast("decimal(18,2)").alias("Salary"), col("bonus").cast("decimal(18,2)").alias("Bonus")',
         'MATCH_EXPECTED_OUTPUT_SCHEMA')
    txt,count=re.subn(r'\.write\.mode\("Overwrite"\)\.csv\("D:\\[^"\n]+\\ActiveEmployees_SSIS\.csv", header="true", sep=","\)',
                     '.write.mode("errorifexists").csv(os.environ["FORGE_OUTPUT_CSV"], header="true", sep=",")',txt)
    if count!=1:raise CandidateBlocked('Cannot bind SCT destination to isolated S3 output')
    edits.append('MAP_DESTINATION_TO_ISOLATED_S3_AND_FAIL_IF_EXISTS')
    if '\\fixtures' in txt or re.search(r'[A-Z]:\\',txt):raise CandidateBlocked('Local Windows path remains in repaired module')
    ast.parse(txt)
    return txt,edits


def glue_entry():
    return '''"""Scenario A glueetl entry; invokes original SCT-produced package/dataflow call chain."""\nimport os\nimport sys\nfrom awsglue.utils import getResolvedOptions\n\ndef main():\n    args = getResolvedOptions(sys.argv, ["INPUT_PREFIX", "OUTPUT_PREFIX"])\n    inp = args["INPUT_PREFIX"].rstrip("/")\n    out = args["OUTPUT_PREFIX"].rstrip("/")\n    if not inp.startswith("s3://") or not out.startswith("s3://"):\n        raise ValueError("Glue data paths must be s3:// URLs")\n    if inp == out or out.startswith(inp + "/"):\n        raise ValueError("Input/output path overlap is forbidden")\n    os.environ["FORGE_INPUT_CSV"] = inp + "/Employees.csv"\n    os.environ["FORGE_OUTPUT_CSV"] = out + "/ActiveEmployees.csv"\n    from a_employees_active_bonus import a_employees_active_bonus\n    a_employees_active_bonus({})\n\nif __name__ == "__main__":\n    main()\n'''


def compile_candidate(original_dir,manifest,package_path,dest,source_method,source_file_name):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    contract=contract_for_package(package_path)
    names,generated_stem=module_paths(manifest,source_file_name)
    originals={k:(Path(original_dir)/file).read_text(encoding='utf-8-sig') for k,file in names.items()}
    for k,text in originals.items():
        if not text.strip():raise CandidateBlocked('SCT module empty '+k)
        ast.parse(text)
    for name,file_name in names.items():
        item=next((i for i in manifest if i['file']==file_name),None)
        if not item or sha((Path(original_dir)/file_name).read_bytes())!=item['sha256']:
            raise CandidateBlocked('Original SCT file changed since import: '+name)
    verify_exact_sct_pipeline_shape(originals,generated_stem)
    if (('import '+FILTER_MODULE) not in originals[MAIN_MODULE] or
        FILTER_MODULE+'.'+FILTER_MODULE+'(connection)' not in originals[MAIN_MODULE] or
        'def '+generated_stem+'(connection: dict):' not in originals[MAIN_MODULE]):
        raise CandidateBlocked('Unexpected SCT orchestration; original package call chain not verified')
    dataflow,edits=transform_dataflow(originals[FILTER_MODULE])
    main_code=originals[MAIN_MODULE]
    if generated_stem!=MAIN_MODULE:
        # Canonicalize only the declaration that SCT derives from the .dtsx
        # basename. This lets the existing tested Glue/PySpark entry points
        # invoke the original SCT coordinator, not a separate reference job.
        main_code,count=re.subn(r'(?m)^def '+re.escape(generated_stem)+r'\(connection: dict\):$',
                                 'def '+MAIN_MODULE+'(connection: dict):',main_code)
        if count!=1:raise CandidateBlocked('Unexpected SCT coordinator declaration')
        edits.append('NORMALIZE_CORRECTED_PACKAGE_COORDINATOR_NAME')
    packaged={MAIN_MODULE+'.py':remove_unused_sct_boilerplate(main_code),
              FILTER_MODULE+'.py':dataflow,
              'variables.py':remove_unused_sct_boilerplate(originals['variables'])}
    packaged[MAIN_MODULE+'.py']=remove_unused_sct_boilerplate(packaged[MAIN_MODULE+'.py'])
    # Do not include generated helpers with unknown semantics; known imports were unused.
    for name,text in packaged.items():
        ast.parse(text)
        if 'sct_utils' in text or 'getResolvedOptions' in text or 'D:\\' in text:
            raise CandidateBlocked('Unresolved import or local Windows path in '+name)
    entry=glue_entry();ast.parse(entry)
    diffs=[]
    for module_key in (MAIN_MODULE,FILTER_MODULE,'variables'):
        before=originals[module_key].splitlines(keepends=True)
        after=packaged[module_key+'.py'].splitlines(keepends=True)
        diffs.extend(difflib.unified_diff(before,after,fromfile='SCT original/'+module_key+'.py',
                                         tofile='deterministic repair/'+module_key+'.py'))
    (dest/'candidate-diff.txt').write_text(''.join(diffs),encoding='utf-8')
    pyzip=io.BytesIO()
    with zipfile.ZipFile(pyzip,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,code in packaged.items():archive.writestr(name,code)
    pyzip_bytes=pyzip.getvalue()
    (dest/'glue_entry_sct_a.py').write_bytes(entry.encode('utf-8'))
    (dest/'sct_modules.zip').write_bytes(pyzip_bytes)
    for name,code in packaged.items():(dest/name).write_bytes(code.encode('utf-8'))
    checks={'sourcePackageContract':True,'originalSctModules':3,'orchestrationPreserved':True,
            'sourceS3Mapping':True,'isolatedOutput':True,'syntaxPass':True,
            'helpersResolvedByRemovingUnusedImports':True,'dataflowFromSCT':True,
            'ssdtRuntimeVerified':False,'awsRuntimeVerified':False}
    report={'status':'SCT_SCENARIO_A_PREFLIGHT_READY_NOT_RUN','provenance':source_method,
            'sourceSha256':contract['sourceSha256'],
            'uploadedSourceFileName':source_file_name, 'sctGeneratedPackageStem':generated_stem,
            'originalModuleSha256':{k:sha(v.encode()) for k,v in originals.items()},
            'generatedEntrySha256':sha(entry.encode()),'pyModulesZipSha256':sha(pyzip_bytes),
            'diffSha256':sha((dest/'candidate-diff.txt').read_bytes()),
            'repairedModuleSha256':{n:sha(code.encode()) for n,code in packaged.items()},
            'edits':[{'rule':x,'origin':'DETERMINISTIC_TOOL_NOT_BEDROCK'} for x in edits],
            'checks':checks,'sourceContract':contract,
            'runtimeVerified':False,'parityVerified':False,
            'note':'This is corrected SCT dataflow code, NOT an independently written reference Glue job. Live Glue execution is required to prove parity.'}
    (dest/'preflight.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
