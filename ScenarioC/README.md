# Migration Forge v2.9.6 — Approved AI Glue deployment integration

**Start with `START_HERE_V295_AI_GLUE_DEPLOY.md`.** This release preserves the existing Scenario A/B lanes and enables a separately approved AWS Glue deployment lane for genuine SCT 25029 PowerShell Execute Process candidates that have passed local Spark checks. Live AWS deployment has **not** been executed in this environment; mock AWS integration tests are included.

---

# Migration Forge v2.8.3 — Preserve completed package results (2026-11-08)

Fixes a bulk workflow defect where a later AI-accept failure overwrote a package's prior successful Glue + independently baseline-matched CSV state with `ERROR_AI_ACCEPT`. The error is retained in history for audit, while authoritative saved Glue status and complete CSV validation evidence restore the visible `OUTPUTS_MATCH` state. A successful Glue run alone is NEVER treated as CSV parity.

Completed packages are skipped by earlier-stage operations (conversion, analysis, AI, AWS config, deployment and execution); no duplicate Glue run or Bedrock request is made. The browser likewise filters completed packages out of those actions. Fresh Scenario C stays separate from already-validated A and B.

Startup now shows the most recently saved migration for convenience, while **Start new migration from folder** ALWAYS creates an independent portfolio. Saved portfolios are not deleted.

**No live AWS execution was performed.** Test results are offline; runtime portfolio restoration should be checked on the user's Windows machine.

---

## v2.8.2 — Fresh migration isolation fix (2026-11-08)

**Why:** The v2.8.1 UI automatically restored the latest portfolio, and folder upload
appended new packages to that portfolio. That made a new A+B+C upload display old
A+B `OUTPUTS_MATCH` and Glue `SUCCEEDED` evidence. It was a UI/session lifecycle bug,
not a new AWS execution.

**New behavior:**
1. App launch shows a clean, empty workspace. Nothing is automatically resumed.
2. **Start new migration from folder** always creates a new independent portfolio,
   recursively discovers the selected `.dtsx` and attaches real supporting files.
3. **Resume previous migration** explicitly loads the most recent saved portfolio.
4. Old portfolio data remain on disk; new runs cannot inherit old per-package
   conversion, AI approval, deployment, output or validation state.
5. Existing cloud, SCT, repair and CSV validation functions are untouched.

**Expected test:** Select a folder with A, B, C and click Start new migration from
folder. The summary must show **3 uploaded, 0 prepared, 0 Glue succeeded,
0 CSV validated**, and all three package stages `UPLOADED` before conversion.
The previous A+B portfolio should still be recoverable via its saved portfolio ID.

**Verification:** 160 offline tests pass; JavaScript syntax checks pass. No live
Windows SCT/Glue run was performed for this UI change.

---

# Migration Forge v2.7 — One five-step workflow for one or many packages

The UI has a single multi-file upload in Step 1; no single/bulk mode switch, no separate bulk dashboard or duplicate workflows. The existing Python `engine/bulk.py` routes each package through the original v2.5 SCT, repair, Bedrock and Glue engine and preserves per-package results.

Steps: Upload packages → Convert all → Analyze all and request Bedrock fixes where needed → Deploy eligible packages → Run and baseline-validate CSV outputs.

The app never auto-approves AI patches: all exact diffs are shown together for one consolidated review confirmation, then each approved patch is independently revalidated by the existing backend. One deployment and one run consent apply to the selected portfolio, while blocked packages are isolated.

Limitations: this is orchestration, not a guarantee that every SSIS transformation is supported. SQL Server and RDS connectivity/mutations must be separately configured and SQL parity validation is not implemented. Real SCT Batch and AWS tests require the user's Windows/AWS environment.

# Migration Forge v2.6 — Bulk portfolio orchestration

**New:** Single package / Bulk portfolio mode. Multi-select up to 500 original `.dtsx` packages; genuine per-package AWS SCT, automated deterministic analysis, selective Bedrock repair proposals with exact per-package approval, deployment, real Glue execution, and S3 CSV baseline validation. Existing single-package functionality is retained unchanged. See `docs/V26_BULK_MIGRATION.md` for the workflow, dependency limitations and important security safeguards. **Not yet live Windows SCT/AWS bulk-tested.**

## v2.4 — Source-derived CSV type review (added)

