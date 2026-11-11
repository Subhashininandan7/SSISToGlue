"""Runtime configuration for REAL SQL Server JDBC jobs; reused from older Studio
configuration contracts: Glue VPC Connection, Secrets Manager and JDBC jar.
Never writes passwords, keys or network configuration guesses into artifacts.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse

ARN=re.compile(r'^arn:aws:secretsmanager:[a-z0-9-]+:\d{12}:secret:[A-Za-z0-9/_+=.@-]+$')
CONNECTION=re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,254}$')

class JdbcConfigError(ValueError):pass

def validate(cfg):
    con=str(cfg.get('glueConnectionName','')).strip()
    arn=str(cfg.get('jdbcSecretArn','')).strip()
    jar=str(cfg.get('jdbcJarS3','')).strip()
    if not CONNECTION.fullmatch(con):raise JdbcConfigError('Specify an existing AWS Glue VPC Connection for the reachable SQL Server')
    if not ARN.fullmatch(arn):raise JdbcConfigError('Specify a Secrets Manager ARN containing SQL Server JDBC URL and SQL-auth credentials')
    region=cfg.get('region','ap-southeast-2')
    if arn.split(':')[3]!=region:raise JdbcConfigError('SQL secret region must match Glue job region')
    uri=urlparse(jar)
    if jar and (uri.scheme!='s3' or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{2,62}',uri.netloc) or not uri.path.lower().endswith('.jar') or '..' in uri.path.split('/')):
        raise JdbcConfigError('Set jdbcJarS3 to the genuine Microsoft JDBC driver .jar in S3')
    return {'glueConnectionName':con,'jdbcSecretArn':arn,'jdbcJarS3':jar}

def validate_and_probe(cfg,glue,s3):
    """Cloud metadata checks only. Network/SQL auth are verified by real Glue run."""
    result=validate(cfg)
    # Existence check. Connection must have physical network settings attached;
    # Glue job binding supplies an ENI in its subnet/security group.
    info=glue.get_connection(Name=result['glueConnectionName'],HidePassword=True)['Connection']
    phys=info.get('PhysicalConnectionRequirements') or {}
    if not (phys.get('SubnetId') and phys.get('SecurityGroupIdList')):
        raise JdbcConfigError('Glue Connection requires a VPC subnet and security group with SQL Server access')
    import boto3
    secrets=boto3.Session(profile_name=cfg['profile'],region_name=cfg['region']).client('secretsmanager')
    metadata=secrets.describe_secret(SecretId=result['jdbcSecretArn'])
    if metadata.get('DeletedDate'):
        raise JdbcConfigError('The configured SQL Server secret is scheduled for deletion')
    if result['jdbcJarS3']:
        uri=urlparse(result['jdbcJarS3'])
        s3.head_object(Bucket=uri.netloc,Key=uri.path.lstrip('/'))
    return result
