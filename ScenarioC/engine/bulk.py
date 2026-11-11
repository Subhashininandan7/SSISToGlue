"""Bulk portfolio orchestration around the existing *single-package* Forge engine.

No second converter or ETL generator. One exact package session per upload;
explicit, resumable per-package steps. Unknown dependencies and missing source
baselines block claims of parity, never trigger fabricated results.
"""
from __future__ import annotations
import base64
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from xml.etree import ElementTree as ET
import unsupported_process_ai as process_ai
import quickflow
import process_glue

BATCH_RE = re.compile(r'^[0-9a-f]{16}$')
PACKAGE_RE = re.compile(r'^[A-Za-z0-9_.-]{1,100}\.dtsx$', re.I)
MAX_PACKAGES = 500

def _home(cli): return cli.HOME / 'portfolios'
def _path(cli, pid):
    if not isinstance(pid, str) or not BATCH_RE.fullmatch(pid):
        raise ValueError('Invalid portfolio ID')
    folder=_home(cli)/pid
    if not (folder/'portfolio.json').is_file():raise ValueError('Portfolio not found')
    return folder

def _read(cli, pid):return json.loads((_path(cli,pid)/'portfolio.json').read_text('utf-8'))
def _save(cli, p, obj):cli.store(p/'portfolio.json',obj)
def _entry(plan, name):
    matches=[e for e in plan['packages'] if e['name'].casefold()==name.casefold()]
    if len(matches)!=1:raise ValueError('Package not found in portfolio')
    return matches[0]

def create(cli, req):
    pid=secrets.token_hex(8)
    folder=_home(cli)/pid
    folder.mkdir(parents=True,exist_ok=False)
    data={'id':pid,'createdAt':cli.moment(),'updatedAt':cli.moment(),
          'status':'UPLOADING','packages':[], 'source':'ORIGINAL_DTSX',
          'notice':'Every package is independently converted by real SCT. No synthesized business logic.'}
    _save(cli,folder,data)
    return data

def _dependencies(raw, name):
    """Extract literal Execute Package Task references only; reject unresolved
    dynamic references at execution time rather than inventing task ordering.
    The scan is conservative: a package with an executable PackageTask but no
    literal path/name is explicitly marked ambiguous.
    """
    root=ET.fromstring(raw)
    deps=set(); ambiguous=[]
    for exe in root.iter():
        if not exe.tag.endswith('Executable'):continue
        attrs={k.split('}')[-1].lower():v for k,v in exe.attrib.items()}
        typ=str(attrs.get('executabletype','')).lower()
        if 'packagetask' not in typ and 'executepackage' not in typ:continue
        paths=[]
        for node in exe.iter():
            for key,value in node.attrib.items():
                k=key.split('}')[-1].lower()
                if k in ('packagename','packagelocation','packagepath','packagetoexecute','packagenametoload'):
                    paths.append(str(value))
            if node.tag.split('}')[-1].lower() in ('packagename','packagelocation','packagepath') and node.text:
                paths.append(node.text)
        candidates=[Path(v.replace('\\','/')).name for v in paths if v.lower().endswith('.dtsx')]
        if len(set(v.casefold() for v in candidates))==1:
            target=candidates[0]
            if target.casefold()!=name.casefold():deps.add(target)
        else:
            ambiguous.append('Execute Package Task has dynamic or missing package reference')
    return sorted(deps),ambiguous

def _local_name(path):
    return str(path).replace('\\','/').rsplit('/',1)[-1]

def _input_references(raw):
    """Discover literal Flat File Source connections from original SSIS XML.
    Output destinations are deliberately excluded. No source path is rewritten.
    Dynamic expressions are exposed as warnings, not silently resolved.
    """
    root=ET.fromstring(raw)
    managers={}
    for cm in root.iter():
        if cm.tag.split('}')[-1]!='ConnectionManager':continue
        if not any(k.split('}')[-1]=='CreationName' and v.upper()=='FLATFILE' for k,v in cm.attrib.items()):continue
        ident=next((v for k,v in cm.attrib.items() if k.split('}')[-1]=='refId'),None)
        if not ident:continue
        for child in cm.iter():
            if child is cm or child.tag.split('}')[-1]!='ConnectionManager':continue
            path=next((v for k,v in child.attrib.items() if k.split('}')[-1]=='ConnectionString'),None)
            if path:managers[ident]=path
    refs=[];warnings=[];seen=set()
    for component in root.iter():
        if component.tag.split('}')[-1]!='component':continue
        classid=component.attrib.get('componentClassID','').lower()
        if 'flatfilesource' not in classid and 'flat file source' not in classid:continue
        for connection in component.iter():
            if connection.tag.split('}')[-1]!='connection':continue
            ref=connection.attrib.get('connectionManagerRefId') or connection.attrib.get('connectionManagerID')
            if not ref:continue
            path=managers.get(ref)
            if not path:
                warnings.append('Flat File Source has missing or expression-based connection: '+ref)
                continue
            name=_local_name(path)
            key=name.casefold()
            if key in seen:continue
            seen.add(key)
            refs.append({'name':name,'originalPath':path,'connection':ref})
    return refs,warnings

