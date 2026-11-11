"""Faithful *SQL Server-backed* narrow transport adapter for SCT's CSV->SQL-stage->lookup topology.

Unlike CSV lookup demo mode, this adapter actually creates/loads/queries the SQL Server
customer table. The original SSIS BULK INSERT uses a Windows-only local CSV path,
which cannot work in AWS Glue. We transfer *the same CSV bytes* into the same
SQL table in a JDBC transaction. This is a reviewed transport translation,
NOT an automatic guarantee of arbitrary SSIS semantics or SQL Server networking.
"""
from __future__ import annotations
import ast
import hashlib
import re

class UnsupportedSqlServer(ValueError):pass

_STAGE_SCRIPT = '''"""SQL Server CSV-staging transport for the reviewed SCT-derived workflow.
Preserves CREATE-if-absent, DELETE, bulk data load, RTRIM and lookup table state.
This translation substitutes prepared JDBC inserts for BULK INSERT from a Windows-local path.
Database access needs a reachable SQL Server, SQL authentication and an AWS Glue network connection.
"""
import csv
import io
import os
from pyspark.sql import SparkSession

_SQL_CREATE = "IF OBJECT_ID('dbo.DemoForgeCustomers','U') IS NULL CREATE TABLE dbo.DemoForgeCustomers (CustomerID varchar(120) NOT NULL PRIMARY KEY, CustomerName varchar(120) NOT NULL)"
_SQL_DELETE = "DELETE FROM dbo.DemoForgeCustomers"
_SQL_INSERT = "INSERT INTO dbo.DemoForgeCustomers (CustomerID, CustomerName) VALUES (?, ?)"
_SQL_TRIM = "UPDATE dbo.DemoForgeCustomers SET CustomerName=RTRIM(CustomerName)"

def stage_customers(connection):
    """Transactionally implement original SQL stage against REAL SQL Server.

    Uses Java SQL PreparedStatement on the same connection/transaction; no
    dangerous sessionInitStatement used as a read. The Glue role needs a
    Secrets Manager secret; the driver jar must be on the JVM classpath.
    """
    from pyspark.sql import SparkSession
    spark = SparkSession.builder.getOrCreate()
    cfg = connection['SOURCE']
    source = os.environ['MIGRATION_INPUT_PREFIX'].rstrip('/') + '/Customers.csv'
    # This demo is intentionally bounded. Do not collect large enterprise CSVs.
    data = spark.read.option('header', True).csv(source)
    names = {x.lower():x for x in data.columns}
    if set(names) != {'customerid', 'customername'}:
        raise ValueError('Staging CSV must contain exactly CustomerID, CustomerName')
    rows = data.select(names['customerid'], names['customername']).collect()
    if len(rows)>10000:
        raise ValueError('Only <=10000 staging rows permitted in reviewed sample adapter')
    values=[]
    seen=set()
    for row in rows:
        cid,cn=row[0],row[1]
        if cid is None or cn is None or not str(cid) or not str(cn):
            raise ValueError('SQL Server stage forbids NULL/empty customer fields')
        if len(cid)>120 or len(cn)>120 or cid in seen:
            raise ValueError('SQL Server stage varchar(120)/PK constraint failed')
        seen.add(cid)
        values.append((str(cid),str(cn)))
    jvm=spark.sparkContext._jvm
    jvm.java.lang.Class.forName('com.microsoft.sqlserver.jdbc.SQLServerDriver')
    sqlconn=jvm.java.sql.DriverManager.getConnection(cfg['JDBC_CONNECTION_URL'],cfg['USERNAME'],cfg['PASSWORD'])
    try:
        sqlconn.setAutoCommit(False)
        try:
            # DDL can be transactional in SQL Server; DELETE+INSERT+RTRIM
            # succeed or roll back as one unit when the server supports it.
            stmt=sqlconn.createStatement()
            try:
                stmt.execute(_SQL_CREATE)
                stmt.executeUpdate(_SQL_DELETE)
            finally:stmt.close()
            insert=sqlconn.prepareStatement(_SQL_INSERT)
            try:
                for cid,cn in values:
                    insert.setString(1,cid)
                    insert.setString(2,cn)
                    insert.addBatch()
                if values:insert.executeBatch()
            finally:insert.close()
            stmt=sqlconn.createStatement()
            try:stmt.executeUpdate(_SQL_TRIM)
            finally:stmt.close()
            sqlconn.commit()
        except BaseException:
            sqlconn.rollback()
            raise
    finally:sqlconn.close()
'''


