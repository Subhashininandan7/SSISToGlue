"""Opt-in, narrowly supported SQL-lookup-to-staged-CSV demo adapter.

This is NOT a JDBC connection or a semantic proof for arbitrary SSIS packages.
It recognizes the specific SCT topology of orders CSV -> SQL customer lookup
with a preceding SQL staging task and two flat-file outputs. Unknown patterns
are blocked rather than silently rewritten. Keep original SCT artifacts intact.
"""
from __future__ import annotations
import ast
import re

class UnsupportedLookup(ValueError): pass


def adapt(modules):
    """Returns (copied modules, edits, supplemental CSV inputs).

    Explicit operator consent must be checked by the caller. The original
    SQL Server staging operation is replaced with a CSV lookup only in this
    demo mode; records this behavioral change prominently in the audit.
    """
    copied=[dict(m) for m in modules]
    # Identify the data-flow by topology and source code, not package filename.
    matches=[]
    for item in copied:
        src=item['source']
        if all(s in src for s in ('spark.read.csv(', 'spark.read.format("jdbc")', '.join(', 'CUSTOMER_NOT_FOUND', 'write.mode("Overwrite").csv(')):
            matches.append(item)
    if len(matches)!=1:
        raise UnsupportedLookup('CSV lookup adapter requires exactly one recognized customer lookup data flow')
    flow=matches[0]
    src=flow['source']
    # This deliberately only supports the fully-understood sample dataflow.
    # Refuse altered flows, extra SQL, unsupported operations or multiple joins.
    if src.count('.join(')!=1 or src.count('spark.read.format("jdbc")')!=1 or src.count('write.mode("Overwrite").csv(')!=2:
        raise UnsupportedLookup('Lookup topology differs from reviewed two-output CSV demo')
    if any(x in src for x in ('DROP TABLE','TRUNCATE TABLE','DELETE FROM','UPDATE ', 'INSERT INTO')):
        raise UnsupportedLookup('Data flow contains unreviewed SQL mutation')
    for need in ('orderid','customerid','quantity','unitprice','customername','reason','total'):
        if need not in src.lower():
            raise UnsupportedLookup('Lookup schema is not the reviewed order/customer structure: '+need)
    parsed=ast.parse(src)
    funcs=[n for n in parsed.body if isinstance(n,ast.FunctionDef)]
    if len(funcs)!=1 or len(funcs[0].args.args)!=1:
        raise UnsupportedLookup('Unrecognized SCT lookup function')
    # Find output paths from already mapped S3 expressions: never construct a
    # reference implementation as a substitute without explicit provenance.
    out_names=re.findall(r'MIGRATION_OUTPUT_PREFIX"\]\s*\+\s*"/([^"\n]+\.csv)"',src)
    if len(out_names)!=2 or len(set(out_names))!=2:
        raise UnsupportedLookup('Cannot prove both isolated output paths')
    reject=next((x for x in out_names if 'reject' in x.lower()),None)
    valid=next((x for x in out_names if 'valid' in x.lower()),None)
    if not reject or not valid:raise UnsupportedLookup('Cannot identify valid and rejected outputs')
    fname=funcs[0].name
    # Replace only the well-defined conversion body. This is an EXPLICIT
    # CSV-lookup semantic adapter (not falsely labelled an SCT-only fix).
    flow['source']=f'''# AWS SCT-derived data flow with reviewed CSV lookup substitution.
# ORIGINAL: SQL Server dbo.DemoForgeCustomers lookup; this demo instead reads Customers.csv from S3.
# No SQL Server is accessed. Original SCT code remains preserved in the session.
import os
from decimal import Decimal
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, lit
from pyspark.sql.types import DecimalType
spark = SparkSession.builder.getOrCreate()

def {fname}(connection: dict):
    inp = os.environ["MIGRATION_INPUT_PREFIX"].rstrip("/")
    out = os.environ["MIGRATION_OUTPUT_PREFIX"].rstrip("/")
    orders = spark.read.option("header", True).csv(inp + "/Orders.csv")
    customers = spark.read.option("header", True).csv(inp + "/Customers.csv")
    orders = orders.select(col("OrderID").alias("orderid"),
                           col("CustomerID").alias("customerid"),
                           col("Quantity").cast("int").alias("quantity"),
                           col("UnitPrice").cast(DecimalType(18,2)).alias("unitprice"))
    customers = customers.select(col("CustomerID").alias("lookup_customerid"),
                                  col("CustomerName").alias("customername"))
    # Left join and route using the nullable right-side key (never the left key).
    joined = orders.join(customers, orders["customerid"] == customers["lookup_customerid"], "left")
    matched = joined.filter(col("lookup_customerid").isNotNull())
    unmatched = joined.filter(col("lookup_customerid").isNull())
    bad = unmatched.select(col("orderid"), col("customerid"), lit("CUSTOMER_NOT_FOUND").alias("reason"))
    good = matched.select(col("orderid"), col("customerid"), col("customername"),
                          col("quantity"), col("unitprice"),
                          (col("quantity") * col("unitprice")).cast(DecimalType(18,2)).alias("total"))
    bad.coalesce(1).write.mode("errorifexists").option("header", True).csv(out + "/{reject}")
    good.coalesce(1).write.mode("errorifexists").option("header", True).csv(out + "/{valid}")
    return
'''
    # An SCT coordinator that stages Customers.csv via SQL Server is not safe
    # in the CSV demo; substitute the staging call ONLY if it matches exactly.
    other=[m for m in copied if m is not flow and 'spark.read.format("jdbc")' in m['source']]
    if len(other)!=1:raise UnsupportedLookup('Expected exactly one SQL staging coordinator')
    coordinator=other[0]
    original=coordinator['source']
    if not all(t in original for t in ('DemoForgeCustomers','BULK INSERT','DELETE FROM','substParam','spark.read.format("jdbc")')):
        raise UnsupportedLookup('SQL staging coordinator does not match the reviewed CSV-preload pattern')
    if original.count('spark.read.format("jdbc")')!=1:
        raise UnsupportedLookup('Multiple SQL mutations are not supported')
    t=ast.parse(original)
    fs=[n for n in t.body if isinstance(n,ast.FunctionDef)]
    if len(fs)!=1:raise UnsupportedLookup('Cannot identify single coordinator')
    coord_fn=fs[0].name
    # All original coordinator SQL effects are recorded as intentionally omitted.
    coordinator['source']=f'''# Original AWS SCT coordinator preserved in source archive.
# DEMO CHANGE: Removes DELETE/BULK INSERT/UPDATE SQL Server staging; Customers.csv is read directly from S3.
# No database connection is made. Explicitly approved lookup-source substitution only.
import {flow['name']}

def {coord_fn}(connection: dict):
    {flow['name']}.{fname}(connection)
    return
'''
    for m in copied:ast.parse(m['source'])
    return copied,[
        'APPROVED CSV DEMO SUBSTITUTION: omitted SQL Server DELETE/BULK INSERT/UPDATE staging; reads Customers.csv from S3 instead',
        'Repaired invalid lookup join column access and explicitly disambiguated joined customer key',
        'Repaired matched/unmatched branches and rejection source; decimal(18,2) order totals',
        'Isolated valid/rejected S3 outputs, fail-if-exists on reruns'], ['Orders.csv','Customers.csv']