def _safe_relative(value):
    value=str(value).replace('\\','/')
    parts=value.split('/')
    if (not value or len(value)>450 or value.startswith('/') or ':' in value or
        any(x in ('','.','..') for x in parts)):
        raise ValueError('Unsafe relative folder path')
    return value

def add(cli, req):
    pid=req.get('portfolioId');p=_path(cli,pid);plan=_read(cli,pid)
    name=str(req.get('fileName','')).replace('\\','/').split('/')[-1]
    if not PACKAGE_RE.fullmatch(name):raise ValueError('Upload a .dtsx with a safe filename')
    data=cli.decode_b64(req,limit=6_000_000)
    previous=[e for e in plan['packages'] if e['name'].casefold()==name.casefold()]
    if previous:
        if req.get('reuseMatching') is True and previous[0]['sha256']==hashlib.sha256(data).hexdigest():
            prior=previous[0]
            if not prior.get('inputReferences'):
                refs,warns=_input_references(data)
                prior['inputReferences']=refs
                prior.setdefault('inputResolution',{})
                prior['relativePath']=_safe_relative(req.get('relativePath') or name)
                _save(cli,p,plan)
            return {'portfolioId':pid,'package':name,'sessionId':prior['sessionId'],
                    'dependencies':prior['dependencies'],'warnings':prior.get('ambiguousDependencies',[]),
                    'inputReferences':prior['inputReferences'],
                    'relativePath':prior.get('relativePath',name),'reused':True,'count':len(plan['packages'])}
        raise ValueError('Duplicate package name with different content. Create a new migration folder/session for this version')
    if len(plan['packages'])>=MAX_PACKAGES:raise ValueError('Portfolio limit is 500 packages')
    try:
        root=ET.fromstring(data)
        if not root.tag.endswith('Executable') or 'www.microsoft.com/SqlServer/Dts' not in root.tag:
            raise ValueError('Not recognized as a DTSX package')
        deps,ambiguous=_dependencies(data,name)
        references,source_warnings=_input_references(data)
        relative=_safe_relative(req.get('relativePath') or name)
        if relative.rsplit('/',1)[-1].casefold()!=name.casefold():raise ValueError('Package relative path does not match filename')
    except ET.ParseError as exc:raise ValueError('Invalid SSIS package XML') from exc
    s=cli.new('CUSTOM'); sid=s['id']
    cli.submit_source({'sessionId':sid,'fileName':name,'contentBase64':req['contentBase64']})
    plan['packages'].append({'name':name,'sessionId':sid,'sha256':hashlib.sha256(data).hexdigest(),
                             'dependencies':deps,'ambiguousDependencies':ambiguous,
                             'relativePath':relative,'inputReferences':references,'inputResolution':{},
                             'state':'UPLOADED','history':[],'lastError':None})
    plan['updatedAt']=cli.moment();_save(cli,p,plan)
    return {'portfolioId':pid,'package':name,'sessionId':sid,'dependencies':deps,'warnings':ambiguous+source_warnings,'inputReferences':references,
            'relativePath':relative,'count':len(plan['packages'])}

def upload_support(cli,req):
    """Store explicitly selected sidecar evidence for a single original package.

    Never treat arbitrary files in a folder as approved Bedrock data. Sidecars
    are sent only after the user checks both existing Bedrock consents.
    """
    pid=req.get('portfolioId');p=_path(cli,pid);plan=_read(cli,pid)
    e=_entry(plan,str(req.get('packageName','')))
    filename=Path(str(req.get('fileName','')).replace('\\','/')).name
    role=req.get('role')
    if role=='script':
        task=process_ai.inspect_ssis((cli.session_path(e['sessionId'])/'source'/'original.dtsx').read_bytes())
        if filename.casefold()!=task['scriptName'].casefold():raise ValueError('Sidecar script is not named in original SSIS task metadata')
        limit=100_000
    elif role=='input':
        process_ai.validate_name(filename);limit=2_000_000
    elif role=='reference':
        process_ai.validate_name(filename);limit=2_000_000
    else:raise ValueError('Unknown supporting file role')
    raw=cli.decode_b64(req,limit=limit)
    if role!='script':process_ai.csv_schema(raw)
    original_filename=filename
    # Keep the source filename unchanged. References are optional and never
    # assumed to be the original SSIS output simply from an Expected_ prefix.
    dest=cli.session_path(e['sessionId'])/'process-support'/role/filename
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_bytes(raw)
    e.setdefault('processEvidence',{}).setdefault(role,[])
    if filename not in e['processEvidence'][role]:e['processEvidence'][role].append(filename)
    _save(cli,p,plan)
    return {'package':e['name'],'role':role,'fileName':filename,'sha256':hashlib.sha256(raw).hexdigest(),
            'sourceFileName':original_filename,'notice':'Stored as local evidence; not transmitted to Bedrock without explicit approval'}


