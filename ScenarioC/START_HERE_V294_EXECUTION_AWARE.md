# Migration Forge v2.9.4 — execution-aware Bedrock remediation candidate

## Scope and safety

This release updates the ORIGINAL **Generate AI fixes where needed** button. No second AI or validation button is added. The supported unsupported-task adapter is specifically genuine SCT error **25029 / Microsoft.ExecuteProcess**, with ONE static `.ps1` dependency and **CSV input/output**. This is not an arbitrary SSIS task translator.

The previous Scenario A/B conversion paths and their existing repair logic have not been rewritten. The package has **NOT** been compiled in Visual Studio or executed against live AWS on this host. Existing A/B Glue success was not rerun.

**Security boundary:** The preflight invokes generated model code in a throwaway directory and separate Python subprocess; THIS IS NOT A SECURITY SANDBOX. Do not expose this capability to untrusted users, confidential code, or production infrastructure. Use an OS-isolated, network-restricted worker/container for enterprise deployment. Static AST filters cannot guarantee Python code is safe.

## Changes

- Original SSIS task metadata, actual approved external script, SCT 25029 stub, and optional CSV column names comprise the Bedrock evidence. Neither output CSV nor reference output is required for AI translation.
- The existing button checks generated code with Python AST and then attempts local PySpark execution using *uploaded input files*, before offering the candidate for approval. No reference output means status `OUTPUT_GENERATED`, **not** SSIS parity.
- For clearly attributable **CODE_RUNTIME**, **DATA_CONTRACT**, or **OUTPUT_MISSING** failures, the model receives sanitized error information and can regenerate a maximum of **3 total proposals**. Missing input and Spark/Java environment errors are **not** sent back as code-repair requests.
- The diff shows the local preflight status alongside Bedrock's proposed code. Review of the exact hash and approval remain mandatory; the usual post-approval local test runs again.
- Spark writes result JSON to a dedicated file. Spark console output is never parsed as the JSON result. The preflight result is separate from the approved candidate. A failed attempt is not marked `READY_FOR_DEPLOYMENT`.
- This lane does **NOT** automatically deploy the unsupported-task replacement to AWS Glue. Deployment remains blocked until a validated Glue adapter exists.

## Windows installation and testing

1. Keep your successful v2.8.5 Scenario A/B installation unchanged. Extract this ZIP to a distinct folder such as `D:\MigrationForgeV294`.
2. Install Python 3.13, matching PySpark and Java in the environment actually launched by the .NET host. Check `python -m pip show pyspark` and a local Spark smoke test in **that same interpreter**. The supplied requirements include boto3/pytest, not PySpark.
3. Open `ScenarioC\SSISGlueDemo.sln` with VS2022 and start `DemoWeb`. Confirm `v2.9.4` on the page.
4. Start a new portfolio and select the source folder containing the original `.dtsx`, matching PowerShell script, and any available input CSV. You do **not** need a previously generated output CSV.
5. Convert using SCT, analyze, select both Bedrock consent boxes, and click the **single** Generate AI fixes button.
6. If the input CSV is supplied and the Python Spark environment is working, the proposal now includes `runtimePreflight.status` and `validationAttempts`. If runtime failed because of code, a bounded retry is attempted. If it failed because of Java or missing files, correct your environment/inputs rather than regenerating code.
7. Review the diff. Click Apply approved fixes only for reviewed code. The existing post-approval local check runs automatically. Production Glue deployment is still blocked for this unsupported task adapter.

## Validation conducted in this build

- `python -m pytest -q`: **212 passed**, 4 subtests; warnings were emitted by tests.
- `node --check DemoWeb/wwwroot/unified.js`: passed.
- `python -m compileall -q engine`: passed.
- ZIP integrity test passed.
- Not performed: Windows Visual Studio compilation, actual AWS Bedrock request, real Windows PySpark job, Glue deployment, independently executed SSIS parity.

## Known constraints

- Preflight is limited to CSV files in the currently supported ExecuteProcess remediation adapter; external binaries, shell side effects, network calls, database writes and additional task dependencies require specialized adapters.
- With no input files the proposal is reviewable but `NOT_RUN` and cannot be presented as runtime verified.
- With no trusted reference output, actual CSV output generation is shown but SSIS equivalence is **not** claimed.
- Bedrock code generation is nondeterministic and may still return a blocked result after retries. That is a correct fail-closed outcome.
- The source baseline is based on the previously supplied v2.9.3 integrated solution, not an independently retrieved copy of your installed v2.8.5 build.
