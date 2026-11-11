# Migration Forge v3.0.2 — Direct Visual Studio launch + Bedrock JSON recovery

## What changed

1. `DemoWeb/Program.cs`: Each `/api/action` Python subprocess receives stable Windows Spark TEMP, TMP, TMPDIR, and SPARK_LOCAL_DIRS values. Reuses `D:\MigrationForgeSparkTemp` if it already exists; otherwise uses `%LOCALAPPDATA%\MigrationForge\SparkTemp`. Directories are created on demand. Detects an existing `HADOOP_HOME` or `D:\Hadoop` and adds `bin` to the subprocess PATH only if winutils.exe is present. This removes the PowerShell-launch prerequisite *for these settings*, without modifying your global environment.
2. `DemoWeb/Program.cs`: When AWS setup is saved, uses the selected local profile and region as child-process AWS environment defaults. Existing request-specific overrides still take precedence in Python code.
3. `engine/unsupported_process_ai.py`: Recognizes safely parseable JSON surrounded by model commentary, Markdown JSON code fences, and double-encoded JSON. Strictly requires exactly `code` and `explanation` strings, followed by the original AST, semantic, and runtime checks. Ambiguous or incomplete responses still fail closed.
4. Increased Bedrock generation token budget from 4500 to 6500 and records token-limit truncation in retry feedback, without publishing unverified proposals.
5. Added regression tests for response parsing and subprocess environment.

## Run

Extract the ZIP to a fresh folder, then open `ScenarioC\SSISGlueDemo.sln` **directly** in Visual Studio 2022 and start `DemoWeb`. No PowerShell bootstrap required for the Spark temp variables. Keep Python, Java, PySpark, Hadoop/winutils and AWS CLI prerequisites installed; configuration cannot install missing software.

Use AWS Settings to save your own profile and region, connect/reconnect as necessary. To verify AI remediation, create a new Scenario C session if the previous session is stuck; select `Generate AI fixes` and inspect the proposal before approval. Do not re-run Glue jobs unnecessarily. The version marker for the underlying migration engine may still be `2.9.9-source-derived-numeric-parity`, because no overall migration-engine workflow revision is implied by this patch.

## Verification / limitations

- Python pytest suite passes locally.
- No .NET SDK available here: Windows VS2022 build **not executed**.
- No AWS access here: live Bedrock model response and Glue execution **not executed**.
- The parser does not make malformed model output correct. It accepts only a *single unambiguous* JSON proposal. Retries may still fail if Bedrock cannot meet the contract.
- For a server or multi-user deployment, replace local process-based execution with an isolated worker service; this is intended for localhost developer demos.
- Existing approved proposal hashes are not modified.
