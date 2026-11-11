import hashlib
import json
import zipfile
from pathlib import Path

import pytest
from quickflow import Blocked, construct


def test_sct_empty_imported_body_is_not_a_valid_conversion(tmp_path):
    base=tmp_path/'sct'
    original=base/'original'
    original.mkdir(parents=True)
    manifest=[]
    with zipfile.ZipFile(base/'original-conversion-output.zip','w') as z:
        for i,(path,code) in enumerate([
            ('0. create-body-script/0. pkg.pkg.py',b'import transform\ndef pkg(connection):\n    transform.transform(connection)\n'),
            ('0. create-body-script/1. pkg.transform.py',b''),
        ]):
            z.writestr(path,code)
            if code:
                filename=f'sct_{i:03d}.py'
                (original/filename).write_bytes(code)
                manifest.append({'file':filename,'originalPath':path,'sha256':hashlib.sha256(code).hexdigest()})
    (base/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(Blocked,match='empty generated data-flow module'):
        construct(tmp_path)
