using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;

// Local-only prerequisite inventory. No software installation, downloads, shell execution,
// credential reads, or process-wide environment changes are performed by this class.
public static class PortableRuntime
{
    public sealed record Component(string Id, string Name, bool Found, string Detail, string Url, bool Required);
    public sealed record LocalOptions(string HadoopHome = "");
    public sealed record Report(string RuntimeRoot, string Temp, string SparkLocal, string HadoopHome, bool LocalSparkReady,
        IReadOnlyList<Component> Components, string Notice);

    private static readonly string LocalRoot = Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MigrationForge", "Runtime");

    private static string LocalSettingsPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "MigrationForge", "runtime-settings.json");

    public static LocalOptions ReadOptions()
    {
        try { return File.Exists(LocalSettingsPath)
            ? JsonSerializer.Deserialize<LocalOptions>(File.ReadAllText(LocalSettingsPath)) ?? new()
            : new(); }
        catch (Exception) { return new(); }
    }

    public static async Task SaveOptions(LocalOptions options)
    {
        var supplied = (options.HadoopHome ?? "").Trim().Trim('"');
        if (!string.IsNullOrWhiteSpace(supplied) &&
            (!Path.IsPathFullyQualified(supplied) || !File.Exists(Path.Combine(supplied, "bin", "winutils.exe"))))
            throw new ArgumentException("Select an existing Hadoop installation containing bin\\winutils.exe, or leave the field blank.");
        var root = Path.GetDirectoryName(LocalSettingsPath)!;
        Directory.CreateDirectory(root);
        // This file contains only an optional filesystem path, never secrets.
        var tmp = LocalSettingsPath + ".tmp";
        await File.WriteAllTextAsync(tmp, JsonSerializer.Serialize(new LocalOptions(supplied)));
        File.Move(tmp, LocalSettingsPath, true);
    }

    public static string RuntimeRoot
    {
        get
        {
            var custom = Environment.GetEnvironmentVariable("MIGRATION_FORGE_SPARK_TEMP");
            // Explicit developer override is supported. Never assume a D: drive exists.
            return string.IsNullOrWhiteSpace(custom) ? LocalRoot : Path.GetFullPath(custom.Trim().Trim('"'));
        }
    }
    public static (string Temp, string SparkLocal) EnsureScratch()
    {
        var root = RuntimeRoot;
        var temp = Path.Combine(root, "Temp");
        var spark = Path.Combine(root, "SparkLocal");
        Directory.CreateDirectory(temp);
        Directory.CreateDirectory(spark);
        return (temp, spark);
    }

    public static string? FindExecutable(string name)
    {
        foreach (var directory in (Environment.GetEnvironmentVariable("PATH") ?? "")
                     .Split(Path.PathSeparator, StringSplitOptions.RemoveEmptyEntries))
        {
            try
            {
                var candidate = Path.Combine(directory.Trim().Trim('"'), name);
                if (File.Exists(candidate)) return candidate;
            }
            catch (Exception e) when (e is ArgumentException or NotSupportedException or System.IO.IOException) { }
        }
        return null;
    }

    private static string? FindFromEnvironment(string variable, string executable)
    {
        var directory = Environment.GetEnvironmentVariable(variable);
        if (string.IsNullOrWhiteSpace(directory)) return null;
        try
        {
            var candidate = Path.Combine(directory.Trim().Trim('"'), "bin", executable);
            return File.Exists(candidate) ? candidate : null;
        }
        catch (Exception e) when (e is ArgumentException or NotSupportedException) { return null; }
    }

    public static string? PythonPath()
    {
        var overridePath = Environment.GetEnvironmentVariable("PYTHON_COMMAND");
        if (!string.IsNullOrWhiteSpace(overridePath))
        {
            var p = overridePath.Trim().Trim('"');
            if (File.Exists(p)) return p;
            if (!p.Contains('\\') && !p.Contains('/')) return FindExecutable(p);
        }
        return FindExecutable(OperatingSystem.IsWindows() ? "python.exe" : "python3")
            ?? FindExecutable(OperatingSystem.IsWindows() ? "py.exe" : "python");
    }

    public static string? JavaPath() => FindFromEnvironment("JAVA_HOME", OperatingSystem.IsWindows() ? "java.exe" : "java")
        ?? FindExecutable(OperatingSystem.IsWindows() ? "java.exe" : "java");
    public static string? AwsPath() => FindExecutable(OperatingSystem.IsWindows() ? "aws.exe" : "aws")
        ?? (OperatingSystem.IsWindows() && File.Exists(Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Amazon", "AWSCLIV2", "aws.exe"))
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Amazon", "AWSCLIV2", "aws.exe") : null);

    public static string? HadoopHome()
    {
        var root = Environment.GetEnvironmentVariable("HADOOP_HOME");
        if (!string.IsNullOrWhiteSpace(root) && File.Exists(Path.Combine(root, "bin", "winutils.exe"))) return root;
        root = ReadOptions().HadoopHome;
        if (!string.IsNullOrWhiteSpace(root) && File.Exists(Path.Combine(root, "bin", "winutils.exe"))) return root;
        return null;
    }

    private static async Task<(bool Ok, string Version)> ProbeAsync(string? executable, string[] args, CancellationToken cancellationToken)
    {
        if (string.IsNullOrWhiteSpace(executable)) return (false, "Not found");
        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
            timeout.CancelAfter(TimeSpan.FromSeconds(6));
            var start = new ProcessStartInfo(executable) {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            foreach (var arg in args) start.ArgumentList.Add(arg);
            using var process = Process.Start(start);
            if (process is null) return (false, "Could not start");
            var stdout = process.StandardOutput.ReadToEndAsync(timeout.Token);
            var stderr = process.StandardError.ReadToEndAsync(timeout.Token);
            await process.WaitForExitAsync(timeout.Token);
            var output = ((await stdout) + " " + (await stderr)).Trim();
            var first = output.Split('\n', StringSplitOptions.RemoveEmptyEntries).FirstOrDefault()?.Trim() ?? "No version reported";
            // Versions only: don't return arbitrary subprocess errors or local credential content.
            if (process.ExitCode != 0) return (false, "Installed but unavailable or incompatible");
            return (true, first.Length > 150 ? first[..150] : first);
        }
        catch (OperationCanceledException) { return (false, "Check timed out"); }
        catch (Exception) { return (false, "Unable to run executable"); }
    }

    public static async Task<Report> Check(CancellationToken cancellationToken)
    {
        var dirs = EnsureScratch();
        var python = PythonPath();
        var java = JavaPath();
        var aws = AwsPath();
        var pythonArgs = Path.GetFileNameWithoutExtension(python ?? "").Equals("py", StringComparison.OrdinalIgnoreCase)
            ? new[] { "-3", "--version" } : new[] { "--version" };
        var sparkArgs = Path.GetFileNameWithoutExtension(python ?? "").Equals("py", StringComparison.OrdinalIgnoreCase)
            ? new[] { "-3", "-c", "import pyspark; print(pyspark.__version__)" }
            : new[] { "-c", "import pyspark; print(pyspark.__version__)" };
        var pythonCheck = ProbeAsync(python, pythonArgs, cancellationToken);
        var sparkCheck = ProbeAsync(python, sparkArgs, cancellationToken);
        var javaCheck = ProbeAsync(java, new[] { "-version" }, cancellationToken);
        var awsCheck = ProbeAsync(aws, new[] { "--version" }, cancellationToken);
        var dotnetCheck = ProbeAsync(FindExecutable(OperatingSystem.IsWindows() ? "dotnet.exe" : "dotnet"), new[] { "--version" }, cancellationToken);
        await Task.WhenAll(pythonCheck, sparkCheck, javaCheck, awsCheck, dotnetCheck);
        var py = await pythonCheck; var spark = await sparkCheck;
        var jdk = await javaCheck; var cli = await awsCheck; var dotnet = await dotnetCheck;
        var hadoop = HadoopHome();
        var sct = OperatingSystem.IsWindows() && Directory.Exists(@"C:\Program Files\AWS Schema Conversion Tool")
            ? Directory.EnumerateFiles(@"C:\Program Files\AWS Schema Conversion Tool", "RunSCTBatch.cmd", SearchOption.AllDirectories).FirstOrDefault()
            : null;
        var components = new List<Component> {
            new("dotnet", ".NET SDK", dotnet.Ok, dotnet.Ok ? dotnet.Version : "Install .NET 8 SDK for the Visual Studio solution", "https://dotnet.microsoft.com/en-us/download/dotnet/8.0", true),
            new("python", "Python", py.Ok, py.Ok ? py.Version : "Python 3 not detected", "https://www.python.org/downloads/windows/", true),
            new("pyspark", "PySpark", spark.Ok, spark.Ok ? spark.Version : "Install with your Python: python -m pip install pyspark==4.0.3", "https://spark.apache.org/docs/latest/api/python/getting_started/install.html", false),
            new("java", "Java JDK", jdk.Ok, jdk.Ok ? jdk.Version : "A compatible JDK is required for local Spark", "https://adoptium.net/temurin/releases/?version=17", false),
            new("aws", "AWS CLI v2", cli.Ok, cli.Ok ? cli.Version : "Required for AWS account sign-in", "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html", true),
            new("sct", "AWS Schema Conversion Tool", sct is not null, sct is not null ? "SCT batch launcher found" : "Required for real SSIS conversion", "https://docs.aws.amazon.com/SchemaConversionTool/latest/userguide/CHAP_Installing.Procedure.html", false),
            new("hadoop", "Windows Hadoop utilities", hadoop is not null || !OperatingSystem.IsWindows(),
                hadoop is not null ? "Configured winutils.exe detected" : "Not found — local Spark may require compatible Windows Hadoop utilities. No binary is bundled.",
                "https://spark.apache.org/docs/latest/", false)
        };
        return new Report(RuntimeRoot, dirs.Temp, dirs.SparkLocal, ReadOptions().HadoopHome,
            py.Ok && spark.Ok && jdk.Ok && (hadoop is not null || !OperatingSystem.IsWindows()),
            components, "Missing prerequisites require user installation. Migration Forge never downloads or executes installers automatically. AWS Glue cloud execution does not require local Hadoop utilities.");
    }
}
