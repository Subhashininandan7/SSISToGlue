"""Deterministic, auditable CSV reference semantics for the three demonstration cases.
These are expected-result oracles, NOT purported AWS SCT conversions.
"""
from __future__ import annotations
import csv
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

SCENARIOS = {
    'A': {'name':'Active employees & 10% bonus', 'inputs':['Employees.csv'], 'outputs':['ActiveEmployees.csv']},
    'B': {'name':'Customer lookup and order rejection', 'inputs':['Customers.csv','Orders.csv'], 'outputs':['ValidOrders.csv','RejectedOrders.csv']},
    'C': {'name':'Customer Type 2 history', 'inputs':['DimCustomer.csv','CustomerChanges.csv'], 'outputs':['DimCustomerHistory.csv']},
}

SEED = {
 'Employees.csv': (['EmployeeID','EmployeeName','Department','Salary','Status'], [
     [101,'Asha','IT','50000.00','Active'],[102,'Ben','HR','60000.00','Inactive'],
     [103,'Chitra','Sales','65000.00','Active'],[104,'Dev','IT','70500.00','Active'],
     [105,'Esha','Finance','80000.00','Inactive']]),
 'Customers.csv': (['CustomerID','CustomerName'], [['C01','Anika'],['C02','Bruno'],['C03','Chen']]),
 'Orders.csv': (['OrderID','CustomerID','Quantity','UnitPrice'], [
     ['O10','C01','2','125.50'],['O11','C02','3','50.00'],['O12','C99','1','99.99'],
     ['O13','C03','4','20.25'],['O14','C77','2','30.00']]),
 'DimCustomer.csv': (['CustomerID','CustomerName','City','EffectiveFrom','EffectiveTo','IsCurrent'], [
     ['C01','Anika','Chennai','2025-01-01','9999-12-31','1'],
     ['C02','Bruno','Pune','2025-01-01','9999-12-31','1'],
     ['C03','Chen','Mumbai','2025-01-01','9999-12-31','1']]),
 'CustomerChanges.csv': (['CustomerID','CustomerName','City'], [
     ['C01','Anika','Bengaluru'],['C02','Bruno','Pune'],['C04','Diya','Hyderabad']]),
}

def write_csv(path:Path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as f:
        writer=csv.writer(f,lineterminator='\n');writer.writerow(header);writer.writerows(rows)

def read_csv(path:Path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def as_money(x):
    return str(Decimal(str(x)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

def output_a(inp:Path,out:Path):
    rows=read_csv(inp)
    if len({r['EmployeeID'] for r in rows})!=len(rows):raise ValueError('Duplicate employee IDs')
    data=[[r['EmployeeID'],r['EmployeeName'],r['Department'],as_money(r['Salary']),as_money(Decimal(r['Salary'])*Decimal('.10'))]
          for r in rows if r['Status'].casefold()=='active']
    write_csv(out,['EmployeeID','EmployeeName','Department','Salary','Bonus'],data)
    return {'input':len(rows),'output':len(data)}

def output_b(customers:Path,orders:Path,valid:Path,rejected:Path):
    c=read_csv(customers);o=read_csv(orders)
    if len({x['CustomerID'] for x in c})!=len(c):raise ValueError('Duplicate customer lookup keys')
    if len({x['OrderID'] for x in o})!=len(o):raise ValueError('Duplicate order IDs')
    lookup={x['CustomerID']:x['CustomerName'] for x in c}
    good=[];bad=[]
    for r in o:
        total=as_money(Decimal(r['Quantity'])*Decimal(r['UnitPrice']))
        if r['CustomerID'] in lookup:
            good.append([r['OrderID'],r['CustomerID'],lookup[r['CustomerID']],r['Quantity'],as_money(r['UnitPrice']),total])
        else:bad.append([r['OrderID'],r['CustomerID'],'CUSTOMER_NOT_FOUND'])
    write_csv(valid,['OrderID','CustomerID','CustomerName','Quantity','UnitPrice','Total'],good)
    write_csv(rejected,['OrderID','CustomerID','Reason'],bad)
    return {'orders':len(o),'valid':len(good),'rejected':len(bad)}

def output_c(dim:Path,changes:Path,out:Path,as_of='2026-11-08'):
    today=date.fromisoformat(as_of)
    existing=read_csv(dim);change_rows=read_csv(changes)
    keys=[c['CustomerID'] for c in change_rows]
    if len(set(keys))!=len(keys):raise ValueError('Duplicate customer IDs in change file')
    active={}
    for row in existing:
        if row['IsCurrent'] not in ('0','1'):raise ValueError('IsCurrent must be 0 or 1')
        if row['IsCurrent']=='1':
            k=row['CustomerID']
            if k in active: raise ValueError('Multiple current customer rows')
            active[k]=row
    history=list(existing)
    expired=inserted=0
    for r in change_rows:
        current=active.get(r['CustomerID'])
        if current and (current['CustomerName'],current['City'])==(r['CustomerName'],r['City']):continue
        if current:
            if today<=date.fromisoformat(current['EffectiveFrom']):
                raise ValueError('SCD2 effective date not later than existing version')
            current['EffectiveTo']=as_of;current['IsCurrent']='0';expired+=1
        newrow={'CustomerID':r['CustomerID'],'CustomerName':r['CustomerName'],'City':r['City'],
                'EffectiveFrom':as_of,'EffectiveTo':'9999-12-31','IsCurrent':'1'}
        history.append(newrow);active[r['CustomerID']]=newrow;inserted+=1
    history.sort(key=lambda x:(x['CustomerID'],x['EffectiveFrom']))
    write_csv(out,['CustomerID','CustomerName','City','EffectiveFrom','EffectiveTo','IsCurrent'],
              [[r[c] for c in ['CustomerID','CustomerName','City','EffectiveFrom','EffectiveTo','IsCurrent']] for r in history])
    return {'initial':len(existing),'expired':expired,'inserted':inserted,'historyRows':len(history)}

def make_fixtures(destination:Path):
    data=destination/'input';expected=destination/'expected';data.mkdir(parents=True,exist_ok=True);expected.mkdir(parents=True,exist_ok=True)
    for name,(cols,rows) in SEED.items():write_csv(data/name,cols,rows)
    stats={'A':output_a(data/'Employees.csv',expected/'ActiveEmployees.csv'),
           'B':output_b(data/'Customers.csv',data/'Orders.csv',expected/'ValidOrders.csv',expected/'RejectedOrders.csv'),
           'C':output_c(data/'DimCustomer.csv',data/'CustomerChanges.csv',expected/'DimCustomerHistory.csv')}
    return stats
