# v3.0.12 — Scenario C AI decimal formatting repair (2026-11-11)

## What changed
- Fixed source-grounded PowerShell `.ToString('F<n>')` normalization. No longer rewrites `format_number` to Spark Java `format_string('%.nf', Decimal)`; instead produces decimal fixed-scale, ungrouped string output. Normalizes matching model-generated `format_string` proposals too.
- Classifies `java.util.IllegalFormatConversionException: f != org.apache.spark.sql.types.Decimal` as generated `CODE_RUNTIME` (repairable), before generic JVM/environment heuristics.
- Uses the existing bounded AI revision loop (up to 3 proposals with a real runtime check, 2 with injected transport and no runtime check), binding failure evidence to the approved code hash.
- Ensures source-grounded formatting changes remain review-only, and the existing local parity, SHA approval and Glue deployment gates stay intact. AI cannot silently approve or deploy.
- Added targeted regression tests. Full offline suite: 327 passed, 4 subtests passed.

## Important
- No live AWS/Bedrock or Windows Spark validation was possible in the build environment. Run your local Spark test and SSIS reference parity before deployment.
- For previously failed *approved* sessions, do not manually modify candidate.py. Use the existing AI repair/review flow, then explicitly approve and validate the NEW candidate.
- A local numeric cast to `decimal(38,n)` can fail on values out of range; such errors are handled by validation and repair, not silently ignored. Confirm rounding against independent SSIS output.
- Scenario A and B production logic was left unchanged.
