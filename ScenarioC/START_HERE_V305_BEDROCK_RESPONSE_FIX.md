# Migration Forge v3.0.5 — Bedrock response format compatibility

Based on v3.0.4; targeted change to `engine/unsupported_process_ai.py` only, plus new regression tests. Existing UI, AWS setup, SCT, Glue and CSV comparison logic are unchanged.

## Fixed

- Corrected JSON fenced-message matching so a fenced Python block is not stripped as though it were JSON.
- Accepts exactly one syntactically parseable Python module containing `def transform(...)` when Bedrock ignores the requested `{"code": ..., "explanation": ...}` JSON envelope. Also supports a single ```python fenced module surrounded by commentary.
- Rejects multiple fenced proposals, incomplete modules and other ambiguous responses.
- Any recovered module still must pass existing Python AST restrictions, source-derived numeric formatting checks, actual preflight checks when available, and human approval before deployment.
- Adds non-sensitive per-attempt diagnostics (response length and coarse response shape) to `ai-diagnostics.json`; raw model output is not saved on rejection.

## Getting started

1. Extract ZIP to a NEW empty folder.
2. Open `FinalDemo/ScenarioC/SSISGlueDemo.sln` in Visual Studio directly and start DemoWeb.
3. Configure AWS profile, region, and Bedrock model in AWS settings as before.
4. Open your prepared session, and retry *Generate AI fixes where needed* for Scenario C.
5. Inspect model diff and local preflight before any approval or deployment.

## Caveats

- Not tested against a live AWS account in this environment. If the model produces invalid Python, a truncated response, or incompatible business logic, validation correctly rejects the proposal.
- Successful code generation or AWS Glue execution alone does not prove SSIS parity.
- Local Python suite: 272 passed, 4 subtests passed; SyntaxWarnings from pre-existing test fixture strings remain.
- Visual Studio / Windows compilation and AWS Bedrock call require local verification.