Approved SCT-derived scripts can be reviewed and patched for source-provable CSV headers, numeric source types and Derived Column precision/scale, in a separate exact-diff approval step. This does not call Bedrock and does not create new transformation logic. See `docs/V24_SOURCE_DERIVED_CSV_TYPES.md`. Glue runtime parity remains unverified.

# Migration Forge v2.3 — Approved semantic repair revalidation fix

**Fixes the false post-approval failure reported by Scenario B**: approved Spark Merge Join insertion used to be checked against uncleaned raw SCT, even though review validated against the deterministically repaired working copy. The same candidate was therefore incorrectly rejected as "AI changed SCT statements" and its audit-only `25042` marker stayed flagged.

## Resume the already-approved Scenario B session (no repeat Bedrock request)

1. Extract this solution to a short folder, open `SSISGlueDemo.sln` and start `DemoWeb`.
2. Migration Forge stores sessions in `%USERPROFILE%\.ssis_glue_demo\sessions` by default, unless `SSIS_GLUE_DEMO_DATA` was set. Leave that folder in place. The application should restore the latest session automatically.
3. Open **AI repair**, leave the SQL Server adapter unchecked for the CSV package, and click **Analyze & repair** once. **If the saved session already includes a reviewed semantic patch, this action revalidates that same approved working copy rather than running SCT or Bedrock again.**
4. Expect `STATIC_REVIEW_COMPLETE` with `blockers: []` if no other defects are present. Download **Corrected scripts ZIP** and verify `REPAIR_PROVENANCE.txt` has an empty BLOCKERS section. If session provenance or the patch has been changed, the validator fails closed.
5. This is **offline static proof**, not confirmation of AWS Glue execution or SSIS/Glue data parity. Review the generated CSV schemas, numeric precision, and Spark SQL operations before spending money deploying.

## Technical fixes

- `engine/quickflow.py`: pins the **pre-AI deterministic working copy**, plus the raw SCT evidence hash and original `.dtsx` hash, as the basis for semantic proof. Reconstructs the exact one-line insertion byte-for-byte and rejects changes to original statements, comments, join type, source keys, or mappings. Keeps `25042` in the source comment for audit and suppresses that specific static finding only upon successful semantic validation.
- `engine/quickflow.py`: compatible recovery for existing v2.2 approved CSV sessions without the new pinned field; reconstructs the deterministic baseline from original SCT, but does not attempt unsafe adapter recovery.
- `engine/cli.py`: repeated Analyze & repair preserves and revalidates the *existing approved candidate* instead of re-running `construct` and losing approval. Any remaining blockers stay visible.
- `tests/test_v23_approved_semantic_baseline.py`: ten new tests, using actual Scenario B SCT-derived scripts and mocked Bedrock responses. Tests old session recovery, code tamper rejection, missing/extra unsupported-component handling, real ZIP provenance, and repeat analysis.

**Tests:** 118 Python tests passed. `node --check` passed. No .NET SDK, Windows SSDT, AWS SCT installation, or live Bedrock/Glue credentials available in this execution environment; those are not claimed as verified. Existing tests emit known `SyntaxWarning: invalid escape sequence` warnings from older fixtures.

---

# Migration Forge v2.1 — Single-assignment Bedrock Merge Join repair

**This is the updated Visual Studio 2022 solution, based on v1.9.1.**

## Scenario B quick path (reuse your existing session)
1. Extract this ZIP to a new directory and open `SSISGlueDemo.sln`.
2. Start `DemoWeb` in Visual Studio.
3. Open Step 3, **Analyze & repair** again in your existing session. It must now report **SCT unsupported component marker (25042)** and **Undefined SCT DataFrame receiver**.
4. Under Amazon Bedrock code repair, explicitly approve model charges and transmitting bounded SCT code **and original SSIS Merge Join metadata**. Click Generate one-line Merge Join proposal.
5. Inspect proposed diff. A valid proposal contains ONE Python assignment in JSON; the application, not the model, inserts it immediately before the missing frame’s first use. The exact diff must show one added line, zero removed lines. No original SCT statements may change.
6. Approve the exact diff and click **Approve exact patch & validate original SSIS join semantics**. Proceed only if the report's blockers are empty. Separately review the corrected scripts before approving actual Glue deployment and AWS charges.

