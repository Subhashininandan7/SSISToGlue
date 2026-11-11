"""Runs separately from API process; still requires a trusted isolated dev environment."""
from __future__ import annotations
import csv,importlib.util,json,sys,traceback
import re
from pathlib import Path

def rows_csv(path):
    with path.open(encoding='utf-8-sig',newline='') as f:
        reader=csv.DictReader(f)
        header=reader.fieldnames or []
        return header,sorted(tuple((k, row.get(k,'')) for k in header) for row in reader)
def main(root,candidate_override=None,output_override=None):
    from pyspark.sql import SparkSession
    root=Path(root);manifest=json.loads((root/'manifest.json').read_text())
    spark=SparkSession.builder.master('local[2]').appName('MigrationForge-AI-Review').getOrCreate()
    try:
        spec=importlib.util.spec_from_file_location('reviewed_candidate',Path(candidate_override) if candidate_override else root/'candidate.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        out=Path(output_override) if output_override else root/'generated';out.mkdir(exist_ok=True)
        module.transform(spark,str(root/'input'),str(out))
        outputs=[]
        # The source program defines output names. If no independent SSIS
        # reference exists, inspect actual generated Spark part files and label
        # output generation, NOT semantic equivalence.
        generated={d.name:d for d in out.iterdir() if d.is_dir() and list(d.glob('part-*.csv'))}
        if not generated:
            return {'status':'FAILED','error':'Candidate generated no CSV part files'}
        for name,target in generated.items():
            parts=list(target.glob('part-*.csv'))
            actual_rows=[];actual_header=None
            for file in parts:
                h,records=rows_csv(file)
                if actual_header is not None and h!=actual_header:raise ValueError('Inconsistent CSV part-file header')
                actual_header=h;actual_rows.extend(records)
            record={'name':name,'actualRows':len(actual_rows),'columns':actual_header}
            if name in manifest.get('outputs',{}):
                expected=rows_csv(root/'reference'/name)
                record.update({'status':'MATCH' if (actual_header,sorted(actual_rows))==expected else 'MISMATCH','expectedRows':len(expected[1])})
            else:record['status']='GENERATED_UNVERIFIED'
            outputs.append(record)
        missing=[n for n in manifest.get('outputs',{}) if n not in generated]
        if missing: return {'status':'FAILED','outputs':outputs,'error':'Expected reference outputs not generated: '+', '.join(missing)}
        parity=bool(manifest.get('outputs')) and all(x['status']=='MATCH' for x in outputs)
        mismatch=any(x['status']=='MISMATCH' for x in outputs)
        return {'status':'MISMATCH' if mismatch else 'MATCH' if parity else 'OUTPUT_GENERATED',
                'outputs':outputs,'note':'Output generation is not SSIS behavioral parity unless independent references were supplied and matched.'}
    finally:spark.stop()
if __name__=='__main__':
    # The structured result is written to a dedicated file; stdout/stderr can
    # contain Spark/log4j messages or dependency output and are not a protocol.
    result_path=Path(sys.argv[2])
    try:
        result=main(sys.argv[1],sys.argv[3] if len(sys.argv)>3 else None,sys.argv[4] if len(sys.argv)>4 else None)
        exit_code=0
    except Exception as e:
        trace = traceback.format_exc()
        causes = re.findall(r'(?m)^\s*Caused by:\s*(.+)$', trace)
        # Root cause is explicitly retained before truncating the stack tail;
        # prior versions exposed only SparkFileUtils Scala stack frames.
        root_cause = causes[-1][:400] if causes else str(e).splitlines()[0][:400] if str(e) else type(e).__name__
        # Preserve the line of *generated candidate code* that raised the
        # exception. The caller feeds this into the next, bounded model repair.
        # No input CSV rows, AWS credentials or raw runtime environment are logged.
        generated_location = None
        candidate_path = Path(sys.argv[3]).resolve() if len(sys.argv)>3 else (Path(sys.argv[1])/'candidate.py').resolve()
        for frame in reversed(traceback.extract_tb(e.__traceback__)):
            try:
                is_candidate = Path(frame.filename).resolve() == candidate_path
            except (ValueError, OSError):
                is_candidate = False
            if is_candidate:
                expression = (frame.line or '').strip()
                # Do not surface arbitrary literals/paths in diagnostics.
                safe_expr = re.sub(r"[A-Za-z]:\\[^ ]+", '[path]', expression)
                generated_location = {'line':frame.lineno, 'expression':safe_expr[:180]}
                break
        result={'status':'FAILED','error':str(e)[-1200:],
                'exceptionType':type(e).__name__, 'rootCause':root_cause,
                'tracebackTail':trace[-1800:], 'generatedLocation':generated_location}
        exit_code=1
    temp=result_path.with_suffix('.json.tmp')
    temp.write_text(json.dumps(result),encoding='utf-8')
    temp.replace(result_path)
    sys.exit(exit_code)

