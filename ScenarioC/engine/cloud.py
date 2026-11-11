"""Real boto3-based AWS Glue demo integration. No emulated AWS success states."""
from __future__ import annotations
import csv
import io
import re
import time
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_JOB = re.compile(r'^ssis-(?:(?:demo-[abc]|sct-a)-[a-z0-9-]{1,32}|auto-[a-f0-9]{16})$')
PREFIX = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9./_-]{0,150}$')

class CloudError(RuntimeError):pass


def clients(profile,region):
    import boto3
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',profile):raise CloudError('Invalid AWS profile')
    if not re.fullmatch(r'[a-z]{2}-[a-z]+-\d',region):raise CloudError('Invalid AWS region')
    session=boto3.Session(profile_name=profile,region_name=region)
    return session.client('s3'),session.client('glue'),session.client('sts'),session.client('logs')


def parse_s3_url(s):
    p=urlparse(s)
    if p.scheme!='s3' or not re.fullmatch('[a-z0-9][a-z0-9.-]{2,62}',p.netloc) or not p.path.strip('/'):
        raise CloudError('Provide an S3 bucket and a nonempty safe prefix')
    key=p.path.lstrip('/')
    if '..' in key.split('/') or not PREFIX.fullmatch(key):raise CloudError('Unsafe S3 prefix')
    return p.netloc,key.rstrip('/')


def validate_settings(cfg):
    profile=cfg.get('profile','ssis-glue-poc');region=cfg.get('region','ap-southeast-2')
    bucket,prefix=parse_s3_url(cfg['s3Prefix'])
    role=cfg.get('glueRole','')
    if not (re.fullmatch(r'arn:aws:iam::\d{12}:role/[\w+=,.@/-]{1,128}',role) or re.fullmatch(r'[\w+=,.@/-]{1,128}',role)):
        raise CloudError('Provide an existing approved Glue IAM role/ARN')
    return {'profile':profile,'region':region,'bucket':bucket,'prefix':prefix,'glueRole':role}


def identity(cfg):
    _,_,sts,_=clients(cfg['profile'],cfg['region'])
    data=sts.get_caller_identity()
    return {'account':data['Account'],'arn':data['Arn'],'region':cfg['region'],'source':'REAL_AWS_STS'}


def upload_inputs(s3,cfg,scenario,run_id,fixtures):
    from scenarios import SCENARIOS
    base=f"{cfg['prefix']}/{run_id}/{scenario}"
    for name in SCENARIOS[scenario]['inputs']:
        path=Path(fixtures)/'input'/name
        s3.put_object(Bucket=cfg['bucket'],Key=f'{base}/input/{name}',Body=path.read_bytes(),ContentType='text/csv',ServerSideEncryption='AES256')
    return f"s3://{cfg['bucket']}/{base}"


def deploy_reference(cfg,scenario,run_id,fixtures,script):
    if scenario not in ('A','B','C'):raise CloudError('Unsupported scenario')
    if not re.fullmatch('[a-f0-9]{16,32}',run_id):raise CloudError('Invalid run ID')
    s3,glue,sts,_=clients(cfg['profile'],cfg['region'])
    identity=sts.get_caller_identity()
    base=upload_inputs(s3,cfg,scenario,run_id,fixtures)
    bucket=cfg['bucket'];key=f"{cfg['prefix']}/{run_id}/{scenario}/scripts/reference_glue_job.py"
    s3.put_object(Bucket=bucket,Key=key,Body=Path(script).read_bytes(),ContentType='text/x-python',ServerSideEncryption='AES256')
    job=f'ssis-demo-{scenario.lower()}-{run_id[:16]}'
    if not ALLOWED_JOB.fullmatch(job):raise CloudError('Unexpected job name')
    args={'--SCENARIO':scenario,'--INPUT_PREFIX':base+'/input',
          '--OUTPUT_PREFIX':base+'/output','--AS_OF':'2026-11-08','--job-language':'python'}
    command={'Name':'glueetl','ScriptLocation':f's3://{bucket}/{key}','PythonVersion':'3'}
    job_props={'Role':cfg['glueRole'],'Command':command,'GlueVersion':'5.0',
               'WorkerType':'G.1X','NumberOfWorkers':2,'Timeout':20,'MaxRetries':0,
               'DefaultArguments':args,'Description':'Controlled CSV reference demo; NOT SCT generated.'}
    try:
        glue.get_job(JobName=job)
    except glue.exceptions.EntityNotFoundException:
        glue.create_job(Name=job,**job_props)
    else:
        glue.update_job(JobName=job,JobUpdate=job_props)
    return {'jobName':job,'scriptS3':command['ScriptLocation'],'inputS3':base+'/input','outputS3':base+'/output',
            'account':identity['Account'],'origin':'INDEPENDENT_REFERENCE_NOT_SCT','status':'AWS_JOB_CREATED_NOT_RUN'}


