using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;

// Security boundary: localhost only. This is a developer PoC, NOT a remotely hosted service.
var builder = WebApplication.CreateBuilder(args);
builder.WebHost.UseUrls("http://127.0.0.1:5297");
var app = builder.Build();
app.Use(async (ctx, next) => {
    ctx.Response.Headers["X-Content-Type-Options"] = "nosniff";
    ctx.Response.Headers["X-Frame-Options"] = "DENY";
    ctx.Response.Headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; object-src 'none'";
    await next();
});
app.UseDefaultFiles();
app.UseStaticFiles();

// AWS onboarding is intentionally separate from the established Python migration engine.
// All AWS settings persist ONLY under the current OS user's home directory.
static bool HasLocalMarker(HttpContext c) => c.Request.Headers["X-Demo-Request"] == "1" &&
    (c.Request.Headers["Origin"].Count == 0 ||
     (Uri.TryCreate(c.Request.Headers["Origin"].ToString(), UriKind.Absolute, out var o) &&
      o.Host == "127.0.0.1" && o.Port == 5297 && o.Scheme == "http"));
app.MapGet("/api/aws-setup", () => Results.Json(new {configured=AwsSetup.Configured,
    settings=AwsSetup.Read(app.Configuration)}));
app.MapPost("/api/aws-setup", async (HttpContext ctx, AwsSetupOptions settings) => {
    if (!HasLocalMarker(ctx)) return Results.BadRequest(new {error="Invalid local request"});
    var error=AwsSetup.Validate(settings);
    if (error.Length>0) return Results.BadRequest(new {error});
    await AwsSetup.Save(settings);
    return Results.Json(new {ok=true, configured=true, settings});
});
app.MapPost("/api/aws-setup/connect", (HttpContext ctx) => {
    if (!HasLocalMarker(ctx)) return Results.BadRequest(new {error="Invalid local request"});
    if (!AwsSetup.Configured) return Results.BadRequest(new {error="Save AWS setup before connecting"});
    try { AwsSetup.StartLogin(AwsSetup.Read(app.Configuration));
        return Results.Json(new {ok=true, message="AWS sign-in launched using the saved profile and region. Complete AWS browser authentication, then click Test connection."}); }
    catch (Exception ex) when (ex is ArgumentException or System.ComponentModel.Win32Exception or PlatformNotSupportedException) {
        return Results.BadRequest(new {error=ex is System.ComponentModel.Win32Exception ? "Cannot launch AWS login. Install AWS CLI v2." : ex.Message});
    }
});
app.MapPost("/api/aws-setup/test", async (HttpContext ctx) => {
    if (!HasLocalMarker(ctx)) return Results.BadRequest(new {error="Invalid local request"});
    if (!AwsSetup.Configured) return Results.BadRequest(new {error="Save AWS setup before testing"});
    try { return Results.Json(await AwsSetup.Test(AwsSetup.Read(app.Configuration), ctx.RequestAborted)); }
    catch (ArgumentException e) { return Results.BadRequest(new {error=e.Message}); }
});

// Read-only catalog based on the selected region/profile; never invokes a model.
app.MapGet("/api/aws-setup/bedrock-models", async (HttpContext ctx, string? profile, string? region) => {
    var saved = AwsSetup.Read(app.Configuration);
    var cfg = saved with { Profile = profile ?? saved.Profile, Region = region ?? saved.Region };
    try { return Results.Json(await AwsSetup.ListBedrockChoices(cfg, ctx.RequestAborted)); }
    catch (ArgumentException ex) { return Results.BadRequest(new { error = ex.Message }); }
});

// Portable per-user runtime report. Read-only checks; creates only current-user scratch folders.
app.MapGet("/api/runtime/check", async (HttpContext ctx) => {
    try { return Results.Json(await PortableRuntime.Check(ctx.RequestAborted)); }
    catch (Exception) { return Results.Json(new {error="Runtime check failed; verify write permission to local AppData."}, statusCode: 500); }
});

app.MapPost("/api/runtime/settings", async (HttpContext ctx, PortableRuntime.LocalOptions options) => {
    if (!HasLocalMarker(ctx)) return Results.BadRequest(new {error="Invalid local request"});
    try { await PortableRuntime.SaveOptions(options); return Results.Json(new {ok=true}); }
    catch (ArgumentException e) { return Results.BadRequest(new {error=e.Message}); }
});