def _process_folder(cli,e):return cli.session_path(e['sessionId'])/'process-ai'

def _process_files(cli,e):
    base=cli.session_path(e['sessionId'])/'process-support'
    def files(role):return {f.name:f.read_bytes() for f in (base/role).glob('*') if f.is_file()}
    scripts=files('script')
    if len(scripts)!=1:raise ValueError('Exactly one original .ps1 sidecar required; include it in the selected folder')
    return next(iter(scripts.items())),files('input'),files('reference')

def _prepare_process_ai(cli,e):
    session=cli.session_path(e['sessionId'])
    package=(session/'source'/'original.dtsx').read_bytes()
    archive=(session/'sct'/'original-conversion-output.zip').read_bytes()
    task=process_ai.inspect_ssis(package)
    warning=process_ai.inspect_sct(archive)
    (name,script),inputs,references=_process_files(cli,e)
    # Original metadata and sidecar source are the AI inputs; output is generated
    # by the repaired code. Reference output is strictly optional.
    wf=process_ai.Workflow(_process_folder(cli,e))
    manifest=wf.analyze(package,archive,script,inputs,references,script_name=name)
    return wf,manifest

def upload_input(cli,req):
    pid=req.get('portfolioId');p=_path(cli,pid);plan=_read(cli,pid)
    e=_entry(plan,str(req.get('packageName','')))
    name=str(req.get('fileName',''))
    relative=_safe_relative(req.get('relativePath') or name)
    if relative.rsplit('/',1)[-1].casefold()!=name.casefold():
        raise ValueError('Input relative path and filename disagree')
    expected={r['name'].casefold():r for r in e.get('inputReferences',[])}
    if name.casefold() not in expected:
        raise ValueError('Input is not referenced by this package Flat File Source: '+name)
    if not name.lower().endswith('.csv'):
        raise ValueError('Input file type is not supported for automatic S3 CSV staging: '+name)
    result=cli.quick_inputs({'sessionId':e['sessionId'],'fileName':name,
                             'contentBase64':req.get('contentBase64')})
    sha=hashlib.sha256((cli.session_path(e['sessionId'])/'inputs'/name).read_bytes()).hexdigest()
    e.setdefault('inputResolution',{})[name]={
        'relativePath':relative,'originalPath':expected[name.casefold()]['originalPath'],
        'sha256':sha,'method':str(req.get('resolutionMethod','FOLDER_MATCH'))}
    # Preserve completed SCT and AI work. If input absence was the only deploy
    # problem, restore an eligible state without re-converting or deploying.
    analysis=cli.session_path(e['sessionId'])/'quick'/'report.json'
    if e.get('state')=='ERROR_DEPLOY' and analysis.is_file():
        report=json.loads(analysis.read_text('utf-8'))
        required=report.get('inputs',[])
        if not report.get('blockers') and all((cli.session_path(e['sessionId'])/'inputs'/n).is_file() for n in required):
            e['state']='READY_FOR_DEPLOYMENT'
            e['lastError']=None
    plan['updatedAt']=cli.moment();_save(cli,p,plan)
    return {**result,'source':'SELECTED_FOLDER','sha256':sha,'relativePath':relative}

def _csv_parity_proven(e):
    """Only restore a previous verified result using persisted evidence for every
    declared CSV output AND an authoritative successful Glue status.
    This never manufactures a validation result from a successful job alone.
    """
    outputs=e.get('outputs') or []
    validations=e.get('validation') or {}
    return (e.get('glueStatus')=='SUCCEEDED' and bool(outputs)
            and all(str(n).lower().endswith('.csv') for n in outputs)
            and all(validations.get(n,{}).get('status')=='MATCH'
                    and validations.get(n,{}).get('verified') is True
                    for n in outputs))


def _terminal_success(e):
    return _csv_parity_proven(e) or (e.get('state')=='OUTPUTS_MATCH'
             and e.get('glueStatus')=='SUCCEEDED')