An existing session must contain its uploaded **v2 `.dtsx`** as `source/original.dtsx`. The app extracts and hashes the original SSIS JoinType, key lineage, source roles and output InputColumnID lineage. A different package, extra joins, missing lineage, or mismatched SCT source variables fails closed. This solution does **not** manufacture a new Glue job or replace SSIS transformations with fixture-based Python.

## Critical verification boundaries
- **105 offline tests passed** including 20 tests against the user's actual SCT-generated scripts and fake Bedrock API responses.
- **Real Bedrock invocation, actual Windows AWS SCT conversion, Glue runtime and SSIS/Glue output parity are NOT verified by these tests.** Bedrock may return an empty proposal or a rejected patch.
- The validator addresses one isolated unsupported Merge Join. It does not certify other SCT business logic, numeric precision, headers/case, SQL function compatibility, or production readiness. The SCT output's `CAST((quantity * unitprice) AS decimal)` may not preserve the original SSIS `DT_NUMERIC(18,2)` precision/scale and should be reviewed before claiming parity.
- The model's output is **not deployed** until reviewed and approved. The existing quick deployment pathway also requires explicit approval of the corrected SCT code and AWS charges. Runtime data results must be verified.
- Protect your AWS profile and IAM role, and use a test S3 bucket.

Detailed change documentation: `docs/V21_SINGLE_ASSIGNMENT_BEDROCK_REPAIR.md`.

# Migration Forge v1.6 — simplified five-step SCT → Bedrock → Glue

**Windows / Visual Studio 2022 / ASP.NET Core .NET 8 / Python 3 / AWS SCT Batch / boto3**

## Quick start

1. Extract to a short path such as `D:\SFG16`. Install/verify .NET 8 SDK, Python 3, and AWS SCT Desktop with Batch runner (`RunSCTBatch.cmd`). Existing AWS CLI profile: `ssis-glue-poc`.
2. In PowerShell in the extracted folder, run `python -m pip install -r requirements.txt` (or `py -3 -m pip install -r requirements.txt`).
3. Open `SSISGlueDemo.sln` with Visual Studio 2022 and start `DemoWeb`, or run `Start_Demo.cmd` if `dotnet` is on PATH. Open `http://127.0.0.1:5297`.
4. **Upload:** Select `ssis-packages\A_Employees_Active_Bonus_FIXED.dtsx` for the controlled sample, plus `fixtures\input\Employees.csv` (optional: a same-named bundled fixture is detected automatically). This creates a new session. Alternatively upload another genuine `.dtsx` and all required CSVs.
5. **Convert:** Click **Convert with AWS SCT**. This reuses the earlier verified SCT Batch-discovery and `.scts` generation engine. Genuine SCT GUI ZIP import is an honest fallback if the installed CLI fails.
6. **AI repair:** Click **Analyze & repair**. This inventories genuine SCT modules by dynamically derived module names, removes unused helper imports, rewrites recognizable static CSV paths to S3, dynamically identifies a single coordinator, and generates `sct_glue_entry.py` plus a ZIP of generated modules. Download **Corrected scripts ZIP**. If blockers remain, you can opt in to send bounded Python fragments to Nova Lite for a *real proposed code patch*, see its unified diff and explicitly approve; syntax/AST/security checks rerun. AI may return zero patches; this is not a model failure.
7. **Deploy:** Use AWS profile `ssis-glue-poc`, region `ap-southeast-2`, S3 prefix `s3://ssis-glue-poc-bucket/ssis-migrations` (edit to your actual configured prefix) and existing Glue IAM role. Click **Verify AWS connection**, approve the actual SCT-derived source and charges, then **Deploy SCT scripts to Glue**. Unknown connectors and missing input CSVs block deployment.
8. **Execute:** Approve charges, click **Start Glue job** and **Refresh actual status**. Only real Glue API `SUCCEEDED` counts as execution success. It lists actual S3 output keys; there is **no claimed SSIS-vs-Glue parity verification** in this quick demo.

## What this update changed

- Five-step front end, no mandatory local PySpark or Windows `dtexec` gates.
- Existing SCT Batch conversion flow and original SCT-provenance storage retained.
- Generic module-name extraction, generated coordinator detection, CSV S3 staging, Python ZIP and Glue launcher instead of filenames like `ScenarioA`, `_FIXED`, or fixed code hashes.
- Real boto3 Bedrock `converse` request for full-module Python patch proposals **only when static blockers are found**, with cost/code transmission consent, diff review, syntax/AST and security checks, and user approval. Patches are not silently executed.
- Generic real AWS Glue job deployment of the **SCT-generated** modules with pinned hashes and no independent reference-job fallback. Genuine CloudWatch error/status and actual output S3 listing.
- Session files persist under `%USERPROFILE%\.ssis_glue_demo\sessions\<id>` by default. Previous sessions remain untouched; the new UI can restore the latest one.

