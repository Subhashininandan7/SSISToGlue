# Migration Forge v2.9.0 candidate — single AI generation action

This build is based on the available v2.8.9 candidate, not a verified copy of the user's locally installed v2.8.5. Keep the original working A/B build unchanged.

## UI behavior

- The **Generate AI fixes where needed** button remains the sole AI proposal trigger on the existing five-step workflow.
- The extra **Validate approved unsupported-task repair locally** button was removed.
- Review proposed diffs, check approval, then click **Apply approved fixes** (required human approval, not a second Generate AI trigger).
- For eligible SCT warning 25029 Execute Process replacements, the same approval operation now automatically invokes the pre-existing local Spark validator. The result reports `LOCAL_OUTPUT_GENERATED` or `LOCAL_PARITY_MATCH` (when independent reference evidence was supplied), or displays a separate validation error.
- Missing PySpark/runtime prerequisites are reported as validation failure; patches must **never** be silently deployed.
- Standard A/B repair review behavior and deployment protection are unchanged.
- No pre-existing output CSV is required to generate AI proposals; actual output can be generated during local validation.

## Usage

1. Extract to a *new* short directory; do not overwrite the working A/B installation.
2. Stop any older DemoWeb instance and run `ScenarioC/SSISGlueDemo.sln` in VS2022. Hard-refresh the browser; sidebar should show v2.9.0.
3. Upload the folder with `.dtsx`, the relevant external `.ps1` and source CSV, run genuine SCT conversion, Analyze & repair and Generate AI fixes.
4. Review the Bedrock diff. Only after explicit approval, select **Apply approved fixes**, which automatically attempts the local test for eligible unsupported-task repairs.

## Honest boundaries

Automated tests do not establish successful live Bedrock invocation, Windows VS compilation, or AWS Glue execution. The SCT 25029 unsupported-task lane is review/local-test only and cannot auto-deploy to AWS Glue. The code does not claim generic arbitrary-component remediation.