def adapt(modules):
    copied=[dict(m) for m in modules]
    flow=[m for m in copied if all(s in m['source'] for s in ('spark.read.csv(', 'spark.read.format("jdbc")', '.join(', 'CUSTOMER_NOT_FOUND', 'write.mode("Overwrite").csv('))]
    stages=[m for m in copied if all(s in m['source'] for s in ('BULK INSERT','DELETE FROM','DemoForgeCustomers','sessionInitStatement'))]
    if len(flow)!=1 or len(stages)!=1 or flow[0] is stages[0]:
        raise UnsupportedSqlServer('Reviewed SQL Server adapter requires one CSV->SQL lookup data flow and one SQL staging coordinator')
    f,c=flow[0],stages[0]
    original=f['source'];stage=c['source']
    if any(x not in original.lower() for x in ['orders.csv','customerid','customername','quantity','unitprice','orderid']):
        raise UnsupportedSqlServer('Unsupported lookup columns or input')
    if original.count('.join(')!=1 or original.count('spark.read.format("jdbc")')!=1 or original.count('write.mode("Overwrite").csv(')!=2:
        raise UnsupportedSqlServer('Ambiguous joins, JDBC reads or outputs')
    if stage.count('spark.read.format("jdbc")')!=1 or stage.count('BULK INSERT')!=1:
        raise UnsupportedSqlServer('Ambiguous SQL stage')
    for fragment in ("OBJECT_ID('dbo.DemoForgeCustomers'",'CREATE TABLE dbo.DemoForgeCustomers','DELETE FROM dbo.DemoForgeCustomers','BULK INSERT dbo.DemoForgeCustomers',"UPDATE dbo.DemoForgeCustomers SET CustomerName=RTRIM(CustomerName)"):
        if fragment not in stage:raise UnsupportedSqlServer('Original SQL stage differs from reviewed CREATE/DELETE/BULK INSERT/UPDATE contract')
    # Disallow hidden extra SQL mutations and unreviewed source statements.
    if any(re.search(p,stage,re.I) for p in (r'\bDROP\s+TABLE\b',r'\bTRUNCATE\s+TABLE\b',r'\bMERGE\s+\w',r'\bEXEC(?:UTE)?\s+\w')):
        raise UnsupportedSqlServer('Unreviewed destructive/dynamic SQL must not be adapted')
    t=ast.parse(original);fn=[x for x in t.body if isinstance(x,ast.FunctionDef)]
    ct=ast.parse(stage);cfn=[x for x in ct.body if isinstance(x,ast.FunctionDef)]
    if len(fn)!=1 or len(cfn)!=1:raise UnsupportedSqlServer('Cannot identify exact SCT functions')
    if 'SELECT CustomerID, CustomerName FROM dbo.DemoForgeCustomers' not in original:
        raise UnsupportedSqlServer('SQL source query differs from reviewed customer lookup')
    outputs=re.findall(r'MIGRATION_OUTPUT_PREFIX"\]\s*\+\s*"/([^"\n]+\.csv)"',original)
    if len(outputs)!=2:raise UnsupportedSqlServer('Cannot prove two isolated output paths')
    rejected=next((x for x in outputs if 'reject' in x.lower()),None)
    valid=next((x for x in outputs if 'valid' in x.lower()),None)
    if not rejected or not valid:raise UnsupportedSqlServer('Cannot distinguish rejected/valid outputs')
    # Preserve CSV input read and actual JDBC SQL Server lookup; replace the broken
    # join/branches with a constrained, schema-preserving translation. Do not
    # substitute Customers.csv for the SQL Server lookup.
    new_flow=f'''# REVIEWED SCT DATAFLOW TRANSLATION: still reads dbo.DemoForgeCustomers through JDBC.
# Original code retained unchanged under sct/original and in the diff/provenance.
import os
from decimal import Decimal
from pyspark.sql import SparkSession
from pyspark.sql.functions import col,lit
from pyspark.sql.types import DecimalType
spark=SparkSession.builder.getOrCreate()

def {fn[0].name}(connection:dict):
    path=os.environ["MIGRATION_INPUT_PREFIX"].rstrip("/") + "/Orders.csv"
    output=os.environ["MIGRATION_OUTPUT_PREFIX"].rstrip("/")
    orders=spark.read.option("header",True).csv(path).select(
        col("orderid"),col("customerid"),col("quantity").cast("int").alias("quantity"),
        col("unitprice").cast(DecimalType(18,2)).alias("unitprice"))
    jdbc=connection["SOURCE"]
    # Actual original lookup query, qualified to avoid duplicate column ambiguity.
    customers=(spark.read.format("jdbc")
        .option("driver","com.microsoft.sqlserver.jdbc.SQLServerDriver")
        .option("url",jdbc["JDBC_CONNECTION_URL"])
        .option("user",jdbc["USERNAME"]).option("password",jdbc["PASSWORD"])
        .option("query","SELECT CustomerID AS lookup_customerid, CustomerName AS customername FROM dbo.DemoForgeCustomers")
        .load())
    # Lookup matches original customerid equijoin; use nullable RIGHT-hand key
    # to identify rejected orders (SCT incorrectly checked ambiguous left key).
    joined=orders.join(customers,orders["customerid"]==customers["lookup_customerid"],"left")
    matched=joined.where(col("lookup_customerid").isNotNull())
    missing=joined.where(col("lookup_customerid").isNull())
    rejected=missing.select(col("orderid"),col("customerid"),lit("CUSTOMER_NOT_FOUND").alias("reason"))
    valid=matched.select(col("orderid"),col("customerid"),col("customername"),col("quantity"),
        col("unitprice"),(col("quantity")*col("unitprice")).cast(DecimalType(18,2)).alias("total"))
    rejected.write.mode("errorifexists").option("header",True).csv(output+"/{rejected}")
    valid.write.mode("errorifexists").option("header",True).csv(output+"/{valid}")
    return
'''
    new_coordinator=f'''# REVIEWED SQL STAGE TRANSPORT: original SQL Server operations retained.
# Replaces Windows-only bulk-insert transport with JDBC transaction into SAME TABLE.
# The SCT-generated business dataflow is still invoked in its original order.
import {f['name']}
from sct_sql_server_stage import stage_customers

def {cfn[0].name}(connection:dict):
    stage_customers(connection)
    {f['name']}.{fn[0].name}(connection)
    return
'''
    f['source']=new_flow;c['source']=new_coordinator
    helper={'name':'sct_sql_server_stage','source':_STAGE_SCRIPT,'originalSource':'','originalPath':'generated/reviewed/sql-server-stage.py'}
    copied.append(helper)
    for m in copied:ast.parse(m['source'])
    original_sql_hash=hashlib.sha256(stage.encode()).hexdigest()
    return copied,[
        'REVIEWED SQL SERVER TRANSPORT: preserved CREATE/DELETE/insert/RTRIM on dbo.DemoForgeCustomers via a single JDBC transaction; replaced Windows-only BULK INSERT transport',
        'ACTUAL JDBC LOOKUP: SELECT CustomerID, CustomerName from dbo.DemoForgeCustomers, using approved Glue network connection and secret',
        'Repaired SCT invalid dataframe column syntax, right-key lookup routing and undefined reject branch',
        'Preserved Orders.csv and two valid/rejected output schemas, with explicit decimal(18,2) totals',
        'Original SCT staging script SHA256: '+original_sql_hash,
        'This reviewed adapter supports only the recognized SQL staging/lookup contract; original SSIS runtime parity NOT proven'
    ],['Customers.csv']
