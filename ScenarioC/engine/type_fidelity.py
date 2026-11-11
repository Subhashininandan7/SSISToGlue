"""Source-metadata based reviewable repairs for narrow SCT CSV type fidelity gaps.

Never generates business transformations or uses expected output fixtures. Fails closed
when SSIS source schema/expression cannot prove a correction. Offline static proof
only; SSIS/Glue execution parity must be established separately.
"""
from __future__ import annotations
import ast, hashlib, re
from pathlib import Path
from xml.etree import ElementTree as ET

class TypeFidelityError(ValueError): pass

def _local(n): return n.tag.rsplit('}', 1)[-1]
def _elements(n, kind): return [e for e in n.iter() if _local(e)==kind]
def _property(node, name):
    for p in _elements(node, 'property'):
        if p.get('name')==name: return p.text or ''
    return None

def source_types(dtsx):
    """Map Flat File Sources by their *actual* connection manager file name.

    Does not assume component names such as "Customers CSV".  Ambiguous
    connection names or duplicate CSV basenames fail closed.
    """
    root=ET.parse(dtsx).getroot()
    managers={}
    for node in _elements(root,'ConnectionManager'):
        # Top-level DTS ConnectionManager has a refId; child ObjectData
        # ConnectionManager holds the actual file path and format settings.
        ref=node.get('{www.microsoft.com/SqlServer/Dts}refId') or node.get('refId')
        kind=node.get('{www.microsoft.com/SqlServer/Dts}CreationName') or node.get('CreationName')
        if not ref or (kind or '').upper()!='FLATFILE':continue
        nested=[x for x in _elements(node,'ConnectionManager') if x is not node]
        vals=[x.get('{www.microsoft.com/SqlServer/Dts}ConnectionString') or x.get('ConnectionString') for x in nested]
        vals=[v for v in vals if v]
        if len(vals)!=1:raise TypeFidelityError('Ambiguous Flat File connection path')
        base=vals[0].replace('\\','/').rsplit('/',1)[-1].lower()
        if not base.endswith('.csv'):continue
        managers[ref]=base
    out={}
    for comp in _elements(root,'component'):
        if 'FlatFileSource' not in comp.get('componentClassID',''):
            continue
        refs=[x.get('connectionManagerRefId') or x.get('connectionManagerID') for x in _elements(comp,'connection')]
        bases=[managers[r] for r in refs if r in managers]
        if len(bases)!=1:continue
        base=bases[0]
        if base in out:raise TypeFidelityError('Two SSIS source components share CSV basename: '+base)
        outs=[x for x in _elements(comp,'output') if 'Error' not in x.get('name','')]
        if len(outs)!=1:continue
        fields={}
        for c in _elements(outs[0],'outputColumn'):
            key=c.get('name','').lower()
            if not key or key in fields:raise TypeFidelityError('Ambiguous Flat File source schema')
            fields[key]=c.get('dataType','').lower()
        if fields:out[base]=fields
    return out

def derived_casts(dtsx):
    root=ET.parse(dtsx).getroot();casts=[]
    for c in _elements(root,'outputColumn'):
        if c.get('dataType','').lower()!='numeric':continue
        prec=c.get('precision');scale=c.get('scale')
        expression=_property(c,'FriendlyExpression') or _property(c,'Expression') or ''
        pattern=r'\(DT_NUMERIC\s*,\s*(\d+)\s*,\s*(\d+)\s*\)\s*\(\s*([A-Za-z_]\w*)\s*\*\s*([A-Za-z_]\w*)\s*\)'
        match=re.fullmatch(pattern,expression.strip(),flags=re.I)
        if not match:continue
        a,b,left,right=match.groups()
        if (a,b)!=(prec,scale):raise TypeFidelityError('SSIS Derived Column metadata precision mismatch')
        if not (1<=int(prec)<=38 and 0<=int(scale)<=int(prec)):
            raise TypeFidelityError('Invalid source DECIMAL precision or scale')
        casts.append({'output':c.get('name','').lower(),'precision':int(prec),'scale':int(scale),
                      'left':left.lower(),'right':right.lower()})
    return casts

