# Migration Forge v3.0.7 — Source-guarded Bedrock proposal normalization

## Purpose and verified scope
This release addresses repeated Scenario C Bedrock candidate rejections. It builds on v3.0.6. The existing AWS Setup Wizard, portability setup, SCT processing, Glue deployment, CSV comparison and approval hash workflow remain unchanged.

## Changes
- `engine/unsupported_process_ai.py`: require exactly one `transform(spark,input_prefix,output_prefix)` ENTRY POINT, but permit safely restricted top-level helper functions. Reject duplicate transform definitions, decorators, async functions, imports outside the allowlist and top-level executable statements.
- When the model supplies exactly one unambiguous synchronous function with the correct signature but a different name, normalize its entry-point name. If multiple candidates exist, fail rather than guess.
- When original PowerShell explicitly defines `Column = (...).ToString('F<n>')`, change only a matching Spark `format_number(expression,n)` in that output column to `format_string('%.nf',expression)`. Do not change other columns, other precisions or general Spark formatting. This is a source-grounded *candidate* adjustment for human review; it does not assert numeric equivalence, rounding equivalence or SSIS parity.
- Continue passing every candidate through static safety checks, original-source checks, runtime preflight where available, exact-code review and SHA-256 approval. New diagnostics record only normalized column names and entry-point choice, not raw model output.
- `DemoWeb/wwwroot/unified.js`: version marker now reads `3.0.7-source-guarded-bedrock-normalization` so the UI proves which JS bundle is running. No workflow control logic was changed.
- New regression tests for a single helper, duplicate transform, alternative entrypoint, grouped numeric formatting, unrelated output columns and direct function-import aliases.

## Start on Windows
1. Extract into a NEW empty folder.
2. Open `FinalDemo/ScenarioC/SSISGlueDemo.sln` in Visual Studio 2022 and run `DemoWeb`.
3. Refresh your browser with Ctrl+F5 so the new JS is loaded.
4. Confirm AWS profile/model settings, then click Generate AI fixes for Scenario C once. Do not rerun A/B or click Run packages for already executed Glue jobs.
5. If the candidate is generated, REVIEW the code diff. Run local validation against the same input used by the original SSIS job; do not claim output parity on a different dataset. Approve only after inspection.
6. On further rejection, inspect `%USERPROFILE%\.ssis_glue_demo\sessions\<session>\process-ai\ai-diagnostics.json` for the first real AST/runtime error.

## Limitations
The test suite runs offline with mocked model responses. A successful Windows build, live Bedrock response, Spark execution and Glue parity are **not** verified here. This is not a guarantee that every arbitrary PowerShell script can be translated without review. The permitted `format_string` adjustment is limited to ungrouped fixed-point formatting found in the source; unusual rounding, null handling or culture behavior still require parity tests.
