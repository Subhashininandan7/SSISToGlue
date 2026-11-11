# Migration Forge v2.9.1 — Bedrock AST feedback and one bounded retry

This is an integration candidate based on the supplied Migration Forge v2.9.0 package, not a verified installed v2.8.5 snapshot.

## What changed

- Existing **Generate AI fixes where needed** button retained; no extra UI button.
- For a genuine SCT `25029` Execute Process conversion gap, Bedrock is instructed to return JSON containing a Python module with exactly one `def transform(spark, input_prefix, output_prefix):` function, plus permitted imports and optional module docstring. Executable top-level statements are rejected.
- Python `ast` validation reports the rejected statement type and source line, e.g. `line 2, Assign: No executable statements at module import time`.
- Exactly **one** regeneration attempt is allowed using the validation feedback. Both attempts must independently pass the same validator; retry does not weaken safety rules.
- An accepted result remains **AI_PATCH_REVIEW_ONLY**, with an exact code hash, before/after diff, validation attempts, and human approval required. Rejected model output is not automatically promoted to a candidate.
- The existing review/approval action pins the exact SHA-256, verifies original SCT/package/script evidence still matches, and revalidates code before writing `candidate.py`.
- Existing automatic local PySpark validation after human approval is preserved, with no automatic Glue deployment for unsupported tasks. Local Spark runs untrusted model-proposed Python and **is not a security sandbox**. Test only on an isolated trusted development host with least-privilege credentials; never with production data or credentials.
- Rejected proposal diagnostics are written to the per-session `process-ai/ai-diagnostics.json` file and the last validation error is surfaced through the existing error message. Diagnostics contain line/type/message and attempt outcomes, not the rejected code or source script.
- Reference output CSV is **not required** to generate or approve a proposal. When absent, a later local run can report OUTPUT_GENERATED but cannot assert SSIS parity.

## Running

1. Extract to a NEW folder, e.g. `D:\MigrationForgeV291`. Do not overwrite the v2.8.5 A/B proven installation.
2. Open `ScenarioC\SSISGlueDemo.sln` using Visual Studio 2022, launch DemoWeb. Existing web UI stays on port 5297.
3. Upload original `.dtsx` + referenced `transform.ps1` and available source files in one selected folder. Run genuine AWS SCT conversion.
4. Click the same **Generate AI fixes where needed** button. If the first model response violates the Python-module contract, the system returns AST feedback to Bedrock and retries once.
5. Review the model explanation, code diff, and `validationAttempts`. Approve only if the business logic and source evidence are correct; local validation follows in the same workflow.

## Validation performed here

- Full offline suite: **199 tests passed**, including retry failure, retry success, single-button UI, A/B regression tests, hash pinning and no-output-baseline behavior.
- `python -m compileall` and `node --check` succeeded.
- Not performed: live Bedrock API call, Windows VS2022 compilation, real local PySpark run, Glue deployment/output validation. Existing Scenario A/B live runs were not repeated.

## Limitations

- The present adapter supports one unambiguous `Microsoft.ExecuteProcess` PowerShell `-File` task with genuine SCT `25029` evidence. Other unsupported components and general orchestration remain unsupported.
- AST inspection is a *limited static filter*, not proof of code safety or correctness. Model code must be reviewed before any local execution. Continue to block AWS Glue deployment until a separately verified cloud adapter is implemented.
