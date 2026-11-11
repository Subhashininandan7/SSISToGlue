# Migration Forge v2.9.9 — source-driven numeric-fidelity repair

This release starts from the complete v2.9.8 Visual Studio 2022 solution, keeping all established SCT, batch, AWS, approval, download, and validation behavior.

## Fixed at AI-generation time

- When the *original user-approved PowerShell* explicitly calls `.ToString('F2')`, `.ToString('F0')`, etc. on an output property, the AI candidate must not replace that output with Spark `format_number()` (which injects grouping separators and yields string output). The output property name is extracted from the original source, not a hardcoded Scenario C field.
- When an independent reference CSV is available *before generation*, an ungrouped numeric output column cannot be generated using Spark `format_number()` in the same column.
- A rejected candidate gets a bounded, specific, source-backed diagnostic through the EXISTING Bedrock retry, which can produce a new proposed patch automatically. The reviewer must still approve its exact SHA-256 hash before any deployment. The generator does not force an unconditional decimal cast: numeric formatting that the original source actually requires remains possible.
- The absence of source evidence/reference means no fictitious schema inference. All old accepted revisions remain pinned to their original hash and unchanged.

## Important workflow limitations

- The new numeric-fidelity check runs during **Generate AI fixes where needed**, BEFORE code approval. Existing approved and executed v2.9.8 sessions are deliberately not mutated. Create a new migration portfolio for Scenario C to obtain newly generated code. Old A/B runs do not need to be rerun.
- Your prior real Glue output had a different set of employee records from the original reference (Asha/Chitra/Dev vs Ravi/Priya/Meena). No numeric-format correction can fix differing source rows. Align the original input data used in SSIS and Glue before claiming CSV parity.
- A successful Spark/Glue job does not establish SSIS parity; the independent reference comparison remains mandatory. This version does not offer one-click post-deployment self-repair of already approved code. Do not re-run/deploy merely to change the UI status.

## Run

1. Unzip to a new folder (e.g. `D:\MigrationForgeV299`).
2. Open `ScenarioC\SSISGlueDemo.sln` in Visual Studio 2022; run `DemoWeb`.
3. Ensure the UI's AI diagnostics shows `2.9.9-source-derived-numeric-parity`.
4. Start a **new** portfolio for the unsupported-task test; upload the original `.dtsx` and its real support script/input as before. Generate AI, examine the newly proposed diff, approve and locally validate, then deploy ONLY if your data and code are correct.
5. Supply genuine SSIS reference CSVs when validating the completed run.

## Checks done here

- Python unit/integration test suite, including new source-derived and reference-derived rules.
- Python syntax compilation and ZIP integrity check.
- Not tested here: Windows Visual Studio 2022 compilation (`dotnet` unavailable), a real AWS Bedrock invocation, or your private Glue deployment and reference data.
