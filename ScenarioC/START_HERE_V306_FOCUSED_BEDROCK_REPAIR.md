# Migration Forge v3.0.6 — focused Bedrock retry correction

## Scope
This is a targeted update to v3.0.5. The sole existing source file changed is `engine/unsupported_process_ai.py`. New regression tests are in `tests/test_v306_focused_repair.py`. Existing ASP.NET Core UI, AWS setup, SCT conversion, Glue deployment, CSV validation, and approval gate are unchanged.

## Why the previous version failed
The diagnostic from 2026-11-09 showed first attempt rejected due to source-defined ungrouped fixed-point representation; second and third attempts had no recognized JSON or Python module. The old loop appended the error to a growing prompt without including the first rejected code, so the model had no concrete candidate to edit.

## Correction
- On static/semantic rejection, retain the last *extracted* Python module strictly as untrusted retry context (never make it available for approval until it passes validation).
- Rebuild bounded retry requests from the original source evidence, instead of stacking previous retry requests.
- Provide the original rejected code and the specific error. If a later model response is unparseable, keep the prior extracted module and original semantic defect in the next retry.
- Keep the AST/security checks, source-derived numeric formatting checks, local Spark preflight and separate human approval unchanged.
- Record a non-sensitive `retryStrategy` diagnostic.

## Run
1. Extract ZIP to a NEW folder.
2. Open `FinalDemo/ScenarioC/SSISGlueDemo.sln` directly with VS2022.
3. Start `DemoWeb`. Use the existing AWS settings. No special PowerShell environment startup is needed.
4. For Scenario C, run AI remediation on a new or still-unapproved migration session. A/B do not need to rerun. Review the resulting diff before approving.
5. If Bedrock still returns unsuitable output, inspect `%USERPROFILE%/.ssis_glue_demo/sessions/<id>/process-ai/ai-diagnostics.json` and do not approve any generated code that failed parity checks.

## Verification / limitations
Python suite: 274 passing tests plus 4 passing subtests in the evaluation environment (mocked Bedrock responses). ZIP integrity checked. This is not a claim of successful live Bedrock, Windows Visual Studio compilation, Glue deployment or end-to-end SSIS parity.
