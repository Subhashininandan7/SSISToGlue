"""Cloud lane for exact approved SCT-25029 replacement. No reference-code substitution.
This module never alters the generic SCT/SQL deployment lane.
"""
from __future__ import annotations
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse
import cloud
from unsupported_process_ai import read_json, write_json, inspect_python, sha, RemediationBlocked, approved_candidate_bytes

NAME=re.compile(r'^[A-Za-z0-9_.-]{1,100}\.csv$',re.I)
JOB=re.compile(r'^ssis-ai-[a-f0-9]{16}$')
RUN=re.compile(r'^jr_[A-Za-z0-9_-]{6,150}$')

def _record(root):
    root=Path(root)
    m=read_json(root/'manifest.json')
    if m.get('status') not in ('LOCAL_OUTPUT_GENERATED','LOCAL_PARITY_MATCH'):
        raise RemediationBlocked('Approved AI candidate must pass independent local Spark validation first')
    p=read_json(root/'proposal.json')
    candidate=root/'candidate.py'
    if p.get('status')!='AI_PATCH_REVIEW_ONLY' or not candidate.is_file():
        raise RemediationBlocked('Missing approved Bedrock candidate')
    contents=approved_candidate_bytes(root,m,p)
    if sha((root/'original.dtsx').read_bytes())!=m['packageSha256'] or sha((root/'sct-original.zip').read_bytes())!=m['sctZipSha256'] or sha((root/'support.ps1').read_bytes())!=m['scriptSha256']:
        raise RemediationBlocked('SSIS/SCT/external source evidence changed')
    inspect_python(contents.decode('utf-8'))
    for name, digest in m.get('inputSha256',{}).items():
        if not NAME.fullmatch(name) or not (root/'input'/name).is_file() or sha((root/'input'/name).read_bytes())!=digest:
            raise RemediationBlocked('Input source changed or unsafe: '+name)
    if not m.get('inputs') or set(m['inputs'])!=set(m['inputSha256']):
        raise RemediationBlocked('At least one approved, unchanged CSV input is required')
    validated=read_json(root/'local-validation-evidence.json') if (root/'local-validation-evidence.json').is_file() else None
    if not validated or validated.get('codeSha256')!=sha(contents) or validated.get('status') not in ('MATCH','OUTPUT_GENERATED'):
        raise RemediationBlocked('Missing independent post-approval local validation for this exact code')
    return m,p,contents,validated

def _entry():
    return '''# Entry point for approved AI repair; exact candidate ZIP is provided by Glue.
import sys
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession
from ai_candidate import transform

def main():
    args = getResolvedOptions(sys.argv, ["INPUT_PREFIX", "OUTPUT_PREFIX"])
    spark = SparkSession.builder.getOrCreate()
    transform(spark, args["INPUT_PREFIX"].rstrip("/"), args["OUTPUT_PREFIX"].rstrip("/"))

if __name__ == "__main__":
    main()
'''

def _zip_candidate(code):
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('ai_candidate.py',code)
    return mem.getvalue()

