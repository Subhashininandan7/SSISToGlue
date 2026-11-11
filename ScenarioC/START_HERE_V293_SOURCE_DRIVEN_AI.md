# Migration Forge v2.9.3 — Evidence-driven Bedrock instruction fix

This is a candidate update built on the supplied v2.9.2 source snapshot, **not a live-verified AWS or Windows build**. Extract separately; retain the working A/B installation.

## Change
The existing **Generate AI fixes where needed** route still uses one button. Its Execute Process 25029 adapter now constructs a source-evidence prompt from the original .dtsx Execute Process metadata, SCT-generated warning/stub, approved associated PowerShell source, and optional CSV header schemas. Nothing requires pre-existing destination output.

The Bedrock prompt no longer assumes the demo package name, Employees.csv, ActiveEmployees.csv, or any specific business transformation. It requires `transform(spark, input_prefix, output_prefix)` with no executable top-level statements; explicit numeric casts; source-derived null/rounding semantics; correct Spark CSV-directory behavior; and reporting unknown behaviors rather than guessing. Source statements take priority over free-text task descriptions.

AST validation, bounded structural retry, human hash approval, and existing restricted local validation are retained. No new UI button or standalone page is added. Existing normal A/B conversion/remediation handlers are unchanged.

## Important limitations
* This adapter supports one original Execute Process Task with a static PowerShell `.ps1` source and genuine SCT warning 25029. It is not a universal translator for all SSIS components.
* A clearer prompt cannot guarantee runnable or semantically equivalent PySpark; use real local runtime tests and independently verified SSIS outputs where available.
* The current local runner is not an untrusted-code security sandbox. Do not execute AI-produced code against sensitive systems or production resources.
* Automatic AWS Glue deployment for this unsupported task remains blocked.
* No live Bedrock call, Windows build, or Spark integration execution was performed here.

## Run
1. Stop the previous application; extract into a new directory.
2. Open `ScenarioC/SSISGlueDemo.sln` in Visual Studio 2022 and start DemoWeb.
3. Confirm UI shows v2.9.3 and upload the original package and its dependencies.
4. Run SCT conversion and use the existing Generate AI fixes button with explicit approvals.
5. Review the exact generated diff. Only approve for controlled testing after inspecting source-derived correctness.

## Regression test
From ScenarioC with pytest installed: `python -m pytest -q tests`
