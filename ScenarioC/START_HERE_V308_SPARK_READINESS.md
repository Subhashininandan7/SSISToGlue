# Migration Forge v3.0.8 — Portable Spark readiness and diagnostics

## Targeted changes

- `DemoWeb/Program.cs`: the Python adapter inherits the current Windows user's auto-created scratch folders via TEMP, TMP, TMPDIR, SPARK_LOCAL_DIRS, and **SPARK_SUBMIT_OPTS=-Djava.io.tmpdir=...**. JAVA_HOME and HADOOP_HOME discovery are retained; this does not modify system-wide settings or require launching Visual Studio from PowerShell.
- `engine/unsupported_process_ai.py`: if local input fixtures are available for a real AWS Bedrock request, it starts a separate minimal SparkSession and verifies `spark.range(1).count()` **before invoking Bedrock**. If Spark does not start, the operation aborts as `SPARK_NOT_READY` without incurring another Bedrock generation request. The readiness check does not execute any generated code. Injected mock transports skip this check for offline tests.
- `engine/unsupported_process_runner.py`: retain the actionable Java `Caused by:` root cause in structured runtime results rather than only a truncated Scala stack trace. Error excerpts are bounded and filesystem paths are sanitized in the web-facing summary.
- `DemoWeb/wwwroot/unified.js`: update the version marker to 3.0.8.

## Test on Windows

1. Unzip in a separate folder and open `FinalDemo/ScenarioC/SSISGlueDemo.sln` directly in Visual Studio 2022.
2. Run `DemoWeb`, visit **Local runtime**, and verify Python, PySpark and Java are detected.
3. Verify AWS settings, then start **Generate AI fixes where needed** for C only. There is no need to run or redeploy A/B.
4. If local Spark cannot start, read `~/.ssis_glue_demo/sessions/<session-id>/process-ai/ai-diagnostics.json`. `SPARK_NOT_READY` means AWS Bedrock was not invoked.
5. This change does not guarantee that generated business logic matches SSIS: keep existing review and CSV baseline validation.

The Python regression suite can run on a developer machine via `python -m pytest tests -q` from the ScenarioC folder. The environment used to assemble the ZIP does not provide Windows Visual Studio, a configured local Windows Spark JVM, or an AWS account, so actual Windows/Spark/Bedrock end-to-end behavior remains to be verified there.