def deploy(root, session_id, settings, *, approve=False, client_factory=None):
    if not approve:raise RemediationBlocked('Explicit approval required for AWS charges and deployment of reviewed AI code')
    if not re.fullmatch('[a-f0-9]{16}',session_id):raise RemediationBlocked('Invalid source session')
    root=Path(root)
    m,p,code,validated=_record(root)
    cfg=cloud.validate_settings(settings)
    if (root/'cloud-deployment.json').exists():raise RemediationBlocked('AI Glue job already deployed; never overwrite or redeploy')
    s3,glue,sts,logs=(client_factory or cloud.clients)(cfg['profile'],cfg['region'])
    account=sts.get_caller_identity()['Account']
    name='ssis-ai-'+session_id
    try:glue.get_job(JobName=name)
    except glue.exceptions.EntityNotFoundException:pass
    else:raise RemediationBlocked('Glue job already exists; do not overwrite')
    base=f"{cfg['prefix']}/{session_id}/approved-ai"
    s3base=f"s3://{cfg['bucket']}/{base}"
    for filename in m['inputs']:
        s3.put_object(Bucket=cfg['bucket'],Key=f'{base}/input/{filename}',Body=(root/'input'/filename).read_bytes(),ContentType='text/csv',ServerSideEncryption='AES256')
    entry=_entry().encode()
    z=_zip_candidate(code)
    s3.put_object(Bucket=cfg['bucket'],Key=f'{base}/scripts/entry.py',Body=entry,ContentType='text/x-python',ServerSideEncryption='AES256')
    s3.put_object(Bucket=cfg['bucket'],Key=f'{base}/scripts/approved_ai.zip',Body=z,ContentType='application/zip',ServerSideEncryption='AES256')
    props={'Role':cfg['glueRole'], 'Command':{'Name':'glueetl','ScriptLocation':s3base+'/scripts/entry.py','PythonVersion':'3'},
       'GlueVersion':'5.0','WorkerType':'G.1X','NumberOfWorkers':2,'Timeout':20,'MaxRetries':0,
       'DefaultArguments':{'--INPUT_PREFIX':s3base+'/input','--OUTPUT_PREFIX':s3base+'/output',
            '--extra-py-files':s3base+'/scripts/approved_ai.zip','--job-language':'python'},
       'Description':'Exact reviewed Bedrock-generated replacement for genuine SCT-25029; original SCT warning retained; SSIS parity not implied'}
    glue.create_job(Name=name,**props)
    result={'status':'AWS_JOB_CREATED_NOT_RUN','origin':'APPROVED_BEDROCK_SCT_25029','jobName':name,
        'sourceSession':session_id,'approvedCodeSha256':sha(code),'entrySha256':sha(entry),
        'moduleZipSha256':sha(z),'inputSha256':m['inputSha256'],'inputS3':s3base+'/input',
        'outputS3':s3base+'/output','scriptS3':s3base+'/scripts/entry.py',
        'account':account,'profile':cfg['profile'],'region':cfg['region'],'bucket':cfg['bucket'],
        'referenceParity':'LOCAL_REFERENCE_MATCH_ONLY_CLOUD_UNVERIFIED' if m['status']=='LOCAL_PARITY_MATCH' else 'NOT_PROVEN',
        'cloudOutputValidated':False}
    write_json(root/'cloud-deployment.json',result)
    return result

def run(root, *, approve=False, client_factory=None):
    root=Path(root)
    if not approve:raise RemediationBlocked('Explicit Glue execution/charges approval required')
    m,p,code,v=_record(root)
    d=read_json(root/'cloud-deployment.json')
    if sha(code)!=d['approvedCodeSha256']:raise RemediationBlocked('Candidate changed after cloud deployment')
    if (root/'cloud-run.json').exists():raise RemediationBlocked('Existing Glue job run found; poll it instead')
    if not JOB.fullmatch(d['jobName']):raise RemediationBlocked('Invalid approved AI job')
    _,glue,_,_=(client_factory or cloud.clients)(d['profile'],d['region'])
    response=glue.start_job_run(JobName=d['jobName'])
    item={'status':'SUBMITTED','runId':response['JobRunId'],'jobName':d['jobName'],'origin':'REAL_AWS_GLUE'}
    write_json(root/'cloud-run.json',item)
    return item

