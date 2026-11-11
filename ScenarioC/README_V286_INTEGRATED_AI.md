# Migration Forge v2.8.6 — One-button integrated Bedrock remediation (preview)

## What changed

This release uses the existing **five-step unified workflow**, with the existing
**Generate AI fixes where needed** and **Apply approved fixes** buttons. No
secondary UI page is required.

- Regular supported SSIS packages keep the existing SCT, deterministic remediation,
  Glue deployment, and CSV validation path.
- When true AWS SCT conversion of a single `Microsoft.ExecuteProcess` package
  produces warning **25029** and no valid coordinator, Analyze now recognizes
  a separate *review-only* AI eligibility path instead of silently skipping.
- The selected upload folder must contain the original `.dtsx`, its referenced
  static `.ps1`, a CSV input, and an independent baseline CSV. Baseline files
  may be named `Expected_Name.csv` or `Name_SSIS.csv`; they are mapped to
  `Name.csv` for local parity tests. These are file-naming conventions, not
  independent proof that SSIS was run. Only supply actual SSIS outputs for
  SSIS-to-Glue equivalence claims.
- Original .dtsx metadata, authentic SCT warning and generated stub,
  selected PowerShell source, and CSV **header schemas** are supplied to Bedrock
  only after existing charge/data-transmission approvals.
- The generated PySpark is reviewed as a code diff, pinned by hash, and requires
  the existing **Apply approved fixes** action.
- After **Apply approved fixes**, local validation runs automatically in the same Analyze
  & repair step to run local PySpark comparison against reference CSVs.

## Usage

1. Extract to a new folder, e.g. `D:\\MigrationForgeV286`. Preserve the old v2.8.5 folder and its `%USERPROFILE%\\.ssis_glue_demo` data.
2. Open `SSISGlueDemo.sln` in Visual Studio 2022; launch `DemoWeb`.
3. Select a folder containing the `.dtsx`, its static `.ps1`, input CSV and original SSIS reference CSV. Start a **new** portfolio for this test.
4. Convert with genuine AWS SCT. If conversion was completed previously in another session, the normal UI does not provide a bulk conversion ZIP-import action.
5. Click **Analyze**. The unsupported task should report `UNSUPPORTED_TASK_AI_ELIGIBLE` and `REPAIR_BLOCKED` with an explicit 25029 blocker.
6. Check Bedrock charges and screened source-transmission approvals. Click the **existing Generate AI fixes where needed** button. A real API call requires AWS profile/region and model access.
7. Review the exact Bedrock diff, approve and apply it. Status becomes `AI_APPROVED_PENDING_LOCAL_PARITY`.
8. After **Apply approved fixes**, local validation runs automatically; success is `LOCAL_PARITY_MATCH` against the supplied input/baseline only.

## Scope and safety

Only **one static PowerShell `-File` Execute Process Task with a genuine SCT 25029 warning** is currently supported by the new review adapter. Other unsupported components, multi-task dependency graphs, dynamic paths, absent source code, and operations with external side effects need further explicit adapters or manual review. No automatic generic C#/Script Task conversion is promised.

**Glue deployment for the new 25029 adapter remains blocked**, even if local parity passes. A dedicated tested Glue packaging/deployment adapter is required. This is *not yet an end-to-end cloud remediation release*. A/B supported jobs use the original deployment code without change. Model-generated code is executed only in a local test subprocess, which is not a secure sandbox for hostile code; use a disposable controlled developer machine and reviewed code.

## Verification

- Python test suite executed locally: see `TEST_RESULTS_V286.txt`.
- No live Bedrock call, Windows Visual Studio build, AWS SCT invocation, local PySpark execution, or Glue deployment executed in this environment. The integration tests mock the Bedrock call to verify routing without claiming a real call.
- Changes were applied to the provided `ScenarioC.zip` source and prior standalone extension, **not a confirmed identical checkout of installed v2.8.5**. Treat this as a preview to compare before adopting.
