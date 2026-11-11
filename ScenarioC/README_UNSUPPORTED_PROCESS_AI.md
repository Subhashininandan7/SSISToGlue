# Migration Forge — Reviewed Bedrock remediation for SCT Execute Process 25029

## Implementation boundary

This is an **added, independent remediation lane**, implemented against the available
`ScenarioC.zip` Migration Forge source (NOT a verified checkout of your installed
v2.8.5 build). It does **not** overwrite the existing Migration Forge A/B runs.
The new page runs in the same ASP.NET Core Visual Studio solution:

`http://127.0.0.1:5297/unsupported-ai.html`

Supported case: one static PowerShell `.ps1` called by a standard SSIS
`Microsoft.ExecuteProcess` task; original AWS SCT conversion must contain the
genuine `25029` warning. The adapter handles **other original packages of this
same structural pattern**, without hard-coded package, script, CSV or column names.
It cannot infer arbitrary executable/PowerShell side effects, complex multi-task
orchestrations, SQL mutations, secrets or external dependencies. Those remain
blocked for additional source review and adapter support.

## How the AI repair works

1. Read the **actual original `.dtsx` XML** and derive task name, task GUID,
   static external script filename, task description and success exit code.
2. Read the **actual original AWS SCT output ZIP**, confirm a single 25029
   `Microsoft.ExecuteProcess` warning, and fingerprint original artifacts.
3. Require the **actual referenced `.ps1` file**. The `.dtsx` only references
   external scripts; it does **not** contain the PowerShell source.
4. Require sample input CSVs and independent reference SSIS output CSVs.
   Extract schema headers only for Bedrock; **do not send row data**.
5. With explicit approvals, call Bedrock Runtime `converse` using the configured
   AWS profile / region / model. Supply the original task metadata, original
   SCT warning and stub, input/output headers, and approved PowerShell source.
   Do not synthesize a success response if Bedrock is not available.
6. Bedrock returns a JSON proposal with a complete PySpark module containing
   `def transform(spark, input_prefix, output_prefix)`; validate the Python AST,
   reject risky imports/constructs, and show a review-only unified diff.
7. Reviewer approves the exact SHA-256 of the proposed code. Never auto-accept.
8. Run the code in a **separate local Python process** with PySpark and compare
   Spark CSV part files to the independent expected CSV rows and column order.
   This is test-data parity only, not a proof of SSIS equivalence for all inputs.
9. **Cloud deployment remains blocked** in this adapter. Genuine AWS Glue
   orchestration/deployment needs a distinct adapter with S3 input/output
   contracts, Glue job arguments and independently approved run policy.

## How to run (Windows / Visual Studio 2022)

- Install the .NET 8 SDK and the Visual Studio 2022 ASP.NET/Web workload.
- Install Python packages from `requirements.txt`, plus PySpark in an
  **isolated development environment**, e.g. `python -m pip install pyspark==3.5.4`.
  Use a compatible Java runtime. Do not run model-generated code with production
  AWS credentials or on your production SQL Server machine.
- Extract to a short Windows path, e.g. `D:\MigrationForgeBedrock\`.
- Open `SSISGlueDemo.sln`; start `DemoWeb` in Visual Studio 2022 (F5).
- Open `http://127.0.0.1:5297/unsupported-ai.html`.
- Select the original **SSIS package** (`.dtsx`), real **SCT conversion ZIP**,
  referenced PowerShell **script** (`.ps1`), input CSVs, and independently
  generated SSIS output reference CSVs.
- Click **Analyze** → approve model charges and source transmission →
  **Generate AI proposal** → inspect exact diff → approve →
  **Execute local Spark test**. Never treat model output as inherently trusted.

For the supplied scenario:

- `.dtsx`: `C_Unsupported_Execute_Process_AI_Demo.dtsx`
- SCT ZIP: `original-conversion-output (4).zip`
- external script: `transform.ps1`
- input: `Employees.csv`
- baseline: **actual** original SSIS `ActiveEmployees.csv` renamed or copied as
  `ActiveEmployees.csv` in the baseline selector (same name as output).
- A bundled `Expected_ActiveEmployees.csv` fixture is a useful test oracle,
  but is **not evidence of an actual original SSIS run**. If using it for
  preliminary testing, rename a copy to `ActiveEmployees.csv` and label the
  result fixture parity, not independent SSIS equivalence.

Original SCT conversion is already provided from your real Windows conversion;
this flow intentionally starts **after genuine SCT conversion** to handle an
SCT-stub case. It does not pretend SCT converted the unsupported task.

## Verification performed here

- 178 Python tests passed, 4 subtests passed; no failures on the provided
  source and included test evidence after extraction.
- 12 new focused tests passed, including genuine user-supplied SCT 25029
  archive inspection, original `.dtsx` XML parsing, model-response test-double,
  code-review integrity, safety rejection and failed runtime conditions.
- The new Python modules and CLI compile/import successfully.

**NOT verified here:** Visual Studio 2022 compilation, real AWS Bedrock network
invocation, real Spark execution (PySpark unavailable in this runtime), AWS Glue
execution or actual SSIS runtime equivalence. A mocked transport test does not
establish a successful Bedrock API call. The new code is a development PoC, not
an isolated sandbox or production-grade code execution service.

## Engineering safety limits

- SSIS task execution is never performed as part of analysis.
- Secret patterns in external PowerShell source block model submission.
  A manual privacy review is still required; regex screening is not complete.
- Request only schema headers; raw input/output rows do not enter the prompt.
- SHA fingerprints bind the package, script, SCT archive, and reviewed code.
- Unsafe Python AST patterns are rejected but **AST filtering is not a security
  sandbox**. Run only in a disposable, network-isolated development environment
  without production credentials.
- Cross-file source calls and arbitrary non-PowerShell Execute Process
  executables are not automatically translated.
- The existing main migration page, A/B sessions, and deployment pipeline are
  unchanged. This is a separate explicit workflow page linked from the home UI.

## Tests

`python -m pytest -q tests`

The added tests reside in `tests/test_v285_unsupported_process_ai.py`.