def status(cli,req):
    plan=_read(cli,req.get('portfolioId'))
    for e in plan['packages']:
        s=cli.load(e['sessionId'])[1]
        session_dir=cli.session_path(e['sessionId'])
        e['sctCompleted']=(session_dir/'sct'/'auto-result.json').is_file()
        e['sctImported']=(session_dir/'sct'/'original-conversion-output.zip').is_file()
        e['assessmentAvailable']=(session_dir/'sct'/'assessment-original.zip').is_file()
        e['unsupportedProcessAI']=(session_dir/'process-ai'/'manifest.json').is_file()
        if e['unsupportedProcessAI']:
            try:e['processAIStatus']=process_ai.read_json(session_dir/'process-ai'/'manifest.json').get('status')
            except (OSError,ValueError):pass
        e['conversion']=s.get('conversion');e['quickAnalysis']=s.get('quickAnalysis')
        expected=e.get('inputReferences',[])
        e['missingFolderInputs']=[r['name'] for r in expected if not (session_dir/'inputs'/r['name']).is_file()]
        q=cli.session_path(e['sessionId'])/'quick'
        for key, filename in [('deployment','deployment.json'),('analysis','report.json')]:
            file=q/filename
            if file.is_file():
                try:
                    r=json.loads(file.read_text('utf-8'))
                    if key=='analysis':e['blockers']=r.get('blockers',[]);e['outputs']=r.get('outputs',[])
                    elif key=='deployment':e['jobName']=r.get('jobName')
                except (ValueError, OSError, TypeError):pass
        # cloud_run writes run.json immediately. status.json is created only by
        # cloud_poll; using status.json alone deadlocks bulk polling forever.
        # Persisted run identity must survive app/browser restarts. A newer
        # authoritative poll result overrides the submitted state.
        submitted=q/'run.json'
        if submitted.is_file():
            try:
                r=json.loads(submitted.read_text('utf-8'))
                if r.get('runId') and r.get('jobName') and r.get('origin')=='REAL_AWS_GLUE':
                    e['runId']=r['runId'];e['glueStatus']=r.get('status','SUBMITTED')
                    e['jobName']=r['jobName']
            except (ValueError, OSError, TypeError):pass
        polled=q/'status.json'
        if polled.is_file():
            try:
                r=json.loads(polled.read_text('utf-8'))
                # Only accept a poll result for this exact submitted run.
                if r.get('runId') and r.get('runId')==e.get('runId') and r.get('jobName')==e.get('jobName'):
                    e['glueStatus']=r.get('status',e.get('glueStatus'))
                    if r.get('status')=='SUCCEEDED':e['state']='GLUE_SUCCEEDED' if e.get('state')=='RUN_SUBMITTED' else e.get('state')
            except (ValueError, OSError, TypeError):pass
        if e.get('processAIKind')=='EXECUTE_PROCESS_25029' or e.get('unsupportedProcessAI'):
            ai=session_dir/'process-ai'
            # An unsuccessful, unnecessary re-proposal must never invalidate a
            # previously human-approved AND independently validated artifact.
            # Recompute eligibility from on-disk cryptographic evidence, not
            # the last transient UI action/state.
            if e.get('state','').startswith('ERROR_AI_PROPOSE'):
                try:
                    approved=process_glue._record(ai)
                    validated_status=approved[0]['status']
                    e['state']=validated_status
                    e['lastError']=None
                    e.pop('pendingBaseHash',None)
                    e.setdefault('history',[]).append({'at':cli.moment(),'operation':'recover-approved-ai',
                        'status':validated_status,'notice':'Restored from independently validated approved artifact'})
                except (process_ai.RemediationBlocked, OSError, ValueError, KeyError):
                    pass  # A broken candidate remains blocked; never bypass hash checks.
            dep=ai/'cloud-deployment.json'
            if dep.is_file():
                d=process_ai.read_json(dep)
                e['jobName']=d['jobName']
                e['aiCloudOrigin']=d['origin']
                e['aiOutputS3']=d['outputS3']
            run=ai/'cloud-run.json'
            if run.is_file():
                r=process_ai.read_json(run)
                e['runId']=r['runId'];e['glueStatus']=r['status']
            state=ai/'cloud-status.json'
            if state.is_file() and run.is_file():
                r=process_ai.read_json(state)
                if r['runId']==e['runId'] and r['jobName']==e['jobName']:
                    e['glueStatus']='SUCCEEDED' if r['status'] in ('SUCCEEDED_OUTPUTS_GENERATED','SUCCEEDED_OUTPUT_CHECK_FAILED') else r['status']
                    e['cloudOutputValidated']=r.get('cloudOutputValidated',False)
                    e['cloudOutputs']=r.get('outputs',[])
                    e['cloudOutputArchiveAvailable']=r.get('outputArchiveAvailable',False)
                    e['cloudSSISParity']=r.get('ssisParity','NOT_PROVEN')
                    # AI cloud output folders are authoritative discovered CSV outputs.
                    # Never infer them from original SCT's missing coordinator.
                    e['outputs']=[x['output'] for x in e['cloudOutputs']
                                  if isinstance(x,dict) and isinstance(x.get('output'),str)
                                  and x['output'].lower().endswith('.csv')]
                    proof=ai/'cloud-validation.json'
                    if proof.is_file() and r['status']=='SUCCEEDED_OUTPUTS_GENERATED':
                        try:
                            evidence=process_ai.read_json(proof)
                            deployed=process_ai.read_json(dep)
                            if (evidence.get('runId')==r['runId'] and
                                evidence.get('jobName')==r['jobName'] and
                                evidence.get('outputS3')==deployed['outputS3'] and
                                evidence.get('approvedCodeSha256')==deployed['approvedCodeSha256']):
                                e['validation']=evidence.get('results',{})
                        except (ValueError,OSError,KeyError,TypeError):pass
                    if r['status']=='SUCCEEDED_OUTPUTS_GENERATED':e['state']='GLUE_OUTPUT_GENERATED'
                    elif r['status'] in ('SUCCEEDED_OUTPUT_CHECK_FAILED','SUCCEEDED_OUTPUT_CONTRACT_MISMATCH'):e['state']='GLUE_OUTPUT_CHECK_FAILED'
                    elif r['status'] in ('FAILED','TIMEOUT','ERROR','STOPPED'):e['state']='GLUE_FAILED'
        # A later AI or analysis error must not replace previously evidenced
        # Glue + CSV parity success. Retain the error in history for audit.
        if _csv_parity_proven(e):
            e['state']='OUTPUTS_MATCH'
        elif e.get('glueStatus')=='SUCCEEDED' and str(e.get('state','')).startswith('ERROR_AI_'):
            e['state']='GLUE_SUCCEEDED'
    return plan

