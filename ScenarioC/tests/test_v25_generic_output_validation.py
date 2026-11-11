"""Offline tests of read-only real-S3 contract, no fake success in product."""
from io import BytesIO
import pytest
from output_validation import validate_s3_csv_outputs, OutputValidationError

PREFIX='s3://example-bucket/migration-run/generic-sct/output'
class _Pages:
    def __init__(self, keys):self.keys=keys
    def paginate(self, Bucket, Prefix):
        assert Bucket=='example-bucket'
        return [{'Contents':[{'Key':k,'Size':len(v)} for k,v in self.keys.items() if k.startswith(Prefix)]}]
class FakeS3:
    def __init__(self, keys):self.keys=keys
    def get_paginator(self, name):assert name=='list_objects_v2';return _Pages(self.keys)
    def get_object(self, Bucket, Key):assert Bucket=='example-bucket';return {'Body':BytesIO(self.keys[Key])}

def sample(files):
    return FakeS3({f'migration-run/generic-sct/output/ValidOrders.csv/{k}':v for k,v in files.items()})

def test_actual_s3_parts_vs_trusted_baseline_without_row_order():
    s3=sample({'part-00000.csv':b'orderid,total\nO11,150.00\n',
               'part-00001.csv':b'orderid,total\nO10,251.0\n'})
    res=validate_s3_csv_outputs(s3,PREFIX,'ValidOrders.csv',b'Total,OrderID\n251.00,O10\n150,O11\n')
    assert res['status']=='MATCH' and res['verified'] and res['actualRows']==2
    assert res['filesRead']==2 and res['source']=='REAL_AWS_S3'

def test_duplicate_rows_matter():
    s3=sample({'part-1.csv':b'orderid,total\nO10,1\nO10,1\n'})
    r=validate_s3_csv_outputs(s3,PREFIX,'ValidOrders.csv',b'orderid,total\nO10,1\n')
    assert not r['verified'] and r['unexpectedRows']==1

def test_schema_mismatch_fails():
    s3=sample({'part-1.csv':b'orderid,qty\nO10,1\n'})
    r=validate_s3_csv_outputs(s3,PREFIX,'ValidOrders.csv',b'orderid,total\nO10,1\n')
    assert r['status']=='SCHEMA_MISMATCH'

def test_invalid_source_prefix_and_missing_file_fail_closed():
    with pytest.raises(OutputValidationError):
        validate_s3_csv_outputs(sample({}),PREFIX,'../fake.csv',b'a\n1\n')
    with pytest.raises(OutputValidationError,match='No actual'):
        validate_s3_csv_outputs(sample({}),PREFIX,'ValidOrders.csv',b'a\n1\n')

def test_inconsistent_part_schema_blocks():
    s3=sample({'part-1.csv':b'orderid,total\nO10,1\n',
               'part-2.csv':b'orderid,value\nO11,2\n'})
    with pytest.raises(OutputValidationError,match='inconsistent schemas'):
        validate_s3_csv_outputs(s3,PREFIX,'ValidOrders.csv',b'orderid,total\nO10,1\n')