def _outputs(s3,d):
    bucket,prefix=cloud.parse_s3_url(d['outputS3'])
    if bucket!=d['bucket']:raise RemediationBlocked('Output bucket mismatch')
    base=prefix.rstrip('/')+'/'
    objects=[]
    for page in s3.get_paginator('list_objects_v2').paginate(Bucket=bucket,Prefix=base):
        for item in page.get('Contents',[]):
            key=item['Key'];size=item.get('Size',0)
            if key.endswith('.csv') and key.split('/')[-1].startswith('part-'):
                if size>5_000_000:raise RemediationBlocked('Cloud CSV output is over 5MB per part')
                objects.append({'key':key,'bytes':size})
                if len(objects)>100:raise RemediationBlocked('Too many CSV output parts')
    if not objects:raise RemediationBlocked('Glue succeeded but no actual CSV part files were found')
    byfolder={}
    for o in objects:
        rel=o['key'][len(base):]
        if '/' not in rel or '..' in rel.split('/') or len(rel)>250:raise RemediationBlocked('Unexpected output path')
        folder=rel.rsplit('/',1)[0]
        byfolder.setdefault(folder,[]).append(o)
    import csv,io
    records=[]
    for folder,partfiles in sorted(byfolder.items()):
        rows=0;header=None
        for part in partfiles:
            body=s3.get_object(Bucket=bucket,Key=part['key'])['Body'].read(5_000_001)
            if len(body)>5_000_000:raise RemediationBlocked('Oversized cloud output')
            reader=csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
            cols=reader.fieldnames or []
            if not cols:raise RemediationBlocked('Cloud CSV output missing header')
            if header is not None and header!=cols:raise RemediationBlocked('Cloud output schema differs across parts')
            header=cols
            rows+=sum(1 for _ in reader)
        records.append({'output':folder,'columns':header,'rows':rows,'partFiles':len(partfiles),'s3':d['outputS3']+'/'+folder, 'objectKeys':[x['key'] for x in partfiles]})
    return records

def validate_cloud_csv(root, output_name, baseline, client_factory=None):
    """Compare a real AI-repaired Glue output to an explicitly supplied baseline.

    Output inventory, run identity, and S3 location come only from the pinned
    successful cloud manifest. A generated output is NOT its own reference.
    """
    from output_validation import validate_s3_csv_outputs
    root=Path(root)
    d=read_json(root/'cloud-deployment.json')
    run=read_json(root/'cloud-run.json')
    state=read_json(root/'cloud-status.json')
    m,p,code,local=_record(root)  # Fail closed on approval/hash changes.
    if sha(code)!=d.get('approvedCodeSha256'):
        raise RemediationBlocked('Approved AI code hash differs from deployed code')
    if run.get('jobName')!=d.get('jobName') or state.get('jobName')!=d.get('jobName') or state.get('runId')!=run.get('runId'):
        raise RemediationBlocked('Cloud output evidence belongs to a different Glue job/run')
    if (state.get('status')!='SUCCEEDED_OUTPUTS_GENERATED' or not state.get('cloudOutputValidated')
        or state.get('localCloudContractMatch') is False):
        raise RemediationBlocked('Successful Glue execution and inspected output required before baseline validation')
    declared=[x.get('output') for x in state.get('outputs',[]) if isinstance(x,dict)]
    if not isinstance(output_name,str) or output_name not in declared or not output_name.lower().endswith('.csv'):
        raise RemediationBlocked('Output is not declared in the inspected cloud manifest')
    s3,_,_,_=(client_factory or cloud.clients)(d['profile'],d['region'])
    result=validate_s3_csv_outputs(s3,d['outputS3'],output_name,baseline)
    saved=root/'cloud-validation.json'
    evidence=read_json(saved) if saved.exists() else {}
    anchor={'runId':run['runId'],'jobName':d['jobName'],'outputS3':d['outputS3'],
            'approvedCodeSha256':sha(code)}
    if any(evidence.get(k)!=v for k,v in anchor.items()):
        evidence={**anchor,'results':{}}
    evidence['results'][output_name]={k:result.get(k) for k in (
        'status','verified','baselineSha256','actualRows','expectedRows','missingRows',
        'unexpectedRows','source','reference','parityScope')}
    write_json(saved,evidence)
    return result


