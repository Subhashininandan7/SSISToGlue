"""Conservative, nonexecuting repair of recurrent AWS SCT Python syntax defects.

Only Python code tokens, never SQL strings/comments, can be edited. This is not
an SSIS semantic repair and never makes a blocked script deployable by itself.
"""
from __future__ import annotations
import ast
import io
import re
import tokenize


def fix_quoted_column_access(source):
    """Translate `frame.'col'` to `frame['col']` at lexical token boundaries.

    This matches the concrete invalid syntax emitted by some SCT Lookup joins.
    It does not modify Spark filter/join logic, SQL literals or identifiers.
    Return (new_source, edits). If resulting text does not compile, keep it as a
    syntax *candidate* requiring further fixes; it must not be deployed.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, SyntaxError):
        return source, []
    edits = []
    patches = []
    line_offsets = [0]
    for line in source.splitlines(keepends=True):
        line_offsets.append(line_offsets[-1] + len(line))
    for i in range(len(tokens)-2):
        tok, dot, quoted = tokens[i:i+3]
        if (tok.type == tokenize.NAME and dot.type == tokenize.OP and dot.string == '.'
                and quoted.type == tokenize.STRING and
                re.fullmatch(r"'([a-zA-Z_][a-zA-Z0-9_]*)'",quoted.string) and
                tok.end == dot.start and dot.end == quoted.start):
            # Replace only the dot and single quoted identifier. No modification
            # anywhere else, including SQL/query strings and comments.
            start = line_offsets[dot.start[0]-1] + dot.start[1]
            end = line_offsets[quoted.end[0]-1] + quoted.end[1]
            patches.append((start,end,'[' + quoted.string + ']'))
            edits.append({'line':tok.start[0],'frame':tok.string,
                          'column':quoted.string[1:-1],
                          'rule':'SCT_INVALID_QUOTED_COLUMN_ACCESS'})
    if not patches:
        return source, []
    candidate=source
    for start,end,replacement in sorted(patches,reverse=True):
        candidate=candidate[:start]+replacement+candidate[end:]
    # Explicitly preserve every string token, including multiline SQL.
    try:
        after_tokens=list(tokenize.generate_tokens(io.StringIO(candidate).readline))
    except (tokenize.TokenError,SyntaxError) as exc:
        raise ValueError('Syntax candidate cannot be tokenized') from exc
    before_strings = [t.string for t in tokens if t.type == tokenize.STRING]
    after_strings = [t.string for t in after_tokens if t.type == tokenize.STRING]
    if before_strings != after_strings:
        raise ValueError('Repair changed Python/SQL string literals; rejected')
    return candidate, edits


def fix_missing_spark_type_imports(source):
    """Add missing names from pyspark.sql.types only when actually referenced."""
    tree = ast.parse(source)
    types = {'StructType','StructField','StringType','IntegerType','LongType',
             'DecimalType','DateType','TimestampType','DoubleType','FloatType',
             'BooleanType','ShortType','BinaryType','ArrayType','MapType'}
    referenced = {n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Load)}
    defined = set()
    for node in tree.body:
        if isinstance(node,ast.ImportFrom):defined.update(n.asname or n.name for n in node.names)
        if isinstance(node,ast.Import):defined.update(n.asname or n.name.split('.')[0] for n in node.names)
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):defined.add(node.name)
        if isinstance(node,ast.Assign):defined.update(n.id for t in node.targets for n in ast.walk(t) if isinstance(n,ast.Name))
    missing = sorted((referenced & types)-defined)
    if not missing:return source,[]
    prefix = 'from pyspark.sql.types import '+', '.join(missing)+'\n'
    # Keep shebang/encoding, module docstring, and __future__ imports ahead of imports.
    header_end = 0
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant) and isinstance(tree.body[0].value.value, str):
        header_end = tree.body[0].end_lineno
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == '__future__':
            header_end = max(header_end, node.end_lineno)
    lines = source.splitlines(keepends=True)
    if header_end == 0:
        if lines and lines[0].startswith('#!'):
            header_end = 1
        if len(lines) > header_end and re.search(r'coding[:=]', lines[header_end]):
            header_end += 1
    result = ''.join(lines[:header_end]) + prefix + ''.join(lines[header_end:])
    ast.parse(result)
    return result,[{'rule':'ADD_MISSING_PYSPARK_TYPE_IMPORT','type':x} for x in missing]


def repair_candidate(source):
    """Syntax-only safe subset; never assert runtime/SSIS equivalence."""
    candidate,edits=fix_quoted_column_access(source)
    try:
        ast.parse(candidate)
    except SyntaxError as exc:
        return {'candidate':candidate,'edits':edits,'syntaxPass':False,
                'error':f'{exc.msg} (line {exc.lineno})','runtimeReady':False}
    candidate,extra=fix_missing_spark_type_imports(candidate)
    return {'candidate':candidate,'edits':edits+extra,'syntaxPass':True,
            'error':None,'runtimeReady':False}
