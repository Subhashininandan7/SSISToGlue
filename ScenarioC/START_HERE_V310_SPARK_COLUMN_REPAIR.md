# Migration Forge v3.0.10 — Spark Column callable repair diagnostics

## Root cause and scope

v3.0.9 reported `Bedrock proposal rejected after 3 attempts: 'Column' object is not callable`.
That Python `TypeError` means some model-generated expression tried to call a Spark Column like a Python function. It is a generated-code defect, **not** an AWS login, Hadoop, or Spark startup failure. We have not been given the exact generated candidate from the failing Windows run, so its precise expression cannot be proven from the summary alone.

## Code changes (limited to the AI ExecuteProcess adapter)

1. `engine/unsupported_process_ai.py`: deterministic AST checks for provable bad `Column` invocations, including `F.col("X")()`, `.strip()` and `.lower()` on a Spark Column, and extra parentheses after `.cast()`. Correct Spark functions remain allowed. When Spark detects another `Column` invocation defect at runtime, retries receive a source-line number and a bounded expression from the structured runtime report.
2. `engine/unsupported_process_runner.py`: capture the actual candidate.py frame and line of a Python exception in `generatedLocation`. The runner still writes separate structured results. No AWS credentials or input row values are added to this diagnostic.
3. `DemoWeb/wwwroot/unified.js`: update the visible version marker to `3.0.10-spark-column-repair`.
4. `tests/test_v310_spark_column_callable.py`: new regression tests for rejected expressions, legitimate expressions, runtime diagnostics, and focused retry requests.

Existing SCT conversion, Glue deployment, approval and CSV comparison implementations were not modified. Invalid generated code is never automatically approved or deployed. No global string-method rewrite or weakened AST gate was introduced.

## What we verified

- Python regression suite: 318 tests passed, 4 subtests passed. 313 existing SyntaxWarning messages surfaced from legacy test fixtures.
- ZIP archive integrity checked during packaging.
- This runtime does not have the customer's Windows Spark environment or AWS credentials; **live Bedrock generation, post-approval local Spark execution, and Visual Studio build are not verified**.

## Run from Visual Studio

Extract to a new directory. Open `FinalDemo/ScenarioC/SSISGlueDemo.sln`; run `DemoWeb` directly. Preserve the existing AWS and Hadoop configuration. Click `Generate AI fixes where needed` for Scenario C only. Check that the operation JSON includes `appVersion: 3.0.10-spark-column-repair`.

If model output remains defective, inspect the newest session `ai-diagnostics.json` under `%USERPROFILE%\.ssis_glue_demo\sessions\<session-id>\process-ai\`. The improved feedback should identify the generated candidate line when a runtime TypeError occurs. Do not deploy unless local validation and approval succeed. CSV reference parity is a separate requirement; the earlier reference/source data mismatch is not solved by this change.