def _archive_outputs(root,s3,d,outputs):
    """Export bounded actual Glue CSVs for inspection; never invent sample data."""
    root=Path(root)
    prefix=cloud.parse_s3_url(d['outputS3'])[1].rstrip('/')+'/'
    temp=root/'cloud-output.tmp.zip'
    final=root/'cloud-output.zip'
    final.unlink(missing_ok=True)
    total=0
    with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for output in outputs:
            for key in output['objectKeys']:
                if not key.startswith(prefix) or '..' in key[len(prefix):].split('/'):
                    raise RemediationBlocked('Unsafe cloud output object key')
                data=s3.get_object(Bucket=d['bucket'],Key=key)['Body'].read(5_000_001)
                total+=len(data)
                if len(data)>5_000_000 or total>20_000_000:
                    raise RemediationBlocked('Cloud output exceeds bounded 20MB download size')
                z.writestr(key[len(prefix):],data)
        z.writestr('output-manifest.json',json.dumps({'outputs':[
            {k:v for k,v in o.items() if k!='objectKeys'} for o in outputs],
            'originalSSISParity':'NOT_PROVEN_BY_CLOUD_OUTPUT_GENERATION'},indent=2))
    temp.replace(final)
    return True

def poll(root, client_factory=None):
    root=Path(root)
    d=read_json(root/'cloud-deployment.json');r=read_json(root/'cloud-run.json')
    if not JOB.fullmatch(d['jobName']) or r['jobName']!=d['jobName'] or not RUN.fullmatch(r['runId']):
        raise RemediationBlocked('Invalid Glue run identity')
    s3,glue,sts,logs=(client_factory or cloud.clients)(d['profile'],d['region'])
    job=glue.get_job_run(JobName=d['jobName'],RunId=r['runId'],PredecessorsIncluded=False)['JobRun']
    status=job['JobRunState']
    report={'status':status,'jobName':d['jobName'],'runId':r['runId'],
            'origin':'REAL_AWS_GLUE','cloudOutputValidated':False,
            'ssisParity':d['referenceParity'],'error':str(job.get('ErrorMessage',''))[:1000]}
    if status=='SUCCEEDED':
        try:
            report['outputs']=_outputs(s3,d)
            report['cloudOutputValidated']=True
            report['status']='SUCCEEDED_OUTPUTS_GENERATED'
            try:
                report['outputArchiveAvailable']=_archive_outputs(root,s3,d,report['outputs'])
            except (RemediationBlocked,OSError,UnicodeDecodeError) as export_error:
                report['outputArchiveAvailable']=False
                report['outputArchiveError']=str(export_error)[:250]
        except (RemediationBlocked,UnicodeDecodeError,ValueError) as e:
            report['status']='SUCCEEDED_OUTPUT_CHECK_FAILED'
            report['outputError']=str(e)[:500]
        except Exception as e:
            report['status']='SUCCEEDED_OUTPUT_CHECK_FAILED'
            report['outputError']='Cloud output listing/inspection failed: '+type(e).__name__
        if report['cloudOutputValidated']:
            # Compare cloud output contracts to observed local outputs. This is
            # NOT an independent original-SSIS parity claim.
            local=read_json(root/'local-validation-evidence.json').get('outputs',[])
            expected={x['name']:(x.get('actualRows'), x.get('columns')) for x in local if x.get('name')}
            actual={x['output']:(x['rows'],x['columns']) for x in report.get('outputs',[])}
            differences=[]
            if expected and set(expected)!=set(actual):
                differences.append('Cloud output names differ from locally observed output names')
            for name, (count, cols) in expected.items():
                got=actual.get(name)
                if got and count is not None and got[0]!=count:
                    differences.append('Cloud row count differs from local validation: '+name)
                if got and cols and got[1]!=cols:
                    differences.append('Cloud CSV columns differ from local validation: '+name)
            report['localCloudContractMatch']=not differences
            if differences:
                report['status']='SUCCEEDED_OUTPUT_CONTRACT_MISMATCH'
                report['cloudOutputValidated']=False
                report['contractIssues']=differences
    elif status in ('FAILED','TIMEOUT','STOPPED','ERROR'):
        try:
            events=logs.filter_log_events(logGroupName='/aws-glue/jobs/error',filterPattern=r['runId'],limit=25)
            report['logLines']=[x.get('message','')[:700] for x in events.get('events',[])][-15:]
        except Exception as exc:report['logsUnavailable']=type(exc).__name__
    write_json(root/'cloud-status.json',report)
    return report