## Honest limitations / important prerequisites

- A **generic workflow is not a universal migration converter**. The quick automatic runtime path currently recognizes static CSV reads/writes and a *single unambiguous* SCT coordinator. JDBC, Excel, unresolved external modules, multiple coordinators, unknown file paths, destructive SQL and complex orchestration are explicit blockers until supported mappings/semantics exist. This is intentional; Bedrock must not invent DB credentials or destructive operations.
- There is no local PySpark execution gate, as requested. Static checks cannot prove correct ETL behavior. Real Glue execution itself provides the runtime result; users must separately verify business parity if required.
- Bedrock code review is **opt-in, billable and may transmit approved snippets of proprietary generated code**. A secret detection check is applied, but only use non-confidential sample packages unless you have reviewed what is sent. Model patches may be rejected, incomplete or wrong. Patch approval is required.
- Windows SSIS, actual AWS SCT conversion of the fixed `.dtsx`, live Bedrock inference, .NET compilation and live AWS Glue execution **were not run in this environment**. They must be tested on your Windows/AWS setup. Python regression checks and front-end JavaScript syntax did run (see `docs/V16_TEST_EVIDENCE.md`).
- AWS Glue `G.1X` x2 workers can incur usage charges; keep the demo isolated. Do not run destructive jobs against live data.

## 5-minute demo narrative

1. *Upload* a genuine package and show the generated session ID.
2. *Convert* using actual SCT CLI; show genuine original Python ZIP/log.
3. *Analyze & repair* to show deterministic repairs, detected CSV mappings and generated entry point. When there are unresolved supported defects, run Bedrock only with explicit cost and transmission approvals; show code diff. When no defects remain, show `NO_STATIC_DEFECTS_TO_REPAIR`, not fabricated AI code changes.
4. *Deploy* reviewed SCT-derived code to real Glue, noting the actual job name and S3 script.
5. *Execute* and refresh the real Glue run state; on success show S3 output objects. If it fails, show the real error without claiming success.

## Tests

From the root: `set PYTHONPATH=engine` then `python -m pytest -q tests` (CMD) or `$env:PYTHONPATH="engine"; python -m pytest -q tests` (PowerShell).

See `docs/V16_TEST_EVIDENCE.md` for evidence and limitations. This release **does not** require hand-authoring `.scts` or running local PySpark before deployment.

## v1.7 — Real Scenario B SCT syntax repair and opt-in CSV lookup demonstration

**The SQL Server question:** Migration Forge's simplified pipeline did **not** have a verified live SQL Server JDBC connection. Older Migration Studio experiments had JDBC connection plans, but the actual Scenario B SCT output includes `specify driver`, `specify connection` and SQL Server `DELETE`/`BULK INSERT`/`UPDATE`. Glue cannot reach a laptop SQL Server instance merely by specifying a JDBC URL; it also needs network routing/firewall/VPC access and secret handling. This release does not claim to implement that connection.

The main 5-step UI now supports:

- Generic, token-safe syntax corrections such as SCT's invalid `frame.'column'`. They are applied to a reviewed working copy of the *actual* SCT code and work without dependence on filename.
- Bedrock *scoped patches* can be reviewed and accepted for individual syntax fixes even when unrelated external-connection blockers remain. The overall Glue deployment remains blocked until all blockers are gone; a model does not authorize database mutations.
- **Explicit, opt-in CSV lookup demo substitution** (checkbox in Step 3). This supports ONLY the recognized Orders/Customers lookup topology from the original Scenario B SCT output. It drops the original `DemoForgeCustomers` SQL Server staging task from the working copy, reads `Customers.csv` staged from S3 instead, correctly routes matched and unmatched orders, calculates decimal totals, writes two isolated outputs, and records every such behavior change in the corrected ZIP. **This is NOT a live SQL Server migration**, and you must describe it as a CSV-substituted demo.
- If the adapter does not recognize all expected patterns, the application refuses the substitution; it does not attempt unrestricted AST/model-based rewriting.

