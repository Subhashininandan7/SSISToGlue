# Migration Forge v2.9.5 — Reviewed Bedrock repair → AWS Glue (Visual Studio 2022)

## Scope

This release integrates the **existing** Deployment / Execution / Poll controls with a special adapter for the **exact reviewed and locally tested** PySpark replacement of a real AWS SCT **25029 Microsoft.ExecuteProcess** task. The implementation remains source-driven: no package-specific employee names, columns, input filenames, or output filenames are hardcoded in the Glue adapter. It uses the manifest of uploaded CSV input evidence, the approved candidate bytes and the observed CSV-output contract.

This is an **additional constrained adapter**. It does not guarantee arbitrary unsupported SSIS components, multi-task packages, proprietary executables or side effects can be migrated. Missing external source or absent input evidence blocks deployment rather than fabricating data.

## Existing Scenario C session — no need to regenerate Bedrock code

1. **Keep your working A/B installation intact.** Extract this ZIP to `D:\MigrationForgeV295` (new directory).
2. From a PowerShell session where `aws sts get-caller-identity --profile ssis-glue-poc` succeeds, configure Spark temp folders for inherited Visual Studio environment if needed, then open `D:\MigrationForgeV295\ScenarioC\SSISGlueDemo.sln` in Visual Studio 2022 and start `DemoWeb` (F5). The app runs at `http://127.0.0.1:5297` and its sidebar should show **v2.9.5**. Stop earlier instances first. The same `%USERPROFILE%\.ssis_glue_demo` sessions are reused unless you previously set `SSIS_GLUE_DEMO_DATA` to a custom value.
3. Resume your Scenario C portfolio. It should already show `LOCAL_OUTPUT_GENERATED` and the previously approved Bedrock proposal. **Do not reupload or regenerate** unless you intentionally create a new migration.
4. Under AWS configuration, verify **profile `ssis-glue-poc`**, **region `ap-southeast-2`**, **your existing S3 prefix** (must be `s3://bucket/non-empty-prefix`) and **your existing Glue IAM role**. The role needs S3 access to the staged objects, AWS Glue execution and the normal Glue logging permissions. Your local profile must permit STS, S3 uploads/listing/reads, and Glue create/start/get requests.
5. Check existing **deployment / AWS charges approval**, click **Deploy packages**. For an older v2.9.4 session lacking persistent validation evidence, Migration Forge reruns the **already approved candidate locally once** to re-establish a hash-bound validation record. It does **not** call Bedrock again. Only after this and the AWS identity gate succeeds will the tool stage the original uploaded CSV inputs, exact candidate Python ZIP and Glue entry-point to S3 and create a unique `ssis-ai-<sessionId>` Glue job. It will never overwrite an existing job.
6. Go to **Execute & validate**, approve Glue charges, click **Run**, then **Check status / Refresh** to poll. Deployment and job run are separate steps and require separate consent. Run is idempotency-gated: existing run IDs cannot be started twice.
7. If the job succeeds, the application discovers the **actual** S3 CSV part files, reads their headers and counts rows, checks their output names/headers/counts against the local execution when available, and saves an output report. In Package Results you will see the S3 output location, **Glue output report**, and **Download Glue CSV output** for small bounded outputs (20MB combined). Cloud artifacts are stored under `<configured S3 prefix>/<sessionId>/approved-ai/` and do not modify old A/B data.

## Statuses are intentionally different

- `DEPLOYED`: Real Glue CreateJob succeeded; nothing has executed.
- `RUN_SUBMITTED`: Glue StartJobRun returned a real JobRunId; not necessarily finished.
- `GLUE_OUTPUT_GENERATED`: Glue reports SUCCEEDED **and** actual CSV files were found, inspected and checked against the local output contract.
- `GLUE_OUTPUT_CHECK_FAILED`: Glue itself may have succeeded but actual CSV output was absent or mismatched.
- `GLUE_FAILED`: Glue job failed. The report contains a bounded CloudWatch error excerpt where available.
- `OUTPUTS_MATCH` is reserved for independent original-SSIS parity evidence. **Glue success and local execution are not SSIS parity.**

## Safety and verification

- Only exact SHA-256-matching approved code, unchanged original task metadata/SCT/source evidence, staged input hashes, and the **post-approval** local execution proof qualify for cloud deployment.
- Glue wrapper imports `ai_candidate` from the pinned ZIP through `--extra-py-files` and invokes `transform(spark, INPUT_PREFIX, OUTPUT_PREFIX)` using S3 URIs. No Bedrock calls or code regeneration at deploy time.
- All source packages, SCT warnings (including 25029), proposal diffs and approval evidence remain in session audit state. A repaired historical warning is not erased.
- Generated Spark code is **not sandboxed by Python AST checks**. Only run in an isolated, tightly permissioned development account/job. Do not use production data or credentials.
- This environment cannot run the user's Windows/SSDT, AWS account or local PySpark. Offline tests use fake AWS clients; they do not establish that the Glue job will succeed in your cloud. Before claiming full success, perform a real Glue run and inspect the saved output report.

## Verification

Run `python -m pytest -q` from the `ScenarioC` directory. A test file `tests/test_v295_process_glue.py` exercises denied deployment, exact hash, missing local proof, isolated AWS job creation, idempotent run, S3 outputs, absent output, contract mismatch, and the bulk single-page Deploy → Run → Poll journey using mock AWS clients. The original A/B tests are retained.
