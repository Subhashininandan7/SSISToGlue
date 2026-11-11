# Migration Forge v3.0.1 — AWS wizard region configuration fix

## Fix
Previously, the wizard saved the selected Region but its **Connect to AWS**
launcher called `aws login --profile PROFILE` without configuring the selected
AWS CLI profile. On a new computer or new `default` profile, AWS CLI then
asked for the Region again.

The local launcher now runs these commands in sequence, using the exact
profile and Region saved in the wizard:

```cmd
aws configure set region ap-southeast-2 --profile YOUR_PROFILE
aws login --profile YOUR_PROFILE --region ap-southeast-2
```

For IAM Identity Center, the second command is `aws sso login --profile
YOUR_PROFILE --region ap-southeast-2`. SSO profiles must still be initialized
with their SSO start URL and SSO login Region on each computer (one-time AWS
CLI setup). An ordinary AWS Region does not replace the Identity Center
start URL or SSO session configuration.

## Running
1. Extract this ZIP to a NEW directory. Open `ScenarioC/SSISGlueDemo.sln`.
2. Start `DemoWeb` and click **AWS settings**.
3. Select the correct profile (e.g., `ssis-glue-poc`, not `default` unless
   `default` is intentional), Region, bucket, Glue role and model. Save.
4. Click **Connect to AWS**. The AWS CLI profile Region is configured from
   the wizard before browser login, so no duplicate Region prompt is expected.
5. Complete AWS-hosted login and click **Test connection**.

## Scope
This is a targeted change to `DemoWeb/AwsSetup.cs`, the AWS setup UI message,
and the endpoint response text. The existing Python migration engine,
conversion orchestration, Bedrock AI remediation, Glue deployment, and CSV
validation have NOT been modified. Only non-secret AWS CLI profile Region
is persisted. Credentials remain with AWS CLI.

## Local limitations
A real AWS login and Windows Visual Studio build must be tested on the target
Windows machine. The app's Connect action runs on the Windows computer hosting
DemoWeb (localhost PoC), not an arbitrary remote browser device.
