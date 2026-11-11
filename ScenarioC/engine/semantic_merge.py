"""SSIS-provenance based recovery gate for an unsupported SCT Merge Join.

This module NEVER synthesizes execution code for deployment. It produces a
bounded reference contract from the original DTSX and validates a proposed
Bedrock insertion against that contract. A proposal changing any preexisting
SCT statement is rejected. Unsupported patterns remain blocked.
"""
from __future__ import annotations
import ast, re
from pathlib import Path
from xml.etree import ElementTree as ET

class SemanticBlocked(ValueError): pass

MARKER=re.compile(r'(?i)(25042|AWS Glue doesn.t support|perform a manual conversion)')

def unsupported(code):
    return bool(MARKER.search(code))

def unresolved_frames(code):
    try: tree=ast.parse(code)
    except SyntaxError: return []
    assigned={n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)}
    receivers=set()
    for n in ast.walk(tree):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('createOrReplaceTempView','select','join','filter','where'):
            if isinstance(n.func.value,ast.Name):receivers.add(n.func.value.id)
    return sorted(receivers-assigned-{'spark','col'})

def _local(tag):return tag.rsplit('}',1)[-1]
def _children(n,name):return [x for x in n if _local(x.tag)==name]
def _desc(n,name):return [x for x in n.iter() if _local(x.tag)==name]
def _prop(node,name):
    for x in _desc(node,'property'):
        if x.get('name')==name:return (x.text or '').strip()
    return None

def metadata(path):
    p=Path(path)
    if not p.is_file():raise SemanticBlocked('Original DTSX source missing')
    tree=ET.parse(p); root=tree.getroot()
    components=[x for x in root.iter() if _local(x.tag)=='component']
    merges=[c for c in components if 'MergeJoin' in str(c.get('componentClassID','')) or '14D43A4F-D7BD-489D-829E-6DE35750CFE4' in str(c.get('componentClassID','')).upper()]
    if len(merges)!=1:raise SemanticBlocked('Only one explicitly identifiable original SSIS Merge Join is supported')
    merge=merges[0]
    join_type=_prop(merge,'JoinType')
    # SSIS Merge Join: 0 full, 1 left, 2 inner (only left is approved here).
    if join_type!='1':raise SemanticBlocked('Only original left outer join (JoinType=1) supported; refusing to infer join type')
    count=_prop(merge,'NumKeyColumns')
    if count!='1':raise SemanticBlocked('Only one original Merge Join key supported')
    ins=_desc(merge,'input')
    if len(ins)!=2:raise SemanticBlocked('Merge Join does not have exactly two SSIS inputs')
    lineages=[];by_input=[]
    for i in ins:
        cols=_desc(i,'inputColumn');by_input.append(cols)
        matches=[c for c in cols if (c.get('cachedSortKeyPosition') or _prop(c,'SortKeyPosition'))=='1']
        if len(matches)!=1:raise SemanticBlocked('Cannot establish the single sorted join key on both original inputs')
        lineages.append(matches[0].get('lineageId'))
    if not all(lineages):raise SemanticBlocked('Missing original join key lineage')
    output_nodes=_desc(merge,'output')
    named=[o for o in output_nodes if o.get('name')=='Merge Join Output']
    if len(named)!=1:raise SemanticBlocked('Missing unique SSIS Merge Join output')
    outputs=[]
    for c in _desc(named[0],'outputColumn'):
        ref=_prop(c,'InputColumnID')
        if not ref or not ref.startswith('#{') or not ref.endswith('}'):
            raise SemanticBlocked('Merge Join output missing explicit original InputColumnID lineage')
        ref=ref[2:-1]
        match=[side for side,cols in enumerate(by_input) if any(x.get('refId')==ref for x in cols)]
        if len(match)!=1:raise SemanticBlocked('Merge Join output source lineage cannot be resolved: '+str(c.get('name')))
        source=next(x for x in by_input[match[0]] if x.get('refId')==ref)
        outputs.append({'name':c.get('name'),'source':source.get('refId','').split('Columns[')[-1].rstrip(']'),'side':match[0]})
    if not outputs or len({x['name'].lower() for x in outputs})!=len(outputs):raise SemanticBlocked('Ambiguous original output mappings')
    # Key names are the last Columns[...] segment in SSIS lineage paths.
    keys=[ref.split('Columns[')[-1].rstrip(']') for ref in lineages]
    sources=[]
    for lineage in lineages:
        part=lineage.split('.Outputs[')[0]
        source=next((c for c in components if c.get('refId')==part),None)
        if source is None:raise SemanticBlocked('Original join source does not resolve to a component')
        sources.append({'component':source.get('name'),'refId':part})
    return {'mergeName':merge.get('name'),'joinType':'left','keys':keys,'sources':sources,'outputs':outputs,
            'originalPathSha256':__import__('hashlib').sha256(p.read_bytes()).hexdigest()}

