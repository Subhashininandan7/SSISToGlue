# Migration Forge v2.9.7 — Preserve approved AI repair and recover deployment eligibility

## What this version fixes

- An unsuccessful repeated Bedrock `ai-propose` call no longer destroys the deployment stage of a genuinely approved and locally verified unsupported-task candidate.
- Portfolio status can recover `LOCAL_OUTPUT_GENERATED` from existing on-disk evidence **only after** verifying proposal/code SHA-256, original SSIS/SCT/script hashes, approved inputs, and independent local-validation evidence.
- Clicking Generate AI fixes again on an approved valid candidate reuses the approved artifact and does not call Bedrock or rewrite the candidate.
- Re-analysis cannot overwrite an approved task candidate or silently swap evidence. Changed original evidence requires a new migration.
- Deploy packages sends a detected unsupported-task session to the backend even if the UI stage is `ERROR_AI_PROPOSE`: the backend either verifies the approved candidate or returns a specific error. It no longer quietly skips it. AWS verification must succeed before deployment is attempted.
- Successful Scenario A/B paths and human approval/hash checks remain unchanged.

## Exact steps to run

1. Keep the working A/B solution untouched. Extract this ZIP to `D:\MigrationForgeV297`.
2. Stop the old app running on port 5297. Open `D:\MigrationForgeV297\ScenarioC\SSISGlueDemo.sln` in Visual Studio 2022 with the .NET 8 SDK. Start `DemoWeb`. Use Ctrl+F5 in the browser. Check sidebar **v2.9.7**.
3. This build reads the existing session store under `%USERPROFILE%\.ssis_glue_demo` by default (or `SSIS_GLUE_DEMO_DATA`, if set). Use the same Windows user and environment setting as the previous installation to resume an approved session.
4. Click **Resume previous migration**, then **Refresh**. If the package returns to `LOCAL_OUTPUT_GENERATED`, keep the existing approved code; do NOT regenerate AI.
5. Set AWS profile, region, S3 artifact prefix and role. Approve AWS charges and click **Deploy packages**. Inspect both `aws` and `deploy` results. Only if deployment succeeds use **Run deployed packages** then **Refresh run statuses**.
6. If the application instead reports that the approved artifacts cannot be verified, do not bypass SHA-256 checks. The old approved session data may have been overwritten or changed; review and approve a new candidate in a separate session.

## Important boundaries

- Only eligible approved SCT-25029/PowerShell tasks use this new recovery behavior; unsupported arbitrary SSIS components do not become automatically convertible.
- Existing approved artifacts must still be physically present in the same session store; extracting a new ZIP does not copy private run/session data.
- Python tests and JS syntax validation were run offline; this environment does not include the Windows SSIS/SCT stack, live Bedrock/Glue access, or the .NET SDK. No live cloud deployment success is claimed.
- Spark candidate execution in a local subprocess is not a secure sandbox for untrusted code.