### Fast Scenario B demo using your already converted SCT artifacts

1. Stop the previous Visual Studio app and extract this v1.7 solution to a short path (e.g. `D:\SFG17`). Do **not** delete your saved user sessions under `%USERPROFILE%\.ssis_glue_demo`.
2. Start `SSISGlueDemo.sln`; the app normally recovers your latest saved session. If it restores the Scenario B session with `BLOCKED_PENDING_REPAIR`, keep that session; **no need to rerun SCT**.
3. Go to **AI repair**. If your goal is just to show automatic syntax repair, leave the CSV lookup checkbox unchecked and click **Analyze & repair**; note that the real line-24 syntax defect is fixed, while database connection blockers remain.
4. To exercise the **CSV-only lookup** demo instead, explicitly check **'SQL Server lookup → staged Customers.csv'**, then click **Analyze & repair**. Review the `edits` and `blockers`. The corrected-scripts ZIP contains `REPAIR_PROVENANCE.txt` and `SCT_BEFORE_AFTER.diff`. Do not describe this as a real SQL Server connection.
5. Both `Orders.csv` and `Customers.csv` are included under `fixtures/input/`. The cloud deployment uses these sample fixtures if they were not uploaded during session creation. Verify the inputs are your intended demo data.
6. Only if blockers are empty: verify AWS configuration, approve real costs and reviewed modifications, deploy the SCT-derived CSV-substituted candidate, start Glue and review the actual S3 output. The expected sample has 3 valid orders and 2 rejected orders. **No live Glue run has been completed for Scenario B in this release environment.**

**Security:** Do not approve model-generated modifications that invent JDBC credentials, execute original `DELETE`/`BULK INSERT`/`UPDATE`, or alter source SQL without explicit database change review. For production JDBC connectivity, supply an actual approved private network path and Secrets Manager connection mapping first.

## v1.8 — Preserve original Scenario B SQL Server operations (not CSV substitution)

**Start with `docs/V18_SQLSERVER_SCENARIO_B.md`.** v1.8 integrates the older Studio's reviewed JDBC configuration ideas (Glue VPC connection + Secrets Manager SQL-auth secret + optional JDBC jar) into the simplified 5-step path. It adds a narrowly recognized SQL Server staging adapter for the actual Scenario B SCT output. The CSV-only lookup substitution is removed from the main UI; any old CSV-substituted candidate is blocked from the v1.8 deployment path. **Real SQL Server network reachability is required**, and the project cannot manufacture a route from AWS Glue to your laptop's `BG4NBL1097\SQLSERVER01`.

The adapter repairs actual SCT errors but preserves the SQL-backed data source: stage the original Customers.csv to the SQL Server `dbo.DemoForgeCustomers` test table using JDBC transactional CREATE/DELETE/INSERT/RTRIM, then read that same table via genuine Spark JDBC for the orders lookup, calculate totals, and write valid/rejected CSV outputs. The original BULK INSERT Windows-local-file transport must be translated; it cannot run unchanged on AWS Glue. The adapter is explicitly limited to the reviewed sample and is **not a general equivalent converter for arbitrary destructive SQL**. Requires approval before test-database mutation. Live execution and true SSIS parity remain untested from this environment.

## v1.9 — New original CSV-to-CSV Scenario B (no SQL Server)

**Use `ssis-packages/B_CSV_Customer_Order_Join.dtsx`**, not the existing SQL-backed `B_Orders_Customer_Lookup.dtsx`. The new original package contains two CSV sources, left outer Merge Join, conditional matched/reject routing, original order-total calculation, and CSV destinations. The old SQL Server package is retained as a separate original.

Extract the complete ZIP to **`D:\SFG19`** because the original package's Flat File connections reference those paths. Upload **both** `fixtures/input/Orders.csv` and `fixtures/input/Customers.csv` alongside the new `.dtsx`; leave the SQL Server preservation option unchecked. Convert with the **real** AWS SCT CLI, then analyze and deploy only its actual generated code. No substitute Glue lookup job is included.

See `docs/V19_CSV_ORIGINAL_SCENARIO_B.md` for important sorting assumptions, validation evidence and limitations. The new `.dtsx` has **not** been certified by Windows SSDT or actually converted by SCT in this environment; do not claim otherwise.

### v1.9.1 incomplete conversion diagnostic