def _upstream(plan,e):
    mapping={x['name'].casefold():x for x in plan['packages']}
    missing=[n for n in e['dependencies'] if n.casefold() not in mapping]
    if missing:raise ValueError('Unresolved upstream SSIS packages: '+', '.join(missing))
    visiting=set()
    def check_cycles(node):
        key=node['name'].casefold()
        if key in visiting:raise ValueError('Cyclic package dependency detected: '+node['name'])
        visiting.add(key)
        for dependency in node['dependencies']:
            parent=mapping.get(dependency.casefold())
            if parent:check_cycles(parent)
        visiting.remove(key)
    check_cycles(e)
    if e['ambiguousDependencies']:raise ValueError('; '.join(e['ambiguousDependencies']))
    return [mapping[n.casefold()] for n in e['dependencies']]

def _gate(plan,e,phase):
    upstream=_upstream(plan,e)
    if phase in ('run','deploy'):
        for parent in upstream:
            if phase=='run' and parent.get('glueStatus')!='SUCCEEDED':
                raise ValueError('Upstream package must succeed before execution: '+parent['name'])
            if phase=='deploy' and not parent.get('jobName'):
                raise ValueError('Upstream package must be deployed first: '+parent['name'])

def _has_executeprocess_25029(cli,session):
    archive=cli.session_path(session)/'sct'/'original-conversion-output.zip'
    if not archive.is_file():return False
    try:process_ai.inspect_sct(archive.read_bytes());return True
    except process_ai.RemediationBlocked:return False