def start(cfg,job):
    if not ALLOWED_JOB.fullmatch(job):raise CloudError('Job name not allowlisted')
    _,glue,_,_=clients(cfg['profile'],cfg['region'])
    resp=glue.start_job_run(JobName=job)
    return {'jobName':job,'runId':resp['JobRunId'],'status':'SUBMITTED','origin':'REAL_GLUE_API'}


def check(cfg,job,run_id):
    if not ALLOWED_JOB.fullmatch(job) or not re.fullmatch(r'jr_[0-9a-zA-Z]{6,150}',run_id):
        raise CloudError('Invalid Glue job/run')
    _,glue,_,logs=clients(cfg['profile'],cfg['region'])
    run=glue.get_job_run(JobName=job,RunId=run_id,PredecessorsIncluded=False)['JobRun']
    state=run['JobRunState'];details={'status':state,'runId':run_id,'jobName':job,
        'startedAt':str(run.get('StartedOn','')),'finishedAt':str(run.get('CompletedOn','')),
        'error':str(run.get('ErrorMessage',''))[:1000], 'origin':'REAL_GLUE_API'}
    # Only job-specific, bounded CloudWatch logs; failure to read logs is nonfatal.
    if state in ('FAILED','TIMEOUT','STOPPED','ERROR'):
        try:
            result=logs.filter_log_events(logGroupName='/aws-glue/jobs/error',filterPattern=run_id,limit=30)
            details['logLines']=[x.get('message','')[:1000] for x in result.get('events',[])][-20:]
        except Exception as exc:
            details['logsUnavailable']=type(exc).__name__
    return details


