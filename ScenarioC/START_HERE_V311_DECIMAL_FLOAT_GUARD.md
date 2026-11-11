# Migration Studio v3.0.11 — Package C decimal regression guard

## Confirmed finding from supplied v3.0.10 solution
The source code statically rejects explicit oversized Spark DECIMAL casts and some oversized multiplications, but did not reject Python `Decimal(0.1)`. That value is constructed from an inexact binary float and can cause Spark's inferred precision to exceed 38, matching the observed error (`precision 55`).

## Targeted change
In `engine/unsupported_process_ai.py`, `inspect_decimal_precision` now rejects `Decimal(<float literal>)`, including imported aliases, before showing the Bedrock output as an approvable proposal. It requests a bounded, source-grounded correction; it does not silently rewrite approved code or bypass validation. Exact decimal strings (e.g. `Decimal('0.10')`) are not rejected by this specific rule. Existing Spark runtime checks, human approval and parity gates are unchanged.

## Run on Windows
1. Unzip to a NEW location; do not mix with an old `bin` or `obj` directory.
2. Open `FinalDemo/ScenarioC/SSISGlueDemo.sln` in Visual Studio 2022 and start `DemoWeb`.
3. Resume the original portfolio/session if still present under `%USERPROFILE%\.ssis_glue_demo\sessions`. This ZIP does not contain your live persisted session data.
4. For package C with `LOCAL_VALIDATION_FAILED`, click `Generate AI fixes where needed` to request a NEW review-only proposal. Inspect its diff; approve only after checking the PowerShell semantics. The previous approved code remains unchanged until explicit approval.
5. Run local validation and independent CSV comparison. Do not deploy C until these gates pass.

## Verification in this environment
- 322 Python offline tests passed (plus 4 subtests); new tests cover `Decimal(0.1)` rejection, alias spelling, and the AI correction retry path.
- `node --check` passed for `DemoWeb/wwwroot/unified.js`.
- .NET / Visual Studio, live AWS Bedrock and Spark runtime were NOT available for end-to-end execution here.
- New guard targets the reproduced float literal pattern; other inferred precision faults still require Spark preflight and feedback-based remediation. It does NOT guarantee the model always returns correct code.
- This source-only ZIP intentionally excludes stale `bin`, `obj`, `.vs`, and cache folders. Restore/build using Visual Studio.
