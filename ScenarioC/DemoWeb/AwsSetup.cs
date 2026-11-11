using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;

// Local-machine demo integration. Never persist AWS credentials, passwords, tokens, or access keys.
// Profile credentials remain under the logged-in Windows user's AWS CLI credential store.
public sealed record AwsSetupOptions(
    string Profile = "default",
    string Region = "ap-southeast-2",
    string S3Bucket = "",
    string S3Prefix = "ssis-migrations/",
    string GlueRole = "",
    string BedrockModel = "amazon.nova-lite-v1:0",
    string LoginMethod = "login"
);

public static class AwsSetup
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web) { WriteIndented = true };
    private static readonly SemaphoreSlim Gate = new(1, 1);
    private static readonly Regex ProfilePattern = new(@"^[a-zA-Z0-9_-]{1,64}$", RegexOptions.Compiled);
    private static readonly Regex RegionPattern = new(@"^[a-z]{2}(?:-gov)?-[a-z0-9-]+-\d$", RegexOptions.Compiled);
    private static readonly Regex BucketPattern = new(@"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$", RegexOptions.Compiled);
    private static readonly Regex PrefixPattern = new(@"^[a-zA-Z0-9!_.*'()/-]{0,512}$", RegexOptions.Compiled);
    private static readonly Regex RolePattern = new(@"^(?:[a-zA-Z0-9+=,.@_/-]{1,128}|arn:aws(?:-us-gov|-cn)?:iam::\d{12}:role/[a-zA-Z0-9+=,.@_/-]{1,512})$", RegexOptions.Compiled);
    private static readonly Regex ModelPattern = new(@"^[a-zA-Z0-9.:_/-]{3,200}$", RegexOptions.Compiled);

    private static string StorePath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".ssis_glue_demo", "aws-setup.json");

    public static bool Configured => File.Exists(StorePath);

    public static AwsSetupOptions Read(IConfiguration configuration)
    {
        var d = configuration.GetSection("AwsSetup").Get<AwsSetupOptions>() ?? new AwsSetupOptions();
        if (!Configured) return d;
        try { return JsonSerializer.Deserialize<AwsSetupOptions>(File.ReadAllText(StorePath), Json) ?? d; }
        catch (Exception) { return d; }
    }

    public static string Validate(AwsSetupOptions x)
    {
        if (!ProfilePattern.IsMatch(x.Profile ?? "")) return "Profile must contain 1–64 letters, digits, underscores or hyphens.";
        if (!RegionPattern.IsMatch(x.Region ?? "")) return "Invalid AWS region.";
        if (!string.IsNullOrEmpty(x.S3Bucket) && (!BucketPattern.IsMatch(x.S3Bucket) || x.S3Bucket.Contains("..") || Regex.IsMatch(x.S3Bucket, @"^\d+\.\d+\.\d+\.\d+$"))) return "Invalid S3 bucket name.";
        if (!PrefixPattern.IsMatch(x.S3Prefix ?? "") || (x.S3Prefix ?? "").StartsWith('/')) return "Invalid S3 prefix.";
        if (!string.IsNullOrEmpty(x.GlueRole) && !RolePattern.IsMatch(x.GlueRole)) return "Invalid Glue execution role name or ARN.";
        if (!ModelPattern.IsMatch(x.BedrockModel ?? "")) return "Invalid Bedrock model identifier.";
        if (x.LoginMethod is not ("login" or "sso")) return "Choose AWS browser login or IAM Identity Center (SSO).";
        return "";
    }

    public static async Task Save(AwsSetupOptions value)
    {
        var error = Validate(value);
        if (error.Length > 0) throw new ArgumentException(error);
        await Gate.WaitAsync();
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(StorePath)!);
            var tmp = StorePath + ".tmp";
            await File.WriteAllTextAsync(tmp, JsonSerializer.Serialize(value, Json));
            File.Move(tmp, StorePath, overwrite: true);
        }
        finally { Gate.Release(); }
    }

    public static void StartLogin(AwsSetupOptions cfg)
    {
        if (!OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Browser login launcher currently supports local Windows installations only.");
        var error = Validate(cfg);
        if (error.Length > 0) throw new ArgumentException(error);
        // The wizard region must also be persisted to the SELECTED CLI profile.
        // `aws login` prompts for a Region on profiles without one even when the
        // Migration Forge UI already knows the selected region. Configure the
        // non-secret CLI profile region before launching browser authentication.
        // Strict Validate() allowlists for Profile and Region prevent shell tokens.
        // `&&` ensures we never continue to browser login if configuration fails.
        var signIn = cfg.LoginMethod == "sso"
            ? $"aws sso login --profile {cfg.Profile} --region {cfg.Region}"
            : $"aws login --profile {cfg.Profile} --region {cfg.Region}";
        var command = $"aws configure set region {cfg.Region} --profile {cfg.Profile} && {signIn}";
        // Keep this console interactive for the AWS-hosted browser/MFA flow.
        var p = new ProcessStartInfo("cmd.exe") { UseShellExecute = true, CreateNoWindow = false };
        p.ArgumentList.Add("/k");
        p.ArgumentList.Add(command);
        Process.Start(p);
    }

    private static async Task<(bool ok, string message, string output)> RunAws(
        AwsSetupOptions cfg, CancellationToken ct, params string[] args)
    {
        try
        {
            using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
            timeout.CancelAfter(TimeSpan.FromSeconds(18));
            var p = new ProcessStartInfo("aws") {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            foreach (var arg in args) p.ArgumentList.Add(arg);
            p.ArgumentList.Add("--profile"); p.ArgumentList.Add(cfg.Profile);
            p.ArgumentList.Add("--region"); p.ArgumentList.Add(cfg.Region);
            p.ArgumentList.Add("--no-cli-pager");
            p.Environment["AWS_PAGER"] = "";
            using var process = Process.Start(p) ?? throw new InvalidOperationException("AWS CLI could not start");
            var stdout = process.StandardOutput.ReadToEndAsync(timeout.Token);
            var stderr = process.StandardError.ReadToEndAsync(timeout.Token);
            await process.WaitForExitAsync(timeout.Token);
            var output = await stdout;
            var error = await stderr;
            if (process.ExitCode == 0) return (true, "OK", output);
            // Do not send raw CLI stderr to the browser: it may contain sensitive local details.
            var reason = error.Contains("LoginRefreshRequired", StringComparison.OrdinalIgnoreCase) ||
                error.Contains("ExpiredToken", StringComparison.OrdinalIgnoreCase) ||
                error.Contains("Token has expired", StringComparison.OrdinalIgnoreCase)
                ? "AWS session expired; choose Reconnect."
                : error.Contains("AccessDenied", StringComparison.OrdinalIgnoreCase) ||
                  error.Contains("UnauthorizedOperation", StringComparison.OrdinalIgnoreCase)
                ? "AWS permission denied for this check."
                : error.Contains("Unable to locate credentials", StringComparison.OrdinalIgnoreCase) ||
                  error.Contains("profile", StringComparison.OrdinalIgnoreCase)
                ? "AWS profile not authenticated or not configured. Connect or configure this profile first."
                : "AWS command unsuccessful. Confirm profile, network, region, and AWS permissions.";
            return (false, reason, "");
        }
        catch (OperationCanceledException) { return (false, "AWS CLI request timed out.", ""); }
        catch (System.ComponentModel.Win32Exception) { return (false, "AWS CLI v2 is not installed or not on PATH.", ""); }
        catch (Exception) { return (false, "AWS CLI invocation failed.", ""); }
    }

    // Lists resources discoverable from the selected profile/region; presence in the
    // catalogue is not proof of permission to invoke a model. No model is invoked.
    public static async Task<object> ListBedrockChoices(AwsSetupOptions cfg, CancellationToken ct)
    {
        var problem = Validate(cfg);
        if (problem.Length > 0) throw new ArgumentException(problem);
        var foundations = await RunAws(cfg, ct, "bedrock", "list-foundation-models", "--output", "json");
        var profiles = await RunAws(cfg, ct, "bedrock", "list-inference-profiles", "--output", "json");
        var choices = new List<object>();
        var textModels = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (foundations.ok)
        {
            try
            {
                using var doc = JsonDocument.Parse(foundations.output);
                if (doc.RootElement.TryGetProperty("modelSummaries", out var items) && items.ValueKind == JsonValueKind.Array)
                    foreach (var item in items.EnumerateArray())
                    {
                        string id = GetString(item, "modelId");
                        if (id.Length == 0 || !IsTextModel(item)) continue;
                        textModels.Add(id);
                        bool onDemand = item.TryGetProperty("inferenceTypesSupported", out var types) &&
                            types.ValueKind == JsonValueKind.Array &&
                            types.EnumerateArray().Any(x => x.ValueKind == JsonValueKind.String && x.GetString() == "ON_DEMAND");
                        var status = item.TryGetProperty("modelLifecycle", out var lifecycle) ? GetString(lifecycle, "status") : "";
                        if (!onDemand || (status.Length > 0 && status != "ACTIVE")) continue;
                        choices.Add(new { id, label = GetString(item, "modelName") + " — direct model", kind = "foundation" });
                    }
            }
            catch (JsonException) { return new { ok = false, error = "AWS returned an invalid foundation-model catalog.", choices }; }
        }
        if (profiles.ok)
        {
            try
            {
                using var doc = JsonDocument.Parse(profiles.output);
                if (doc.RootElement.TryGetProperty("inferenceProfileSummaries", out var items) && items.ValueKind == JsonValueKind.Array)
                    foreach (var item in items.EnumerateArray())
                    {
                        string id = GetString(item, "inferenceProfileId");
                        if (id.Length == 0 || GetString(item, "status") != "ACTIVE") continue;
                        // The matching foundation model can be absent from a Region's direct
                        // catalog while still being available through cross-Region inference.
                        // Keep active profiles; the UI identifies them distinctly.
                        string name = GetString(item, "inferenceProfileName");
                        string type = GetString(item, "type");
                        choices.Add(new { id, label = (name.Length == 0 ? id : name) + " — inference profile", kind = "profile", profileType = type });
                    }
            }
            catch (JsonException) { return new { ok = false, error = "AWS returned an invalid inference-profile catalog.", choices }; }
        }
        return new { ok = foundations.ok || profiles.ok, profile = cfg.Profile, region = cfg.Region,
            choices, foundationModelsListed = foundations.ok, inferenceProfilesListed = profiles.ok,
            message = foundations.ok && profiles.ok ? "Models available for discovery; invocation and Converse compatibility must still be verified."
                : "Some catalogs could not be read. Check Bedrock read permissions or reconnect to AWS. Discovery does not prove invocation permission." };
    }

    private static string GetString(JsonElement item, string key) =>
        item.TryGetProperty(key, out var value) && value.ValueKind == JsonValueKind.String ? value.GetString() ?? "" : "";

    private static bool IsTextModel(JsonElement item)
    {
        static bool ContainsText(JsonElement element, string key) =>
            element.TryGetProperty(key, out var modalities) && modalities.ValueKind == JsonValueKind.Array &&
            modalities.EnumerateArray().Any(m => m.ValueKind == JsonValueKind.String && m.GetString() == "TEXT");
        return ContainsText(item, "inputModalities") && ContainsText(item, "outputModalities");
    }

    public static async Task<object> Test(AwsSetupOptions cfg, CancellationToken ct)
    {
        var problem = Validate(cfg);
        if (problem.Length > 0) throw new ArgumentException(problem);
        var sts = await RunAws(cfg, ct, "sts", "get-caller-identity", "--output", "json");
        if (!sts.ok) return new { connected = false, profile = cfg.Profile, region = cfg.Region, message = sts.message };
        string account;
        string identity;
        try
        {
            using var doc = JsonDocument.Parse(sts.output);
            account = doc.RootElement.GetProperty("Account").GetString() ?? "unknown";
            identity = doc.RootElement.GetProperty("Arn").GetString() ?? "unknown";
        }
        catch (JsonException) { return new { connected = false, message = "AWS identity response was invalid." }; }

        // Connection checks are non-destructive and never start jobs or invoke billed models.
        var s3 = string.IsNullOrWhiteSpace(cfg.S3Bucket)
            ? (ok: false, message: "No S3 bucket configured", output: "")
            : await RunAws(cfg, ct, "s3api", "head-bucket", "--bucket", cfg.S3Bucket);
        var glue = await RunAws(cfg, ct, "glue", "list-jobs", "--max-results", "1", "--output", "json");
        var bedrock = await RunAws(cfg, ct, "bedrock", "list-foundation-models", "--output", "json");
        return new {
            connected = true, account, identity, profile = cfg.Profile, region = cfg.Region,
            checks = new {
                s3 = new { ok = s3.ok, message = s3.message },
                glue = new { ok = glue.ok, message = glue.message },
                bedrockCatalog = new { ok = bedrock.ok, message = bedrock.message,
                    note = "Catalog access does not prove the selected model can be invoked." }
            },
            notice = "Identity verified. Service checks are read-only; deployment, role pass-through and model invocation still require appropriate permissions."
        };
    }
}