app.MapPost("/api/action", async (HttpContext context) => {
    if (context.Request.Headers["X-Demo-Request"] != "1")
        return Results.BadRequest(new { ok = false, error = "Missing same-origin request marker" });
    if (context.Request.ContentLength is > 23_000_000)
        return Results.BadRequest(new { ok = false, error = "Request too large" });
    string json;
    using (var reader = new StreamReader(context.Request.Body))
        json = await reader.ReadToEndAsync();
    if (json.Length > 23_000_000) return Results.BadRequest(new { ok = false, error = "Request too large" });
    try {
        using var doc = JsonDocument.Parse(json);
        if (doc.RootElement.ValueKind != JsonValueKind.Object)
            return Results.BadRequest(new { ok = false, error = "Expected JSON object" });
        var appRoot = Directory.GetParent(app.Environment.ContentRootPath)?.FullName
            ?? app.Environment.ContentRootPath;
        // When published, content root may already contain engine/. In source mode it is DemoWeb/.
        if (!File.Exists(Path.Combine(appRoot, "engine", "cli.py"))) appRoot = app.Environment.ContentRootPath;
        var scriptPath = Path.Combine(appRoot, "engine", "cli.py");
        if (!File.Exists(scriptPath))
            return Results.Json(new { ok = false, error = "Python adapter missing from deployment" }, statusCode: 500);
        var python = ResolvePythonExecutable();
        var psi = new ProcessStartInfo(python) {
            WorkingDirectory = appRoot,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            UseShellExecute = false, CreateNoWindow = true
        };
        if (Path.GetFileNameWithoutExtension(python).Equals("py", StringComparison.OrdinalIgnoreCase))
            psi.ArgumentList.Add("-3");
        psi.ArgumentList.Add(scriptPath);
        // Local Spark/JVM configuration belongs to the child process, not to
        // the Visual Studio launch environment. No process-wide mutations.
        ConfigureLocalSpark(psi);
        // Each developer's saved, non-secret AWS setup determines their profile
        // and region for the Python engine; do not use a hardcoded demo identity.
        if (AwsSetup.Configured) {
            var aws = AwsSetup.Read(app.Configuration);
            psi.Environment["AWS_PROFILE"] = aws.Profile;
            psi.Environment["AWS_DEFAULT_REGION"] = aws.Region;
            psi.Environment["AWS_REGION"] = aws.Region;
        }
        using var proc = Process.Start(psi);
        if (proc is null) return Results.Json(new { ok = false, error = "Python process failed to start" }, statusCode: 500);
        await proc.StandardInput.WriteAsync(json);
        proc.StandardInput.Close();
        var stdoutTask = proc.StandardOutput.ReadToEndAsync();
        var stderrTask = proc.StandardError.ReadToEndAsync();
        // Real SCT Batch can run much longer than a normal Python API request.
        // The browser keeps one conversion action in flight; do not time out at 5 minutes.
        var isSctConversion = doc.RootElement.TryGetProperty("action", out var a)
            && a.ValueKind == JsonValueKind.String && (
                a.GetString() == "convert-auto" ||
                (a.GetString() == "bulk-step" &&
                 doc.RootElement.TryGetProperty("operation", out var op) &&
                 op.ValueKind == JsonValueKind.String && op.GetString() == "convert"));
        using var deadline = new CancellationTokenSource(TimeSpan.FromMinutes(isSctConversion ? 32 : 5));
        await proc.WaitForExitAsync(deadline.Token);
        var result = await stdoutTask;
        _ = await stderrTask; // Never expose potentially sensitive local error output in HTTP.
        if (proc.ExitCode != 0) return Results.Json(new { ok = false, error = "Python adapter failed" }, statusCode: 500);
        return Results.Content(result, "application/json");
    } catch (System.ComponentModel.Win32Exception) {
        return Results.Json(new { ok = false, error = "Python process could not start. Install Python 3 or set PYTHON_COMMAND to the full path of python.exe, then restart Migration Forge." }, statusCode: 500);
    } catch (JsonException) {
        return Results.BadRequest(new { ok = false, error = "Invalid JSON" });
    } catch (OperationCanceledException) {
        return Results.Json(new { ok = false, error = "Operation timed out" }, statusCode: 504);
    } catch (Exception ex) {
        return Results.Json(new { ok = false, error = "Application process failure: " + ex.GetType().Name }, statusCode: 500);
    }
});

