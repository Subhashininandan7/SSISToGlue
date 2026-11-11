# Migration Forge v3.0.4: Bedrock model catalog and diagnostics

Open `FinalDemo/ScenarioC/SSISGlueDemo.sln` directly in Visual Studio 2022 and run DemoWeb.

## New behavior
- AWS Settings > Refresh models for region queries the selected AWS CLI profile and region via **read-only** `aws bedrock list-foundation-models` and `aws bedrock list-inference-profiles`.
- Direct models with text input/output and on-demand support are listed, alongside active inference profiles. Selecting an entry synchronizes Step 3's Bedrock model selection. Choose Save Settings to persist it.
- Changing AWS region requires another refresh. The previous model stays visible but is labeled as unverified until a new catalog is loaded.
- When boto3 raises AWS `ClientError`, the Python adapter reports its service error code and a bounded, redacted message instead of only `ValidationException`. Do not share any sensitive fields even when sending logs for support.

## Limitations
- A listed model/profile is discoverable, **not necessarily authorized, compatible with Converse, or invokable**. IAM policies, model access, service quotas, regional routing, and selected inference parameters can still block invocation.
- The selected profile needs permission for `bedrock:ListFoundationModels` and `bedrock:ListInferenceProfiles` to list both categories.
- The UI does not call a paid test inference or alter IAM permissions. Refresh is read-only.
- No real AWS credentials are available in this build environment; validate model listing and Scenario C AI invocation on your AWS account.
- The existing engine's migration/conversion/deployment behavior is preserved. Only `engine/cli.py` error handling changed to show sanitized AWS service diagnostics.
- Build and browser integration must be verified on Windows Visual Studio because the .NET SDK is unavailable in the build environment.

## Troubleshooting
1. Set your profile and region in AWS Settings (for example `ssis-glue-poc`, `ap-southeast-2`).
2. Connect and Test connection.
3. Refresh models for region, choose an active **inference profile** or supported on-demand text model, Save Settings.
4. Confirm the same selection appears at Step 3. Click Generate AI fixes where needed.
5. If AWS returns `ValidationException`, use the newly surfaced AWS service message to diagnose the exact request rejection. Do not rerun Glue packages unnecessarily.