def list_output_rows(s3,cfg,output_s3,folder):
    bucket,key=parse_s3_url(output_s3)
    if bucket!=cfg['bucket'] or not key.startswith(cfg['prefix']+'/'):
        raise CloudError('Output path is outside the configured demo prefix')
    if folder not in ('ActiveEmployees.csv','ValidOrders.csv','RejectedOrders.csv','DimCustomerHistory.csv'):
        raise CloudError('Unknown expected output')
    path=f"{key}/{folder}/"
    paginator=s3.get_paginator('list_objects_v2')
    blobs=[]
    for page in paginator.paginate(Bucket=bucket,Prefix=path):
        for item in page.get('Contents',[]):
            if item['Key'].split('/')[-1].startswith('part-') and item['Key'].endswith('.csv'):
                if item['Size']>2_000_000:raise CloudError('Demo output exceeds bounded read limit')
                blobs.append(item['Key'])
    if not blobs:raise CloudError('No CSV part files found under '+folder)
    if len(blobs)>25:raise CloudError('Too many CSV parts')
    rows=[]
    for blob in blobs:
        data=s3.get_object(Bucket=bucket,Key=blob)['Body'].read(2_000_001)
        if len(data)>2_000_000:raise CloudError('Output exceeds bounded read limit')
        rows.extend(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    return rows


def deploy_sct_candidate(cfg,scenario,run_id,fixtures,candidate_folder,preflight):
    """Deploy only staged SCT-derived code whose pinned hashes match reviewed files."""
    from sct_candidate import sha
    if scenario!='A':raise CloudError('SCT candidate deployment currently supports Scenario A only')
    if not re.fullmatch('[a-f0-9]{16,32}',run_id):raise CloudError('Invalid run ID')
    if preflight.get('status')!='SCT_SCENARIO_A_PREFLIGHT_READY_NOT_RUN':
        raise CloudError('SCT candidate failed preflight readiness')
    folder=Path(candidate_folder)
    script=folder/'glue_entry_sct_a.py';helpers=folder/'sct_modules.zip'
    if not script.is_file() or not helpers.is_file():raise CloudError('Prepared SCT candidate artifact missing')
    if sha(script.read_bytes())!=preflight['generatedEntrySha256'] or sha(helpers.read_bytes())!=preflight['pyModulesZipSha256']:
        raise CloudError('Prepared SCT candidate file changed after approval')
    s3,glue,sts,_=clients(cfg['profile'],cfg['region'])
    who=sts.get_caller_identity()
    base=upload_inputs(s3,cfg,scenario,run_id,fixtures)
    prefix=f"{cfg['prefix']}/{run_id}/{scenario}/scripts"
    entry_key=prefix+'/sct_glue_entry.py'
    helper_key=prefix+'/sct_generated_modules.zip'
    s3.put_object(Bucket=cfg['bucket'],Key=entry_key,Body=script.read_bytes(),ContentType='text/x-python',ServerSideEncryption='AES256')
    s3.put_object(Bucket=cfg['bucket'],Key=helper_key,Body=helpers.read_bytes(),ContentType='application/zip',ServerSideEncryption='AES256')
    output_prefix=base+'/sct-output'
    script_s3=f"s3://{cfg['bucket']}/{entry_key}"
    helper_s3=f"s3://{cfg['bucket']}/{helper_key}"
    job=f'ssis-sct-a-{run_id[:16]}'
    if not ALLOWED_JOB.fullmatch(job):raise CloudError('Unexpected job name')
    args={'--SCENARIO':'A','--INPUT_PREFIX':base+'/input','--OUTPUT_PREFIX':output_prefix,
          '--extra-py-files':helper_s3,'--job-language':'python'}
    props={'Role':cfg['glueRole'],
           'Command':{'Name':'glueetl','ScriptLocation':script_s3,'PythonVersion':'3'},
           'GlueVersion':'5.0','WorkerType':'G.1X','NumberOfWorkers':2,
           'Timeout':20,'MaxRetries':0,'DefaultArguments':args,
           'Description':('SCT-derived Scenario A with approved Bedrock SQL patch, deterministic repairs and source-bound preflight; NOT reference code'
                          if preflight.get('aiPatches') else
                          'SCT-derived Scenario A with deterministic repairs and source-bound preflight; NOT reference code')}
    try:glue.get_job(JobName=job)
    except glue.exceptions.EntityNotFoundException:glue.create_job(Name=job,**props)
    else:raise CloudError('SCT job already exists; refuse to overwrite an existing job')
    return {'jobName':job,'scriptS3':script_s3,'helpersS3':helper_s3,
            'inputS3':base+'/input','outputS3':output_prefix,
            'account':who['Account'],'origin':'SCT_CONVERTED_CANDIDATE',
            'sourceSha256':preflight['sourceSha256'],
            'scriptSha256':preflight['generatedEntrySha256'],
            'modulesSha256':preflight['pyModulesZipSha256'],
            'status':'AWS_SCT_JOB_CREATED_NOT_RUN','runtimeVerified':False,
            'repairOrigin':('APPROVED_BEDROCK_PLUS_DETERMINISTIC' if preflight.get('aiPatches') else 'DETERMINISTIC_ONLY')}