app.MapGet("/api/artifact/{sid}/{name}", (string sid, string name) => {
    if (!Regex.IsMatch(sid, "^[0-9a-f]{16}$")) return Results.BadRequest();
    string? relative = name switch {
        "repair-report" => Path.Combine("candidates", "report.json"),
        "ai-plan" => Path.Combine("bedrock", "latest.json"),
        "ai-patch-proposal" => Path.Combine("bedrock", "patch-proposal.json"),
        "ai-patch-diff" => Path.Combine("bedrock", "patch-diff.txt"),
        "ai-patch-applied" => Path.Combine("bedrock", "patch-applied.json"),
        "sct-manifest" => Path.Combine("sct", "manifest.json"),
        "sct-cli-log" => Path.Combine("sct", "auto-sct.log"),
        "sct-cli-scenario" => Path.Combine("sct", "auto-scenario.scts"),
        "sct-cli-output" => Path.Combine("sct", "original-conversion-output.zip"),
        "sct-assessment" => Path.Combine("sct", "assessment-original.zip"),
        "sct-assessment-pdf" => Path.Combine("sct", "assessment-original.pdf"),
        "sct-cli-result" => Path.Combine("sct", "auto-result.json"),
        "sct-preflight" => Path.Combine("sct-candidate", "preflight.json"),
        "sct-entry" => Path.Combine("sct-candidate", "glue_entry_sct_a.py"),
        "sct-modules" => Path.Combine("sct-candidate", "sct_modules.zip"),
        "quick-scripts" => Path.Combine("quick", "corrected_scripts.zip"),
        "quick-entry" => Path.Combine("quick", "entry.py"),
        "quick-report" => Path.Combine("quick", "report.json"),
        "quick-ai-diff" => Path.Combine("quick", "diff.txt"),
        "process-ai-diff" => Path.Combine("process-ai", "diff.txt"),
        "process-ai-cloud-status" => Path.Combine("process-ai", "cloud-status.json"),
        "process-ai-cloud-output" => Path.Combine("process-ai", "cloud-output.zip"),
        "sct-diff" => Path.Combine("sct-candidate", "candidate-diff.txt"),
        "dtexec-log" => Path.Combine("ssis-validation", "dtexec.log"),
        "session" => "session.json",
        _ when Regex.IsMatch(name, "^candidate_[0-9]{1,3}\\.py$") => Path.Combine("candidates", name),
        _ => null
    };
    if (relative is null) return Results.NotFound();
    var home = Environment.GetEnvironmentVariable("SSIS_GLUE_DEMO_DATA")
        ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".ssis_glue_demo");
    var path = Path.Combine(home, "sessions", sid, relative);
    return File.Exists(path) ? (name == "sct-assessment-pdf" ? Results.File(path,"application/pdf") : Results.File(path, "application/octet-stream", Path.GetFileName(path))) : Results.NotFound();
});

Console.WriteLine("SSIS Glue Demo — http://127.0.0.1:5297 — local machine only");
app.Run();


// Windows does not always install the `py` launcher even when `python.exe` is available.
// Prefer a real executable on PATH; never invoke a shell with user-controlled arguments.
static string ResolvePythonExecutable() => PortableRuntime.PythonPath()
    ?? (OperatingSystem.IsWindows() ? "python.exe" : "python3");

// Configure reliable per-user local Spark scratch space without requiring
// PowerShell to launch Visual Studio. This only affects the Python child.
static void ConfigureLocalSpark(ProcessStartInfo psi) {
    if (!OperatingSystem.IsWindows()) return;
    var (temp, local) = PortableRuntime.EnsureScratch();
    psi.Environment["TEMP"] = temp;
    psi.Environment["TMP"] = temp;
    psi.Environment["TMPDIR"] = temp;
    psi.Environment["SPARK_LOCAL_DIRS"] = local;
    // Match the verified working local Spark configuration. The Spark launcher
    // starts a JVM whose java.io.tmpdir does not necessarily follow TEMP/TMP.
    // Keep this setting on the Python child (and its JVM descendants) only.
    var tempJvm = temp.Contains(' ') ? $"\"{temp}\"" : temp;
    var options = psi.Environment.TryGetValue("SPARK_SUBMIT_OPTS", out var currentSparkOpts)
        ? currentSparkOpts ?? "" : "";
    psi.Environment["SPARK_SUBMIT_OPTS"] = (options + " -Djava.io.tmpdir=" + tempJvm).Trim();
    // Detect installed Java and Hadoop utilities, without assuming drive letters.
    var java = PortableRuntime.JavaPath();
    if (!string.IsNullOrWhiteSpace(java)) {
        var home = Directory.GetParent(Path.GetDirectoryName(java)!)?.FullName;
        if (!string.IsNullOrWhiteSpace(home) && Directory.Exists(Path.Combine(home, "bin")))
            psi.Environment["JAVA_HOME"] = home;
        var javaBin = Path.GetDirectoryName(java)!;
        var existing = psi.Environment.TryGetValue("PATH", out var current) ? current ?? "" : "";
        if (!existing.Split(';', StringSplitOptions.RemoveEmptyEntries).Contains(javaBin, StringComparer.OrdinalIgnoreCase))
            psi.Environment["PATH"] = javaBin + ";" + existing;
    }
    var python = PortableRuntime.PythonPath();
    if (!string.IsNullOrWhiteSpace(python) && Path.GetFileName(python).Equals("python.exe", StringComparison.OrdinalIgnoreCase))
        psi.Environment["PYSPARK_PYTHON"] = python;
    var hadoop = PortableRuntime.HadoopHome();
    if (!string.IsNullOrWhiteSpace(hadoop)) {
        psi.Environment["HADOOP_HOME"] = hadoop;
        var bin = Path.Combine(hadoop, "bin");
        var path = psi.Environment.TryGetValue("PATH", out var value) ? value ?? "" : "";
        if (!path.Split(';', StringSplitOptions.RemoveEmptyEntries).Contains(bin, StringComparer.OrdinalIgnoreCase))
            psi.Environment["PATH"] = bin + ";" + path;
    }
}
