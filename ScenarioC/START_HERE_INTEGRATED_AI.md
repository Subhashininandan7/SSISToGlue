# Migration Forge — Integrated Generate AI fixes (candidate)

This build modifies the **existing five-step Migration Forge UI** and its existing **Generate AI fixes where needed** button. No separate page is required. Based on the supplied `ScenarioC.zip` source (README identifies v2.8.3, with later 2.8.4/2.8.5-related modifications); this is **not** a binary-identical verified patch to the user's separately installed v2.8.5.

## What changed

- The normal analysis and Bedrock repair logic for Scenario A/B remains intact.
- If actual SCT output contains `25029` for exactly one `Microsoft.ExecuteProcess` task and no SCT coordinator is provable, Analyze marks the package as unsupported-task AI-eligible, instead of silently making it invisible to AI.
- The **existing** Generate AI button detects that eligibility. With model cost and code-sharing approvals it requests a review-only Bedrock PySpark proposal using: original SSIS Execute Process metadata, true SCT warning/stub, the script file named by SSIS `-File` arguments and, when available, input CSV schema headers. The original external `.ps1` is an explicitly selected folder input and must be present. External source is essential: the .dtsx does not contain the script logic.
- **No pre-existing output CSV, `Expected_*.csv`, or filename-based reference convention is needed for AI proposal.** Actual output is produced by executing the approved candidate in local Spark. Independent reference CSVs remain optional evidence for parity; without them the status is `OUTPUT_GENERATED`, **not** `OUTPUTS_MATCH`.
- Existing Review / Apply buttons require exact proposal hash approval. The candidate cannot auto-deploy to Glue: there is no verified task-replacement Glue adapter yet. The separate-page experiment remains in source history but is not linked from the main UI.

## Workflow

1. Extract the ZIP to a **new** short folder, e.g. `D:\MigrationForgeIntegratedAI`; do not overwrite your successful v2.8.5 installation or its sessions.
2. Open `ScenarioC/SSISGlueDemo.sln` in Visual Studio 2022 (requires .NET 8, Python dependencies from requirements.txt).
3. Select `DemoWeb` and start with F5. Use the normal main Migration Forge page only.
4. Select a source folder containing `.dtsx`, referenced `transform.ps1`, and optional source CSVs. The sidecar script filename must match the original SSIS Execute Process Task metadata. Upload is local and model transmission requires explicit consent.
5. Convert with real installed AWS SCT. Analyze. A real SCT 25029 / missing coordinator should enter `REPAIR_BLOCKED` with `UNSUPPORTED_TASK_AI_ELIGIBLE` recorded in the action result.
6. Tick model charges and screened source transmission; use **Generate AI fixes where needed**. Review the diff, then approve the exact patch.
7. Optional local PySpark validation can generate real output without SSIS baselines. This does not prove behavioral parity. The candidate remains blocked from AWS Glue auto-deployment until a separate runtime/deployment adapter exists.

## Scope and safety

This is a **generic-by-metadata** adapter for one static PowerShell `.ps1` invoked by a genuine standard SSIS `Microsoft.ExecuteProcess` task. No hard-coded package, script, or output filename. It is **not** a universal translator for custom DLLs, executables, multiple interconnected tasks, unknown data sources, missing scripts or unproven side effects. Analysis declines those cases. The model may return code that requires review or further changes, and an AST screening is not a secure sandbox; run only in an isolated non-production development environment. Never claim Bedrock invocation merely from a mocked test. Do not send secrets.

## Verification performed

`python -m pytest -q tests`: **184 passed, 4 subtests passed**, warnings present; JavaScript parses with `node --check`. Tests use mocked Bedrock transport. No real Bedrock request, Windows Visual Studio build, Windows SSIS validation, live Glue deployment, or real PySpark run was possible here. Prior Scenario A/B successes are preserved in the original installation, not independently repeated live against AWS in this environment.
