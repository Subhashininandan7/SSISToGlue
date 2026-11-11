"""Isolated process for REAL local PySpark execution of repaired SCT code.
Executed only by the controlled Scenario A preflight runner.
"""
import json
import os
import sys
from pathlib import Path

def main():
    z,inp,out,report=sys.argv[1:5]
    if not Path(z).is_file() or not Path(inp).is_file():raise ValueError('Missing controlled SCT inputs')
    if Path(out).exists():raise ValueError('Output directory must not already exist')
    sys.path.insert(0,str(Path(z).resolve()))
    os.environ['FORGE_INPUT_CSV']=str(Path(inp).resolve())
    os.environ['FORGE_OUTPUT_CSV']=str(Path(out).resolve())
    from pyspark.sql import SparkSession
    import pyspark
    spark=SparkSession.builder.master('local[2]').appName('Forge-SCT-ScenarioA-Validation').getOrCreate()
    try:
        from a_employees_active_bonus import a_employees_active_bonus
        a_employees_active_bonus({})
        Path(report).write_text(json.dumps({'pysparkVersion':pyspark.__version__,'execution':'SCT_MODULES_INVOKED'}),encoding='utf-8')
    finally:spark.stop()
if __name__=='__main__':main()
