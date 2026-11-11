"""Actual-result row-level parity: ignores order, preserves duplicate multiplicity."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from scenarios import SCENARIOS,read_csv

NUMERIC={'Salary','Bonus','UnitPrice','Total'}

def canon(k,value):
    if k in NUMERIC:
        try:return str(Decimal(value).quantize(Decimal('.01')))
        except (InvalidOperation,TypeError):return '!BADNUM:'+str(value)
    if k=='Quantity':
        try:return str(int(value))
        except (ValueError,TypeError):return '!BADINT:'+str(value)
    return str(value)

def compare(expected,actual):
    if not expected and not actual:return {'match':True,'expected':0,'actual':0,'missing':[],'extra':[]}
    keys=list(expected[0].keys()) if expected else list(actual[0].keys())
    if any(set(r)!=set(keys) for r in expected+actual):
        return {'match':False,'reason':'SCHEMA_MISMATCH','expected':len(expected),'actual':len(actual)}
    def record(row):return tuple(canon(k,row.get(k)) for k in keys)
    a=Counter(map(record,expected));b=Counter(map(record,actual));missing=list((a-b).elements());extra=list((b-a).elements())
    return {'match':not missing and not extra,'expected':len(expected),'actual':len(actual),
            'columns':keys,'missing':[list(x) for x in missing[:10]],'extra':[list(x) for x in extra[:10]]}

def compare_scenario(fixtures,scenario,actual_by_output):
    results={}
    for name in SCENARIOS[scenario]['outputs']:
        expected=read_csv(Path(fixtures)/'expected'/name)
        results[name]=compare(expected,actual_by_output[name])
    return {'scenario':scenario,'verified':all(x['match'] for x in results.values()),
            'outputs':results,'verification':'ROW_LEVEL_ACTUAL_OUTPUT_COMPARISON'}
