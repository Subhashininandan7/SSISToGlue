# Migration Forge v3.0.9 — Generic Spark decimal precision repair

Based on v3.0.8. This release targets Spark SQL `DECIMAL_PRECISION_EXCEEDS_MAX_PRECISION` in Bedrock-generated Execute Process translations, including the reported "Decimal precision 55 exceeds max precision 38" failure.

## Changes

- Generated-code static validation rejects invalid explicit decimal(p,s) types (p > 38, p < 1, s > p) and provably over-wide *intermediate* multiplication of two explicitly cast DECIMAL operands (p1+p2+1 > 38). It does not assume a column name or globally rewrite numeric expressions.
- The local Spark preflight recognizes decimal precision exceptions as generated-code defects, requests a targeted bounded Bedrock repair and revalidates before offering the candidate for review. It never disables decimal checks, converts to float as a blanket workaround, or declares semantic parity without independent evidence.
- After human approval, a failed local validation writes `local-validation-failure.json` bound to the exact approved SHA-256. The existing **Generate AI fixes where needed** control can now create a NEW review-only fix from the old approved source and the observed error. The old approved file is kept unchanged until the user explicitly approves the replacement; the old proposal/code are then archived in `review-history/`.
- Validation failures due to environment or missing inputs never trigger this AI repair action. Retry a transient local validation without regenerating code; the same approved SHA remains enforced.
- The existing SCT, AWS credentials wizard, AWS Glue deployment, approval hash, and CSV parity gates are preserved. No existing successful AWS job is modified or rerun.

## How to test the existing failed Scenario C

1. Stop the old `DemoWeb` and extract this ZIP in a new folder. Open `FinalDemo/ScenarioC/SSISGlueDemo.sln` directly in VS2022 and start `DemoWeb`.
2. Resume the existing portfolio/session, not a new bulk upload. The already-approved but failed candidate stays in its stored session (`%USERPROFILE%/.ssis_glue_demo/sessions/<id>/process-ai`).
3. Under Step 3 approve model cost/source transmission as before, then click **Generate AI fixes where needed**. For a code-related failed validation it should show a **new** source-grounded diff, not redeploy the previous failure.
4. Review the new diff, especially operand decimal casts, grouping/rounding, output schema, and source semantics; approve it explicitly. The existing Step 3 flow runs local validation after approval. A failed run still blocks deployment.
5. Upload the correct input CSV and independent original SSIS output to the same session before generating when possible. Without uploaded inputs, the model can be checked statically but there is no proof its code actually runs or matches SSIS output. New uploads may require starting a new portfolio/session because the original analysis is SHA-bound.
6. Only if local output validation passes should you proceed to the separate AWS approval/deployment actions; an independent SSIS baseline is necessary for a `MATCH` claim.

## Verification and limitations

- Local Python test suite: 306 tests passed; JS syntax checked with Node; Python modules compiled successfully.
- We could not run Visual Studio/.NET or a live AWS Bedrock/Spark job in this environment. Therefore it is *not* claimed that this particular user session's revised Bedrock output already succeeds.
- Spark can produce precision overflow through expressions whose numeric types are inferred dynamically or embedded in SQL strings. Those require the local Spark test and targeted repair; the static AST check is intentionally limited to provable cases.
- Runtime repair cannot safely infer a numeric type that the original source does not specify. Ambiguous output semantics should remain review-required or blocked.
- This is a trusted local development runner, not an isolation sandbox for hostile generated code.