def step(cli,req):
    """Exactly one package action per request, so 100-package operations can be
    resumed, retried safely, and polled without a server-side background worker.
    Call existing single-package functions; NEVER auto-approve AI suggestions.
    """
    pid=req.get('portfolioId');p=_path(cli,pid);plan=_read(cli,pid)
    e=_entry(plan,str(req.get('packageName','')))
    operation=req.get('operation')
    allowed={'convert','analyze','ai-propose','ai-accept','ai-local-validate','aws','deploy','run','poll','validate'}
    if operation not in allowed:raise ValueError('Unsupported bulk operation')
    plan=status(cli,{'portfolioId':pid});e=_entry(plan,e['name'])
    # Already completed packages are immutable under early-stage bulk actions.
    # Adding C must not replay Bedrock acceptance or overwrite A/B success.
    if _terminal_success(e) and operation in ('convert','analyze','ai-propose','ai-accept','aws','deploy','run'):
        return {'package':e['name'],'sessionId':e['sessionId'],
                'state':e['state'],'result':{'status':'SKIPPED_ALREADY_COMPLETED',
                'notice':'Original Glue and CSV validation evidence preserved'}}
    _gate(plan,e,operation)
    session=e['sessionId']
    inner={'sessionId':session}
    # A repeat Generate AI click must NOT overwrite an approved code artifact.
    # Its trusted, persisted evidence is authoritative across application
    # upgrades, restarts and transient Bedrock errors.
    if operation=='ai-propose' and (e.get('processAIKind')=='EXECUTE_PROCESS_25029' or e.get('unsupportedProcessAI')):
        ai=_process_folder(cli,e)
        if (ai/'manifest.json').is_file():
            m=process_ai.read_json(ai/'manifest.json')
            if m.get('status') in ('LOCAL_OUTPUT_GENERATED','LOCAL_PARITY_MATCH'):
                process_glue._record(ai)  # verify code, approval hash, input and local validation
                e['processAIKind']='EXECUTE_PROCESS_25029'
                e['state']=m['status'];e['lastError']=None
                e.pop('pendingBaseHash',None)
                plan['updatedAt']=cli.moment();_save(cli,p,plan)
                return {'package':e['name'],'sessionId':session,'state':e['state'],
                        'result':{'status':'ALREADY_APPROVED_AND_VALIDATED',
                        'notice':'Existing approved and locally verified code preserved; deploy it, do not regenerate AI.'}}
    inner={'sessionId':session}
    try:
        if operation=='convert':
            if (cli.session_path(session)/'sct'/'auto-result.json').is_file():
                raise ValueError('SCT conversion already attempted; inspect existing result')
            result=cli.auto_convert(inner)
            ok=bool(result.get('importedScripts')) and result.get('exitCode')==0
        elif operation=='analyze':
            try:
                result=cli.quick_analyze({**inner,'preserveOriginalSqlServer':req.get('preserveOriginalSqlServer') is True})
                ok=not result.get('blockers')
            except quickflow.Blocked as exc:
                if 'Unable to prove unique SCT coordinator' not in str(exc):raise
                # Only a genuine SCT 25029 plus matching SSIS task metadata can
                # enter this special lane; no fabricated coordinator is created.
                wf,manifest=_prepare_process_ai(cli,e)
                result={'status':'UNSUPPORTED_TASK_AI_ELIGIBLE','blockers':['SCT 25029: Microsoft.ExecuteProcess requires reviewed PySpark replacement'],
                        'task':manifest['task'],'sct':manifest['sct'],'deployAllowed':False}
                e['blockers']=result['blockers'];ok=False
                e['processAIKind']='EXECUTE_PROCESS_25029'
        elif operation=='ai-propose' and req.get('approveModelCost') is True and req.get('approveCodeTransmission') is True and not (cli.session_path(session)/'sct'/'original-conversion-output.zip').is_file():
            raise ValueError('No original SCT conversion ZIP for this package. Convert with AWS SCT in this new portfolio before requesting AI; an older portfolio or a failed conversion cannot be repaired.')
        elif operation=='ai-propose' and not e.get('processAIKind') and not (cli.session_path(session)/'quick'/'report.json').is_file() and _has_executeprocess_25029(cli,session):
            # Coordinator-free SCT output cannot pass the usual analysis gate.
            # Inspect real original metadata + real SCT 25029 evidence here,
            # rather than letting the browser silently skip this package.
            # Ordinary conversions must still follow the existing quick_ai path.
            wf,manifest=_prepare_process_ai(cli,e)
            e['processAIKind']='EXECUTE_PROCESS_25029'
            e['blockers']=['SCT 25029: Microsoft.ExecuteProcess requires reviewed PySpark replacement']
            result=wf.propose(profile=req.get('profile') or 'ssis-glue-poc',region=req.get('region') or 'ap-southeast-2',
                model=req.get('modelId') or 'amazon.nova-lite-v1:0',approve_cost=req.get('approveModelCost') is True,
                approve_transmission=req.get('approveCodeTransmission') is True)
            result={'status':'AI_PATCH_REVIEW_ONLY','baseHash':result['codeSha256'],'diff':result['diff'],
                    'model':result['model'],'usage':result['usage'],'runtimePreflight':result.get('runtimePreflight'),'validationAttempts':result.get('validationAttempts',[]),'deployAllowed':False}
            ok=False
        elif operation=='ai-propose' and e.get('processAIKind')=='EXECUTE_PROCESS_25029':
            wf=process_ai.Workflow(_process_folder(cli,e))
            result=wf.propose(profile=req.get('profile') or 'ssis-glue-poc',region=req.get('region') or 'ap-southeast-2',
                model=req.get('modelId') or 'amazon.nova-lite-v1:0',approve_cost=req.get('approveModelCost') is True,
                approve_transmission=req.get('approveCodeTransmission') is True)
            result={'status':'AI_PATCH_REVIEW_ONLY','baseHash':result['codeSha256'],'diff':result['diff'],
                    'model':result['model'],'usage':result['usage'],'runtimePreflight':result.get('runtimePreflight'),'validationAttempts':result.get('validationAttempts',[]),'deployAllowed':False}
            ok=False
        elif operation=='ai-propose':
            result=cli.quick_ai({**inner,'profile':req.get('profile'),'region':req.get('region'),
                                 'modelId':req.get('modelId'),'approveModelCost':req.get('approveModelCost') is True,
                                 'approveCodeTransmission':req.get('approveCodeTransmission') is True})
            ok=result.get('status')=='NO_STATIC_DEFECTS_TO_REPAIR'
        elif operation=='ai-accept' and e.get('processAIKind')=='EXECUTE_PROCESS_25029':
            wf=process_ai.Workflow(_process_folder(cli,e))
            result=wf.approve(req.get('baseHash'),req.get('approveExactDiff') is True)
            result['blockers']=['Awaiting independent local Spark output parity; automatic Glue deployment is disabled for this adapter']
            ok=False
        elif operation=='ai-local-validate':
            if e.get('processAIKind')!='EXECUTE_PROCESS_25029':raise ValueError('No unsupported task patch pending local validation')
            wf=process_ai.Workflow(_process_folder(cli,e))
            result=wf.validate()
            ok=result.get('status') in ('MATCH','OUTPUT_GENERATED')
            if not ok:
                remedy = (' Click Generate AI fixes where needed to prepare a NEW review-only correction; '
                          'the previous approved code remains unchanged until you approve the new diff.'
                          if result.get('nextAction')=='REGENERATE_AI_FOR_REVIEW' else
                          ' Check the Local runtime settings and source input files before retrying validation.')
                raise ValueError('Local Spark validation failed: '+str(result.get('error',''))[:260]+'.'+remedy)
        elif operation=='ai-accept':
            result=cli.quick_accept({**inner,'baseHash':req.get('baseHash'),
                                     'approveExactDiff':req.get('approveExactDiff')})
            ok=not result.get('blockers')
        elif operation in ('aws','deploy','run','poll') and (e.get('processAIKind')=='EXECUTE_PROCESS_25029' or e.get('unsupportedProcessAI')):
            ai=_process_folder(cli,e)
            if operation=='aws':
                # Migrate existing successful v2.9.4 sessions without rerunning
                # SCT/Bedrock. Re-execute the approved hash locally once because
                # older releases did not persist post-approval proof.
                if not (ai/'local-validation-evidence.json').is_file():
                    old=process_ai.read_json(ai/'manifest.json')
                    if old.get('status') in ('LOCAL_OUTPUT_GENERATED','LOCAL_PARITY_MATCH'):
                        rerun=process_ai.Workflow(ai).validate()
                        if rerun.get('status') not in ('MATCH','OUTPUT_GENERATED'):
                            raise ValueError('Previous local validation could not be reconfirmed: '+str(rerun.get('error',''))[:220])
                from cloud import validate_settings,identity
                cfg=validate_settings(req)
                process_glue._record(ai)  # exact approved code + post-approval Spark proof
                result={'status':'AWS_VERIFIED','identity':identity(cfg),'source':'APPROVED_AI_CANDIDATE'}
            elif operation=='deploy':
                if not req.get('approvePortfolioDeployment'):
                    raise ValueError('Explicit deployment and AWS charges approval required')
                result=process_glue.deploy(ai,session,req,approve=True)
                e['jobName']=result['jobName'];e['aiOutputS3']=result['outputS3']
                e['sctWarnings']=e.get('blockers',[])
                e['blockers']=[]  # Historical SCT 25029 remains in sctWarnings and assessment
            elif operation=='run':
                if not req.get('approvePortfolioExecution'):
                    raise ValueError('Explicit Glue execution and charges approval required')
                result=process_glue.run(ai,approve=True)
                e['runId']=result['runId'];e['glueStatus']='SUBMITTED'
            else:
                result=process_glue.poll(ai)
                e['glueStatus']='SUCCEEDED' if result['status'] in ('SUCCEEDED_OUTPUTS_GENERATED','SUCCEEDED_OUTPUT_CHECK_FAILED') else result['status']
                e['cloudOutputValidated']=result.get('cloudOutputValidated',False)
                e['cloudOutputs']=result.get('outputs',[])
                e['cloudOutputArchiveAvailable']=result.get('outputArchiveAvailable',False)
                e['cloudSSISParity']=result.get('ssisParity','NOT_PROVEN')
            ok= True
        elif operation=='aws':
            result=cli.quick_aws({**inner,**{k:req.get(k) for k in ('profile','region','s3Prefix','glueRole','glueConnectionName','jdbcSecretArn','jdbcJarS3')}})
            ok=True
        elif operation=='deploy':
            if not req.get('approvePortfolioDeployment'):
                raise ValueError('Explicit approval required for this portfolio deployment batch')
            if e.get('blockers'):raise ValueError('Package has unresolved analysis blockers')
            # Bulk must never silently substitute demo fixtures for an uploaded
            # package's undeclared/missing source data.
            report_path=cli.session_path(session)/'quick'/'report.json'
            if not report_path.is_file():raise ValueError('Analyze the SCT package before deployment')
            report=json.loads(report_path.read_text('utf-8'))
            missing=[n for n in report.get('inputs',[]) if
                     not (cli.session_path(session)/'inputs'/n).is_file()]
            if missing:raise ValueError('Missing required source files from selected folder: '+', '.join(missing)+'; return to Step 1 and select the complete source folder')
            result=cli.quick_deploy({**inner,'approveCharges':True,'approveSctCode':True,
                                     'approveSqlServerMutations':req.get('approveSqlServerMutations') is True})
            ok=True
        elif operation=='run':
            if not req.get('approvePortfolioExecution'):
                raise ValueError('Explicit approval required for billable portfolio execution')
            # Even a legacy status-only record is evidence of a previous Glue
            # invocation. Fail closed rather than accidentally bill twice.
            q=cli.session_path(session)/'quick'
            if ((q/'run.json').is_file() or (q/'status.json').is_file() or
                e.get('runId') or e.get('glueStatus') in
                ('SUBMITTED','STARTING','RUNNING','STOPPING','SUCCEEDED')):
                raise ValueError('Existing Glue run found; poll status instead of starting another')
            result=cli.quick_run({**inner,'approveCharges':True});ok=True
        elif operation=='poll':
            result=cli.quick_poll(inner);ok=result.get('status')=='SUCCEEDED'
        elif operation=='validate':
            if not req.get('contentBase64'):
                raise ValueError('Provide an independent baseline CSV for this output')
            output=req.get('outputName')
            if e.get('aiCloudOrigin')=='APPROVED_BEDROCK_SCT_25029' or e.get('processAIKind')=='EXECUTE_PROCESS_25029':
                # A genuine approved AI output has no SCT quick/report.json.
                # Pin validation to the exact inspected cloud job, run, S3 prefix
                # and approved code hash. No output files are used as baselines.
                import base64
                try:
                    baseline=base64.b64decode(req['contentBase64'],validate=True)
                except (ValueError,TypeError) as ex:
                    raise ValueError('Invalid reference CSV encoding') from ex
                result=process_glue.validate_cloud_csv(_process_folder(cli,e),output,baseline)
            else:
                result=cli.quick_validate_outputs({**inner,'outputName':output,
                                                   'contentBase64':req.get('contentBase64')})
            ok=result.get('status')=='MATCH'
            e.setdefault('validation',{})[output]={'status':result.get('status'),
                'baselineSha256':result.get('baselineSha256'),'actualRows':result.get('actualRows'),
                'verified':bool(result.get('verified'))}
        if e.get('processAIKind')=='EXECUTE_PROCESS_25029' and operation in ('deploy','run','poll'):
            e['state']=('DEPLOYED' if operation=='deploy' else 'RUN_SUBMITTED' if operation=='run'
                else 'GLUE_OUTPUT_GENERATED' if result['status']=='SUCCEEDED_OUTPUTS_GENERATED'
                else 'GLUE_OUTPUT_CHECK_FAILED' if result['status'] in ('SUCCEEDED_OUTPUT_CHECK_FAILED','SUCCEEDED_OUTPUT_CONTRACT_MISMATCH')
                else 'GLUE_FAILED' if result['status'] in ('FAILED','TIMEOUT','STOPPED','ERROR')
                else 'GLUE_PENDING_OR_FAILED')
        else:
            e['state']={'convert':'CONVERTED' if ok else 'CONVERSION_REVIEW',
                    'analyze':'READY_FOR_DEPLOYMENT' if ok else 'REPAIR_BLOCKED',
                    'ai-propose':'NO_AI_NEEDED' if ok else 'AI_REVIEW_REQUIRED',
                    'ai-accept':'REPAIR_VALIDATED' if ok else 'AI_APPROVED_PENDING_LOCAL_TEST',
                    'ai-local-validate':'LOCAL_PARITY_MATCH' if result.get('status')=='MATCH' else 'LOCAL_OUTPUT_GENERATED' if ok else 'RUNTIME_VALIDATION_FAILED',
                    'aws':'AWS_VERIFIED','deploy':'DEPLOYED','run':'RUN_SUBMITTED',
                    'poll':'GLUE_SUCCEEDED' if ok else 'GLUE_PENDING_OR_FAILED',
                    'validate':('OUTPUTS_MATCH' if ok and e.get('outputs') and
                        all(e.get('validation',{}).get(n,{}).get('status')=='MATCH' for n in e['outputs'] if str(n).lower().endswith('.csv')) and
                        all(str(n).lower().endswith('.csv') for n in e['outputs'])
                        else 'PARTIAL_VALIDATION' if ok else 'CSV_MISMATCH')}[operation]
        e['lastError']=None
        if operation=='ai-propose' and result.get('baseHash'):e['pendingBaseHash']=result['baseHash']
        if operation=='ai-accept' and e.get('processAIKind')=='EXECUTE_PROCESS_25029':e.pop('pendingBaseHash',None)
        e['history'].append({'at':cli.moment(),'operation':operation,'status':e['state']})
    except Exception as exc:
        e['state']='ERROR_'+str(operation).upper().replace('-','_')
        e['lastError']=str(exc)[:400]
        e['history'].append({'at':cli.moment(),'operation':operation,'error':e['lastError']})
        plan['updatedAt']=cli.moment();_save(cli,p,plan)
        raise
    plan['updatedAt']=cli.moment();_save(cli,p,plan)
    return {'package':e['name'],'sessionId':session,'state':e['state'],'result':result}

def latest(cli):
    root=_home(cli)
    if not root.is_dir():return {'status':'NO_PORTFOLIO'}
    files=sorted(root.glob('*/portfolio.json'),key=lambda x:x.stat().st_mtime,reverse=True)
    for f in files:
        try:return status(cli,{'portfolioId':f.parent.name})
        except (ValueError,OSError):continue
    return {'status':'NO_PORTFOLIO'}
