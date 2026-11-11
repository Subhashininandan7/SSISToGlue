# Migration Forge v3.0.3 — Portable local runtime setup

This release is based on v3.0.2. The Python migration engine and existing workflow JavaScript are unchanged.
It is an additional local runtime discovery/setup feature. Windows .NET and live AWS execution still
need testing on a Windows developer workstation.

## Start normally

1. Unzip to any writable folder; no `D:` drive is required.
2. Open `FinalDemo/ScenarioC/SSISGlueDemo.sln` directly in Visual Studio 2022.
3. Start `DemoWeb`. In the web UI choose **Local runtime**.
4. Click **Recheck prerequisites**. The application creates its own scratch directories in:
   `%LOCALAPPDATA%\MigrationForge\Runtime\Temp` and `...\SparkLocal`.
5. For missing components, use the official install links shown alongside each dependency.
   Install with your company's normal software approval process, restart Visual Studio if PATH changes,
   and recheck. No AWS password or token is stored by Migration Forge.
6. Click **AWS settings** to configure each developer's AWS account, region, bucket, role, and model.

## Supported dependency downloads (official sources, NOT bundled executables)

* Python 3: https://www.python.org/downloads/windows/
* Java: Eclipse Temurin JDK 17: https://adoptium.net/temurin/releases/?version=17
* AWS CLI v2 (Windows per-user and administrator installers): https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
* AWS SCT installer: https://docs.aws.amazon.com/SchemaConversionTool/latest/userguide/CHAP_Installing.Procedure.html
* PySpark installation instructions: https://spark.apache.org/docs/latest/api/python/getting_started/install.html
* .NET 8 SDK: https://dotnet.microsoft.com/en-us/download/dotnet/8.0

After installing Python, optional local Spark can be installed explicitly in a Python environment:

    python -m pip install pyspark==4.0.3

The current application's Python dependencies are listed in `requirements.txt`:

    python -m pip install -r requirements.txt

Python and Java version compatibility should be checked against the exact PySpark build used.
For Windows Hadoop utilities, obtain binaries only from an organization-approved, trusted source;
no random `winutils.exe` downloads are supplied or silently installed. Set `HADOOP_HOME` to a valid
Hadoop home containing `bin\winutils.exe` if your local Spark distribution needs it. The diagnostic
will show missing utilities rather than claiming readiness. This is **not** an installer or a
full real Spark smoke test.

## Machine portability and overrides

* By default no absolute machine-specific path is required.
* `MIGRATION_FORGE_SPARK_TEMP` may be set by an advanced developer to override scratch location.
* `PYTHON_COMMAND` may select a specific Python executable; `JAVA_HOME` and `HADOOP_HOME` are honored
  when correctly configured.
* Environment changes are applied only to the Python child process. The Visual Studio process
  and Windows machine environment are not modified.
* Cloud Glue jobs do not require Hadoop tools on the local computer; those tools only matter for
  local Spark checks/runs.

## Limitations

The setup screen provides detected status, official installer pages and installation commands;
installers themselves are not redistributed in this ZIP. The app does not auto-install system tools,
modify PATH permanently, or provide a guaranteed cross-version winutils binary. AWS SCT conversion
may require JDBC drivers and further per-user configuration, depending on the SSIS packages.

Test the .NET build, genuine SCT conversion, local Spark, AWS identity, Bedrock and Glue from a
Windows workstation before presenting as end-to-end validated on another laptop.
