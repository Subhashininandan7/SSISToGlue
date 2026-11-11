"""Safe, bounded deterministic SCT candidate repair and evidence collection."""
import ast
import hashlib
import json
from pathlib import Path
import sys

# Reused verbatim from the earlier Migration Studio source, preserving proven token safeguards.
try:
    from sct_generic_syntax_fixes import repair_candidate
except ImportError:
    from .sct_generic_syntax_fixes import repair_candidate

DANGER=('specify driver','specify connection','openrowset','sqlncli','drop table','truncate table')

def classify(text):
    issues=[]
    low=text.casefold()
    for term in DANGER:
        if term in low:issues.append('BLOCK_'+term.upper().replace(' ','_'))
    if 'spark.read.format("jdbc")' in low or "spark.read.format('jdbc')" in low:
        if 'update ' in low or 'delete ' in low or 'insert into ' in low:
            issues.append('JDBC_READ_SQL_MUTATION_REVIEW')
    try:ast.parse(text)
    except SyntaxError as e:issues.append('PYTHON_SYNTAX_ERROR_LINE_'+str(e.lineno))
    return list(dict.fromkeys(issues))

def repair_text(text):
    result=repair_candidate(text)
    issues=classify(result['candidate'])
    return {'code':result['candidate'],'edits':result['edits'],'syntaxPass':result['syntaxPass'],
            'blockers':issues,'deployApproved':False,
            'candidateSha256':hashlib.sha256(result['candidate'].encode()).hexdigest(),
            'originalSha256':hashlib.sha256(text.encode()).hexdigest()}

def report_folder(source_dir:Path,target_dir:Path):
    target_dir.mkdir(parents=True,exist_ok=True)
    evidence=[]
    for file in sorted(source_dir.rglob('*.py')):
        if not file.is_file() or file.is_symlink() or file.stat().st_size==0:continue
        if len(evidence)>=150:raise ValueError('Too many Python modules for bounded candidate analysis')
        rel=file.relative_to(source_dir)
        if len(str(rel))>220: raise ValueError('SCT path exceeds safe review length')
        data=repair_text(file.read_text(encoding='utf-8-sig'))
        output=target_dir / ('candidate_'+str(len(evidence)+1)+'.py')
        output.write_text(data['code'],encoding='utf-8')
        evidence.append({'originalRelativePath':str(rel),'candidateFile':output.name,
                         **{k:v for k,v in data.items() if k!='code'}})
    (target_dir/'report.json').write_text(json.dumps({'modules':evidence,'origin':'ACTUAL_SCT_IMPORT','runtimeParity':'NOT_PROVEN'},indent=2),encoding='utf-8')
    return evidence
