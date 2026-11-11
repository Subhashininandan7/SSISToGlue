# Migration Forge v3.0 — Local AWS Setup Wizard

## Scope and regression protection

This release adds *only* the AWS onboarding UI and ASP.NET Core API layer to v2.9.9.
All 23 Python files under `engine/` match v2.9.9 byte-for-byte. No AWS SCT, Bedrock
repair, approval/hash, Glue deployment, Spark execution, package coordination or
CSV validation logic was changed. The original `unified.js` workflow is unchanged.

## Starting in Visual Studio 2022

1. Extract the complete ZIP, then open `ScenarioC/SSISGlueDemo.sln`.
2. Start `DemoWeb` (F5). The app listens on `http://127.0.0.1:5297`.
3. On first run, fill the AWS setup wizard. Existing users can open **AWS settings**.
4. Enter the AWS profile, region, S3 bucket, S3 object prefix, Glue execution role
   (name or ARN), Bedrock model identifier, and login method.
5. Click **Save settings**, **Connect to AWS**, and finish AWS-hosted sign-in in the
   newly opened local Windows command console/browser.
6. Click **Test connection**. Confirm that AWS STS shows your expected account and
   identity. S3, Glue and Bedrock catalog are read-only permission checks.
7. Close the wizard. The existing five-step migration workflow remains unchanged.

If your AWS CLI profile was created with `aws login --profile example`, choose
**AWS CLI browser login**. If your profile was configured with
`aws configure sso --profile example`, choose **IAM Identity Center / SSO**.
For a first-time SSO user, run `aws configure sso --profile NAME` once on that
computer before attempting the application's Connect button.

## Configuration, no passwords

`DemoWeb/appsettings.json` contains NON-SECRET default AWS configuration only.
When a developer saves the wizard, settings are written to their OWN user profile:

`%USERPROFILE%\.ssis_glue_demo\aws-setup.json`

The credentials themselves are managed by the standard AWS CLI / SDK profile
credentials stores. No usernames, AWS passwords, MFA secrets, temporary credentials
or access keys are stored by Migration Forge.

The application's profile, region, bucket, prefix, role, and model inputs are
updated from the selected profile. This supplies the SAME settings used in the
existing engine requests, so no Python migration implementation changes are needed.

## Security and limitations

- Local Windows / localhost PoC only. Do NOT deploy this server to a public or
  multi-user host: the login launcher starts a command console on the server machine.
- AWS CLI v2 must be installed on PATH.
- **Connect** opens a terminal which launches an AWS browser flow. **Test** verifies
  identity and read-only service access; it does not execute a billable Bedrock
  inference, run Glue jobs, test Glue PassRole, or validate model entitlement.
- AWS IAM permissions and Glue service role must be configured by the account owner.
- `aws login` and SSO login will require reauthentication when sessions expire.
- This release does NOT automatically retry a previously failed AI operation;
  after a successful connection test, click the existing Generate AI fixes action.
- Use a different account's bucket, role, profile and region for that person's demo.
- The local `aws-setup.json` is user-specific; it should not be committed or
  distributed with the portable project ZIP.

## Verification performed for this release

- Python test suite: 245 passed and 4 subtests passed.
- JavaScript syntax: `node --check` passed for new setup and unchanged workflow.
- All 23 Python engine files identical to the v2.9.9 source ZIP.
- ZIP file integrity verified.

A Windows .NET build, browser interaction and AWS identity sign-in could not be
executed in the packaging environment. Verify these on the target Windows PC.
