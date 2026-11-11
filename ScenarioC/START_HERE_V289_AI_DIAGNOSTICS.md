# Migration Forge v2.8.9 candidate — AI skip diagnostics and routing

This supersedes v2.8.8. The existing **Generate AI fixes where needed** button now presents packages with SCT conversion evidence to the backend even if the quick-analysis coordinator could not be established. Server-side evidence checks determine whether the genuine 25029 Execute Process remediation lane is allowed. A package lacking SCT artifacts produces an explicit actionable error, not a silent skip. Existing validated A/B packages are not reprocessed.

**Important:** This is built from the source supplied earlier, not a verified checkout of the locally installed v2.8.5 solution. Deploy to a separate folder.

## Steps
1. Stop ALL old instances of DemoWeb / Migration Forge on localhost:5297. Extract into a new folder, e.g. `D:\MigrationForgeV289`.
2. Open `ScenarioC\SSISGlueDemo.sln`, start DemoWeb, and verify the left sidebar says **v2.8.9**. If it does not, you are still running old static assets. Use Ctrl+F5 to reload.
3. Create a new migration and select a folder containing `C_Unsupported_Execute_Process_AI_Demo.dtsx`, `transform.ps1` (as referenced by original SSIS), and available CSV source inputs. The UI stages external script files as local evidence during folder selection. You must use the folder upload, not a bare `.dtsx` upload.
4. Run AWS SCT conversion. Confirm the genuine SCT output ZIP is recorded, including 25029. If Analyze reports no coordinator, proceed to Generate AI fixes without fabricating one.
5. Approve charges and transmission. Click **Generate AI fixes where needed**. Inspect `issues`, `diagnostics`, and `appVersion` fields. A real Bedrock response will provide a review-only proposal. Do not deploy generated code without validation and human approval.

### Interpretation
- `completed: 0, skipped: [name], diagnostics: ...`: the displayed diagnostics now explains why the **browser** skipped it. If `appVersion` is absent, your browser/Visual Studio is serving an older build.
- `issues: ["... No original SCT conversion ZIP ..."]`: re-convert in this portfolio before requesting AI.
- `issues: ["... sidecar ..."]`: re-upload the whole folder with `transform.ps1`.
- `issues: ["... Bedrock ..."]`: check account/model permissions and region; this is no longer an eligibility skip.

Test evidence: Python regression `189 passed` and `4 subtests passed`. JavaScript syntax check passed. This environment did not perform a Windows VS2022 build, live Bedrock call, or AWS Glue run. Unsupported Execute Process proposals remain review/local Spark test only; there is no verified automatic Glue deployment adapter.