def describe_runtime_contract(code,contract):
    # Bind original SSIS left/right sources to their *actual SCT variable assignments*
    # using source component names. Fail closed on any mismatch.
    tree=ast.parse(code)
    reads={}
    source_reads={n.targets[0].id for n in ast.walk(tree) if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and 'spark.read.csv(' in ast.unparse(n.value)}
    for n in ast.walk(tree):
        if not isinstance(n,ast.Assign) or len(n.targets)!=1 or not isinstance(n.targets[0],ast.Name):continue
        try:src=ast.unparse(n.value)
        except Exception:continue
        if '.select(' not in src or '.alias(' not in src:continue
        if n.targets[0].id in source_reads:reads[n.targets[0].id]=src
    bindings=[]
    for source in contract['sources']:
        label=source['component'].lower().replace(' ','_')
        # Actual SCT uses x0020 for spaces; detect by normalized words.
        tokens=[x for x in re.split(r'\W+',source['component'].lower()) if x not in ('csv','input','source')]
        options=[name for name in reads if all(t in name.lower() for t in tokens)]
        if len(options)!=1:raise SemanticBlocked('Cannot unambiguously bind SCT source for '+source['component'])
        bindings.append(options[0])
    if bindings[0]==bindings[1]:raise SemanticBlocked('Both SSIS join sources bound to the same SCT DataFrame')
    unresolved=unresolved_frames(code)
    if len(unresolved)!=1:raise SemanticBlocked('Expected exactly one undefined SCT DataFrame to restore, found '+str(unresolved))
    return dict(contract,frames=bindings,frame=unresolved[0])

def canonical_assignment(contract,frame=None):
    frame=frame or contract.get('frame','csv_customer_merge_join')
    if not re.fullmatch(r'[A-Za-z_]\w*',frame):raise SemanticBlocked('Unsafe join output identifier')
    a,b=contract['frames'];keys=contract['keys']
    if any(not re.fullmatch(r'[A-Za-z_]\w*',k) for k in keys):raise SemanticBlocked('Unsupported source key names')
    selections=[]
    for o in contract['outputs']:
        side='ss_left' if o['side']==0 else 'ss_right'
        # SCT normalized SSIS column output names to lowercase in the read.select calls.
        col=o['source'].lower();out=o['name'].lower()
        if not re.fullmatch(r'[A-Za-z_]\w*',col) or not re.fullmatch(r'[A-Za-z_]\w*',out):raise SemanticBlocked('Unsupported original output name')
        selections.append(f'col("{side}.{col}").alias("{out}")')
    return (f'{frame} = {a}.alias("ss_left").join({b}.alias("ss_right"), '
            f'col("ss_left.{keys[0].lower()}") == col("ss_right.{keys[1].lower()}"), "left").select('
            +', '.join(selections)+')')

