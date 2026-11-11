# Migration Forge v2.9.8 — Generic AI Glue output validation

Based on v2.9.7. Fixes the empty `{matched: [], unverified: []}` response when a real SCT-25029/Bedrock repair generated Glue CSV output but its results were recorded under `cloudOutputs` rather than ordinary `outputs`.

## Resume the existing run; do not reconvert or redeploy

1. Extract this release to a different short folder, for example `D:\MigrationForgeV298`.
2. Stop the previous server. Open `ScenarioC/SSISGlueDemo.sln` with Visual Studio 2022 and run the `DemoWeb` startup project. Confirm the UI says v2.9.8.
3. Choose **Resume previous migration**, refresh the package. It should remain `GLUE_OUTPUT_GENERATED`, with its real `cloudOutputs` discovered from the saved inspected Glue report.
4. In **Execute & validate**, select a CSV produced independently by the *original* SSIS execution. For Scenario C, use the `ActiveEmployees.csv` actually produced when you ran the original Execute Process Task (not the Glue output or bundled expected fixture). Do not rename the actual Glue part files.
5. Click the **existing** Validate all matching CSV outputs button. No new button, new Bedrock call, conversion or Glue run is needed.
6. `MATCH` reflects real S3 CSV versus the user-supplied baseline only; a trusted original-SSIS run is needed to claim SSIS parity. Output row/column differences return DATA_MISMATCH / SCHEMA_MISMATCH. The result is persisted and tied to the exact approved code hash, job, run ID and output S3 prefix.

## Generic matching

- For a unique output name, supply `OutputName.csv`; for duplicate output names in a portfolio use `PackageStem__OutputName.csv`.
- The UI reads the output names from the inspected cloud report, not from an assumed Scenario C filename or sample fixture.
- The backend requires the approved hash and a real successful Glue run, lists only declared S3 `part-*.csv` objects under that job's pinned output prefix, and reuses the existing content-based CSV comparator (column name mapping, row order independence, decimal normalization).
- No reference output is required before AI generation or Glue deployment.
- A missing reference returns UNVERIFIED, never false MATCH.

## Verification

- Offline Python suite: 234 passed, 4 subtests passed in this environment.
- JS syntax and ZIP integrity checked.
- Not verified here: Windows VS2022 build, access to the user's local portfolio, live AWS execution, or actual original SSIS parity.
- Do not overwrite the known-good v2.8.5 A/B installation. The original A/B deployment and validation branches remain unchanged.