def plan(code,dtsx):
    """Return (patched, evidence). Only exact SCT reads/selects and source-proven derived casts."""
    sources=source_types(dtsx)
    numeric={'i4':'int','i8':'bigint','i2':'smallint','r8':'double','r4':'float'}
    changed=code.replace("\r\n", "\n");applied=[]
    # CSV source reads supplied by the original SCT-generated code.
    for base,fields in sources.items():
        regex=r'(?m)^(?P<indent>[ \t]*)(?P<var>[A-Za-z_]\w*)\s*=\s*spark\.read\.csv\([^\n]*?/'+re.escape(base)+r'["\'][^\n]*$'
        matches=list(re.finditer(regex,changed,flags=re.I))
        if not matches:continue
        if len(matches)!=1:raise TypeFidelityError('Ambiguous SCT CSV source '+base)
        match=matches[0];var=match.group('var');indent=match.group('indent')
        # Use stable source field names in Spark regardless of CSV header capitalization.
        normalize=(f'{indent}{var} = {var}.toDF(*[name.lower() for name in {var}.columns])\n')
        if normalize not in changed:
            # Check for same-name collisions before normalizing, even with unexpected headers.
            guard=(f'{indent}if len({{name.lower() for name in {var}.columns}}) != len({var}.columns):\n'
                   f'{indent}\traise ValueError("CSV header has case-insensitive duplicate columns")\n'
                   f'{indent}if not set({sorted(fields)!r}).issubset({{name.lower() for name in {var}.columns}}):\n'
                   f'{indent}\traise ValueError("CSV headers do not match original SSIS source metadata")\n')
            # Preserve source read statement bytes; add after it.
            end=match.end();changed=changed[:end]+'\n'+guard+normalize.rstrip('\n')+changed[end:]
            applied.append({'kind':'SOURCE_HEADER','source':base,'columns':sorted(fields)})
        # Restrict edits to the SELECT immediately following that source; no arbitrary SQL rewrites.
        select_re=re.compile(r'(?m)^'+re.escape(indent)+re.escape(var)+r'\s*=\s*'+re.escape(var)+r'\.select\([^\n]*\)$')
        sm=list(select_re.finditer(changed))
        if len(sm)!=1:raise TypeFidelityError('Cannot identify unique SCT source projection for '+base)
        original=sm[0].group();projected=original
        for field,kind in fields.items():
            if kind not in numeric:continue
            old=f'col("{field}").alias("{field}")'
            updated=f'col("{field}").cast("{numeric[kind]}").alias("{field}")'
            if old not in projected and updated not in projected:
                raise TypeFidelityError('Cannot prove SCT column for SSIS type: '+field)
            if old in projected:
                # SSIS's source output has FailComponent on conversion errors.
                # A silent Spark null from an invalid numeric string is not equivalent.
                validation=(f'{indent}if {var}.filter(col("{field}").isNotNull() & '
                            f'col("{field}").cast("{numeric[kind]}").isNull()).limit(1).count():\n'
                            f'{indent}\traise ValueError("Invalid numeric CSV field {field}; SSIS source rejects conversion errors")\n')
                at=sm[0].start()
                changed=changed[:at]+validation+changed[at:]
                # Recompute selection position after the inserted guard.
                sm=list(select_re.finditer(changed))
                projected=projected.replace(old,updated,1)
                applied.append({'kind':'NUMERIC_SOURCE','source':base,'column':field,'ssisType':kind,'sparkType':numeric[kind]})
        changed=changed[:sm[0].start()]+projected+changed[sm[0].end():]
    casts=derived_casts(dtsx)
    for spec in casts:
        # Replace only the exact SCT Spark SQL derived expression: no hand-authored calculation.
        bare=re.compile(r'(?i)CAST\s*\(\s*\(\s*`'+re.escape(spec['left'])+r'`\s*\*\s*`'+re.escape(spec['right'])+r'`\s*\)\s+AS\s+decimal\s*\)\s+AS\s+`'+re.escape(spec['output'])+r'`')
        replacements=list(bare.finditer(changed))
        if len(replacements)>1:raise TypeFidelityError('Ambiguous SCT decimal conversion')
        if not replacements:continue
        m=replacements[0]
        revised=f'CAST((`{spec["left"]}` * `{spec["right"]}`) AS DECIMAL({spec["precision"]},{spec["scale"]})) AS `{spec["output"]}`'
        changed=changed[:m.start()]+revised+changed[m.end():]
        applied.append({'kind':'DERIVED_DECIMAL','output':spec['output'],'precision':spec['precision'],'scale':spec['scale'],'operands':[spec['left'],spec['right']]})
    if not applied:return code,[]
    ast.parse(changed)
    return changed,applied

def sha(data): return hashlib.sha256(data.encode('utf-8')).hexdigest()
