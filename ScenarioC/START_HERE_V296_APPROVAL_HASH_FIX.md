# Migration Forge v2.9.6 — Approved AI candidate hash fix

This is the existing single-button Migration Forge v2.9.5 solution with only the approved-candidate integrity handling corrected; no altered Scenario A/B conversion or deployment routines.

## Root cause fixed

Previous approval used `Path.write_text()` to save `candidate.py`. On Windows it may convert LF into CRLF, while `approvedCodeSha256` was generated from the original UTF-8 LF text. Deployment compared the raw file bytes and reported `Approved AI code hash mismatch` despite identical reviewed code. v2.9.6 writes exact reviewed UTF-8 bytes on new approvals.

For existing v2.9.5 sessions, the deployment verification may restore the exact approved UTF-8 bytes **only** when `candidate.py` is exactly the CRLF rendering of the saved approved proposal, and both the proposal hash and approved manifest hash agree. A small audit artifact `approval-normalization.json` records such a restoration. No code is regenerated, no hash is reapproved, and any other code change is blocked.

If the stored proposal changed after approval (for example a later Bedrock proposal overwrote it), this version deliberately refuses deployment. The user must review and approve the current candidate. It must not silently reapprove a new proposal.

## Run

1. Leave your existing verified A/B installation unchanged.
2. Extract to `D:\MigrationForgeV296` and open `D:\MigrationForgeV296\ScenarioC\SSISGlueDemo.sln` in Visual Studio 2022; launch DemoWeb.
3. Confirm sidebar v2.9.6 and stop older app instances on port 5297. Launch Visual Studio from the PowerShell session containing working Spark environment variables if required.
4. Resume the existing approved Scenario C session; do **not** click Generate AI again. Use AWS verification and Deploy packages with explicit approvals.
5. If approval evidence was preserved, previously approved code is reused; the original SCT warning remains auditable.

## Verification

225 Python tests + 4 subtests passed on Linux, including exact legacy-Windows-CRLF recovery, hash-preserving deployment, and deliberate tamper rejection. No live Windows Visual Studio build, Bedrock call, or AWS Glue deployment was performed here. Do not claim cloud success until the live job and output inspection complete.
