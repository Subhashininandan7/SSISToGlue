"""Read-only, baseline-driven comparison of genuine Glue S3 CSV outputs.

No hard-coded package names, field names, expected rows, or fixture values.
The caller pins the S3 prefix to the successful deployment manifest.
"""
from __future__ import annotations
import csv
import hashlib
import io
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

MAX_BYTES=5_000_000
MAX_OBJECTS=50

class OutputValidationError(ValueError):pass

def parse_s3(uri):
    if not isinstance(uri,str) or not uri.startswith('s3://'):
        raise OutputValidationError('Invalid deployment S3 prefix')
    rest=uri[5:]
    bucket,sep,key=rest.partition('/')
    if not sep or not bucket or not key:raise OutputValidationError('Invalid S3 bucket/prefix')
    return bucket,key.rstrip('/')

def _parse_csv(data):
    try: text=data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:raise OutputValidationError('CSV must be UTF-8') from exc
    try:
        reader=csv.reader(io.StringIO(text,newline=''),strict=True)
        records=list(reader)
    except csv.Error as exc:raise OutputValidationError('Invalid CSV format') from exc
    if not records:raise OutputValidationError('Empty CSV including header')
    header=records[0]
    if not header or any(not name.strip() for name in header):raise OutputValidationError('Missing CSV header name')
    normalized=[x.strip().casefold() for x in header]
    if len(set(normalized))!=len(normalized):raise OutputValidationError('Case-insensitive duplicate headers')
    if any(len(row)!=len(header) for row in records[1:]):raise OutputValidationError('Inconsistent CSV field count')
    return normalized,records[1:]

def _value(s):
    # Compare numeric formatting, but keep IDs with leading zeros distinct.
    s=s.strip()
    if s and not (len(s)>1 and s[0]=='0' and s[1].isdigit()):
        try:
            v=Decimal(s)
            if v.is_finite():return ('number',str(v.normalize()))
        except InvalidOperation:pass
    return ('text',s)

def validate_s3_csv_outputs(s3,base_s3,output_name,expected):
    if not isinstance(output_name,str) or not output_name.lower().endswith('.csv') or '/' in output_name or '\\' in output_name or output_name in ('.','..'):
        raise OutputValidationError('Only a declared CSV output folder is supported')
    if not isinstance(expected,bytes) or len(expected)>MAX_BYTES:
        raise OutputValidationError('Reference CSV exceeds 5 MB')
    bucket,prefix=parse_s3(base_s3)
    target=prefix+'/'+output_name+'/'
    paginator=s3.get_paginator('list_objects_v2')
    keys=[];size=0
    for page in paginator.paginate(Bucket=bucket,Prefix=target):
        for obj in page.get('Contents',[]):
            key=obj['Key']
            if not key.startswith(target):continue
            # only Spark's data parts, never _SUCCESS or unrelated nested objects
            if not PurePosixPath(key).name.startswith('part-') or not key.lower().endswith('.csv'):continue
            if '/' in key[len(target):]:continue
            size+=obj['Size'];keys.append(key)
            if len(keys)>MAX_OBJECTS or size>MAX_BYTES:raise OutputValidationError('Output exceeds safe 50 files / 5 MB validation limit')
    if not keys:raise OutputValidationError('No actual Spark CSV part files under the declared output folder')
    exp_cols,exp_rows=_parse_csv(expected)
    actual_rows=[];actual_cols=None
    for key in sorted(keys):
        data=s3.get_object(Bucket=bucket,Key=key)['Body'].read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise OutputValidationError('S3 CSV part exceeds size limit')
        cols,rows=_parse_csv(data)
        if actual_cols is None:actual_cols=cols
        if cols!=actual_cols:raise OutputValidationError('Part files have inconsistent schemas')
        actual_rows.extend(rows)
        if len(actual_rows)>150_000:raise OutputValidationError('Too many CSV rows for local comparison')
    if set(exp_cols)!=set(actual_cols):
        return {'status':'SCHEMA_MISMATCH','verified':False,'expectedColumns':exp_cols,'actualColumns':actual_cols,
                'baselineSha256':hashlib.sha256(expected).hexdigest(),'filesRead':len(keys),'source':'REAL_AWS_S3'}
    # Reorder columns so a different physical order isn't mistaken for different data.
    positions=[actual_cols.index(name) for name in exp_cols]
    expected_counts=Counter(tuple(_value(s) for s in row) for row in exp_rows)
    actual_counts=Counter(tuple(_value(row[i]) for i in positions) for row in actual_rows)
    missing=sum((expected_counts-actual_counts).values())
    unexpected=sum((actual_counts-expected_counts).values())
    passed=(missing==0 and unexpected==0)
    return {'status':'MATCH' if passed else 'DATA_MISMATCH','verified':passed,
            'expectedRows':len(exp_rows),'actualRows':len(actual_rows),
            'missingRows':missing,'unexpectedRows':unexpected,'filesRead':len(keys),
            'baselineSha256':hashlib.sha256(expected).hexdigest(),
            'source':'REAL_AWS_S3','reference':'USER_SUPPLIED_BASELINE',
            'parityScope':'S3_CSV_VS_SUPPLIED_BASELINE_ONLY',
            'notice':'Full SSIS parity is established only when baseline is from a trusted original SSIS run.'}
