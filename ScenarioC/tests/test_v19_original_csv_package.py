"""Check the actual SSIS input topology, never substitute a handcrafted Glue job."""
from pathlib import Path
from xml.etree import ElementTree as ET
import csv

ROOT=Path(__file__).resolve().parents[1]
PKG=ROOT/'ssis-packages'/'B_CSV_Customer_Order_Join.dtsx'
D='{www.microsoft.com/SqlServer/Dts}'

def parse():return ET.parse(PKG).getroot()

def test_real_ssis_component_inventory_and_no_sql_server():
    root=parse()
    assert root.attrib[D+'CreationName']=='Microsoft.Package'
    assert root.attrib[D+'ObjectName']=='B_CSV_Customer_Order_Join'
    cm=root.findall('.//'+D+'ConnectionManagers/'+D+'ConnectionManager')
    assert len(cm)==4
    assert all(c.attrib[D+'CreationName']=='FLATFILE' for c in cm)
    components=root.findall('.//component')
    types=[c.attrib['componentClassID'] for c in components]
    assert types.count('Microsoft.FlatFileSource')==2
    assert types.count('Microsoft.FlatFileDestination')==2
    for typ in ('Microsoft.MergeJoin','Microsoft.ConditionalSplit','Microsoft.DerivedColumn'):
        assert typ in types
    assert 'Microsoft.Lookup' not in types
    assert 'Microsoft.ExecuteSQLTask' not in [x.attrib.get(D+'CreationName') for x in root.findall('.//'+D+'Executable')]
    payload=PKG.read_text(encoding='utf-8')
    for token in ('DemoForge_SQL','BULK INSERT','DELETE FROM','specify connection','jdbc:sqlserver'):
        assert token not in payload

def test_all_dataflow_paths_resolve():
    root=parse()
    ids={x.attrib['refId'] for x in root.iter() if 'refId' in x.attrib}
    paths=root.findall('.//path')
    assert len(paths)==7
    assert all(p.attrib['startId'] in ids and p.attrib['endId'] in ids for p in paths)
    assert len({p.attrib['startId'] for p in paths})>=5
    assert not any('Customer Lookup' in p.attrib['startId']+p.attrib['endId'] for p in paths)

def test_flat_file_sources_and_csv_fixtures():
    root=parse()
    sources={x.attrib['name']:x for x in root.findall('.//component') if x.attrib['componentClassID']=='Microsoft.FlatFileSource'}
    assert set(sources)=={'Orders CSV','Customers CSV'}
    for name, file_name in (('Orders CSV','Orders.csv'),('Customers CSV','Customers.csv')):
        path=ROOT/'fixtures'/'input'/file_name
        assert path.is_file()
        rows=list(csv.DictReader(path.open(newline='')))
        assert rows and [r['CustomerID'] for r in rows]==sorted(r['CustomerID'] for r in rows)
        src=sources[name]
        columns=[c.attrib['name'] for c in src.findall('./outputs/output[@name="Flat File Source Output"]/outputColumns/outputColumn')]
        assert 'CustomerID' in columns
        key=next(x for x in src.findall('.//outputColumn') if x.attrib['name']=='CustomerID')
        assert any(p.attrib.get('name')=='SortKeyPosition' and p.text=='1' for p in key.findall('./properties/property'))

def test_expected_output_is_independent_and_original_destinations_isolated():
    root=parse()
    strings=[e.attrib[D+'ConnectionString'] for e in root.iter() if D+'ConnectionString' in e.attrib]
    assert any(s.endswith(r'input\Orders.csv') for s in strings)
    assert any(s.endswith(r'input\Customers.csv') for s in strings)
    assert any(s.endswith(r'ssis-output\ValidOrders_SSIS.csv') for s in strings)
    assert any(s.endswith(r'ssis-output\RejectedOrders_SSIS.csv') for s in strings)
    assert not any('fixtures\\expected\\' in s for s in strings)
    customers={r['CustomerID']:r['CustomerName'] for r in csv.DictReader((ROOT/'fixtures/input/Customers.csv').open())}
    orders=list(csv.DictReader((ROOT/'fixtures/input/Orders.csv').open()))
    valid=[r for r in orders if r['CustomerID'] in customers]
    rejected=[r for r in orders if r['CustomerID'] not in customers]
    assert len(valid)==3 and len(rejected)==2
    assert {r['OrderID'] for r in valid}=={'O10','O11','O13'}
    assert {r['OrderID'] for r in rejected}=={'O12','O14'}

def test_no_generated_glue_substitution_in_source_package():
    root=parse()
    assert len(root.findall('.//component'))==8
    assert any(c.attrib.get('componentClassID')=='Microsoft.MergeJoin' for c in root.findall('.//component'))
    assert not (ROOT/'glue'/'B_CSV_Customer_Order_Join.py').exists()