def validate_proposal(original,proposed,contract):
    """Proof of tight edit scope, exact SSIS join semantics, and no unrelated edits."""
    old=ast.parse(original);new=ast.parse(proposed)
    frame=contract.get('frame','csv_customer_merge_join')
    expected=ast.parse(canonical_assignment(contract,frame)).body[0]
    def equivalent(a,b):return ast.dump(a,include_attributes=False)==ast.dump(b,include_attributes=False)
    # Exact single new assignment, all old statements preserved in order.
    def remove_one(body):
        candidates=[(i,n) for i,n in enumerate(body) if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id==frame]
        if len(candidates)!=1:raise SemanticBlocked('AI must create exactly one missing named Merge Join assignment')
        i,n=candidates[0]
        if not equivalent(n,expected):raise SemanticBlocked('AI Merge Join does not exactly preserve the original keys, type and output lineage')
        return body[:i]+body[i+1:]
    # Insert within the original data-flow function, immediately before first use.
    oldf=[n for n in old.body if isinstance(n,ast.FunctionDef)]
    newf=[n for n in new.body if isinstance(n,ast.FunctionDef)]
    if len(oldf)!=1 or len(newf)!=1 or oldf[0].name!=newf[0].name:raise SemanticBlocked('AI changed SCT module function structure')
    stripped=remove_one(newf[0].body)
    if len(stripped)!=len(oldf[0].body) or any(not equivalent(x,y) for x,y in zip(stripped,oldf[0].body)):
        raise SemanticBlocked('AI changed SCT statements beyond the missing Merge Join assignment')
    first_use=next((i for i,n in enumerate(newf[0].body) if any(isinstance(t,ast.Name) and t.id==frame and isinstance(t.ctx,ast.Load) for t in ast.walk(n))),None)
    insert=next(i for i,n in enumerate(newf[0].body) if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id==frame)
    if first_use is None or insert>=first_use:raise SemanticBlocked('AI Merge Join assignment must precede all usages')
    if len(old.body)!=len(new.body):raise SemanticBlocked('AI modified top-level SCT code')
    if not equivalent(ast.Module(body=[x for x in old.body if x is not oldf[0]],type_ignores=[]),
                      ast.Module(body=[x for x in new.body if x is not newf[0]],type_ignores=[])):
        raise SemanticBlocked('AI changed imports or module initialization')
    return {'joinType':contract['joinType'],'keys':contract['keys'],'outputColumns':[x['name'] for x in contract['outputs']],
            'originalPathSha256':contract['originalPathSha256'],'validatedAssignment':canonical_assignment(contract)}


def insert_scoped_assignment(original: str, assignment: str, contract: dict) -> tuple[str, dict]:
    """Insert exactly one model-supplied assignment; preserve every existing byte.

    The Bedrock text is NEVER used as a complete module. Source provenance and
    AST structure are verified both before and after the insertion.
    """
    if not isinstance(assignment, str) or len(assignment) > 2500:
        raise SemanticBlocked('Expected one bounded Merge Join assignment')
    if '\n' in assignment.strip() or '\r' in assignment.strip() or '\t' in assignment.strip():
        raise SemanticBlocked('Bedrock must return a single-line assignment only')
    if '#' in assignment:
        raise SemanticBlocked('Comments are not allowed in the single-line assignment')
    try:
        parsed = ast.parse(assignment.strip())
        expected = ast.parse(canonical_assignment(contract))
    except SyntaxError as exc:
        raise SemanticBlocked('Merge Join assignment contains invalid Python') from exc
    if len(parsed.body) != 1 or ast.dump(parsed, include_attributes=False) != ast.dump(expected, include_attributes=False):
        raise SemanticBlocked('Bedrock assignment does not preserve SSIS join type, keys or five output lineages')
    frame = contract['frame']
    tree = ast.parse(original)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    if len(functions) != 1:
        raise SemanticBlocked('Expected one SCT data flow function')
    fun = functions[0]
    usages = [n for n in fun.body if any(isinstance(t, ast.Name) and t.id == frame and isinstance(t.ctx, ast.Load)
                                          for t in ast.walk(n))]
    if not usages:
        raise SemanticBlocked('Missing SCT join receiver use')
    use = min(usages, key=lambda n: n.lineno)
    # Require actual source DataFrame assignments precede insertion (not just their names).
    assignments = {t.id: n.lineno for n in fun.body if isinstance(n, ast.Assign)
                   for t in n.targets if isinstance(t, ast.Name)}
    if any(n not in assignments or assignments[n] >= use.lineno for n in contract['frames']):
        raise SemanticBlocked('Source DataFrame assignments do not precede join insertion')
    lines = original.splitlines(keepends=True)
    prefix = re.match(r'^[ \t]*', lines[use.lineno - 1]).group()
    if not prefix or not lines[use.lineno - 1].lstrip().startswith(frame + '.'):
        raise SemanticBlocked('Cannot safely locate first Merge Join use')
    newline = '\r\n' if '\r\n' in original else '\n'
    insertion = prefix + assignment.strip() + newline
    new = ''.join(lines[:use.lineno - 1]) + insertion + ''.join(lines[use.lineno - 1:])
    proof = validate_proposal(original, new, contract)
    if new.replace(insertion, '', 1) != original:
        raise SemanticBlocked('SCT original statements were not preserved byte-for-byte')
    if unresolved_frames(new):
        raise SemanticBlocked('Undefined DataFrame remains after proposed insertion')
    if len([x for x in ast.walk(ast.parse(new)) if isinstance(x, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == frame for t in x.targets)]) != 1:
        raise SemanticBlocked('Join DataFrame is not uniquely defined')
    return new, proof