See `docs/V191_SCT_INCOMPLETE_CONVERSION.md`. An empty SCT-generated data flow
body now raises a specific blocking message instead of `found 0 coordinators`.
This protects faithful code provenance; it does not fix source SSIS metadata.


## v2.2 generic workflow clarification

The user-facing AI action is now **Generate targeted AI repair proposal**, not a Merge Join button.
The analysis response includes a `repairPlan` describing detected strategies and whether
manual review is necessary. The internal Merge Join strategy remains specifically
source-constrained; **this does not mean arbitrary SSIS components can be translated
automatically**. No AI call is required when analysis finds no defects.
Unverified transformations remain blocked; all AI changes remain review-only.

## v2.5 additions

- Safe, uniquely source-proven type/precision patches automatically execute during SCT analysis and after reviewed AI repairs; no separate numeric-type approval screen. Source hashes and repair diffs remain auditable. One final deployment approval remains, with an additional explicit gate only for dangerous SQL mutations.
- Step 2 hides logs/output/assessment links during conversion. On completion it displays genuine SCT Batch conversion logs, original output and, **only when SCT generated them**, real SCT PDF/CSV assessments. The PDF is viewable in browser; a ZIP contains actual exported reports.
- Step 5 adds **Download from S3 & validate CSV** after a successful real Glue run, comparing each declared CSV output folder against a user-supplied trusted reference. Nothing is passed just because Glue reported `SUCCEEDED`.
- SQL table validation is architected but **not claimed implemented**; see `docs/V25_GENERIC_VALIDATION_AND_SCT_REPORTS.md` for the proposed read-only validator strategy and limits.
- Existing deployment/run workflows and SQL staging adapter remain. Never claim a single CSV fixture comparison proves a SQL-backed package or independent SSIS-to-Glue parity.

## v2.8 — Folder-based source discovery (recommended for bulk upload)

Step 1 has one folder picker instead of separate `.dtsx` and input CSV uploads. Select a parent folder containing SSIS packages and the actual supporting input files, including subdirectories, then click **Discover & upload folder**. The application discovers all `.dtsx` files, extracts literal Flat File Source references from the original XML, matches each CSV against the selected folder, and attaches the real bytes to each existing isolated package session. The current 5-step conversion/repair/approval/Glue/validation pipeline is unchanged. Reselecting a source folder resumes identical package sessions and can resolve previously missing inputs without repeating SCT or Bedrock. See `docs/V28_FOLDER_SOURCE_DISCOVERY.md` for matching precedence, security limits and supported source formats.

## v2.8.1 — Bulk Glue polling hotfix

Fixes a run-status deadlock in v2.8: `cloud_run` persists the submitted AWS
job identity to `quick/run.json`, but the portfolio status reader previously
looked only at `quick/status.json` (which does not exist until polling).
Consequently, both packages could remain `RUN_SUBMITTED` while Refresh skipped
both jobs. Portfolio status now loads `run.json`, then applies `status.json`
only when the job name and run ID match. Existing submitted runs can be polled
without triggering another Glue run. The run action also blocks duplicates if
an earlier run/status file is already present.

To resume: extract into a separate folder, run the same app with the *same*
`SSIS_GLUE_DEMO_DATA` location (default: `%USERPROFILE%\\.ssis_glue_demo`),
open Step 5, press **Refresh run statuses**. **Do not press Run deployed packages
again** for previously submitted jobs. No new SCT conversion or Bedrock repair
is necessary. The previously submitted runs and actual AWS state are not
accessible from offline tests, so the user must poll AWS to confirm success.

Offline regression suite: 157 passed. Python syntax and JavaScript syntax
checked. The tests simulate persisted AWS run records; they do not issue Glue
API calls.

## v2.8.4 - Visible package details and analyze status

This is a **UI-only** update based on v2.8.3. Clicking Details expands an inline row immediately under the package, showing analysis state, blockers, the last reported error, and available SCT/AI artifacts. Clicking again collapses it. The expanded row stays open across status refreshes. Analyze & repair now explains when no operation ran because a package was already analyzed or completed. It does not automatically rerun completed analysis, SCT, Bedrock, or Glue.

The existing application state directory is unchanged; no migration or deployment data are reset. Live Windows browser verification remains outstanding.


See `START_HERE_V296_APPROVAL_HASH_FIX.md` for the Windows SHA-256 integrity correction and restart instructions.
