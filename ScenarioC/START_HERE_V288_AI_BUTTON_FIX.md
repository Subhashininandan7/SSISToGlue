# Migration Forge v2.8.8 candidate — AI button skips SCT 25029

## Corrected behavior
The existing **Generate AI fixes where needed** button now sends coordinator-free real SCT output to the backend rather than silently skipping it. The backend only uses the new lane if the original SCT ZIP includes the actual **25029 Microsoft.ExecuteProcess** warning. It validates original SSIS Execute Process metadata and requires the exact referenced `.ps1` before invoking Bedrock. Normal A/B code fixes continue through the original `quick_ai` branch.

No expected output CSV is needed for a Bedrock proposal. An optional baseline can be used for parity later. No automatic AWS Glue deployment is claimed for the unsupported-task adapter.

## Windows procedure
1. **Keep the working A/B v2.8.5 folder untouched.** Extract this candidate to a new short folder such as `D:\MigrationForgeV288`.
2. Close any other Migration Forge process using port 5297. Open `ScenarioC\SSISGlueDemo.sln` in Visual Studio 2022 and launch `DemoWeb`.
3. Use **Start new migration**. Select a folder containing `C_Unsupported_Execute_Process_AI_Demo.dtsx`, the referenced `transform.ps1`, and optionally `Employees.csv`. The script filename must match the original SSIS task metadata. Avoid relying on a previous portfolio which may not have staged sidecar files.
4. Run real AWS SCT conversion. The original SCT output must include `25029 Microsoft.ExecuteProcess`.
5. Click **Analyze** (if normal coordinator proof fails, the revised backend also recognizes this under the AI button), approve Bedrock charges and transmission, and click the **existing Generate AI fixes where needed** button. Review the returned AI proposal diff before approval.
6. If there is still a problem, view the `issues` array, not just `skipped`. A missing sidecar now yields an explicit issue instead of silent filtering. Do not force a fabricated coordinator into the SCT output.

## Evidence and limitations
- Offline regression: `python -m pytest -q` — **187 passed** and four parametrized subtests passed; nonfatal SyntaxWarning messages remain from old SCT fixture strings.
- JavaScript syntax check: `node --check DemoWeb/wwwroot/unified.js` — success.
- Live Visual Studio build, AWS Bedrock network invocation, and Glue execution: **not executed in this environment**.
- The supplied sources are a previously provided Migration Forge snapshot, not a verified checkout of your installed v2.8.5. Treat as an integration candidate.
- This is a narrowly validated repair lane for single static `.ps1` Execute Process tasks with real SCT 25029 evidence; not arbitrary unsupported SSIS components.
