using PhoneBox.Agent;
using Xunit;

/// <summary>An agent started from a packaged app (Claude Desktop) kept its layout in the package's LocalCache.</summary>
public class PackageSandboxTests : IDisposable
{
    private readonly string _packages = Path.Combine(Path.GetTempPath(), "pb-packages-" + Guid.NewGuid().ToString("N"));

    public void Dispose()
    {
        try { Directory.Delete(_packages, true); } catch (DirectoryNotFoundException) { }
    }

    private string Cached(string package, string relative, string name)
    {
        var dir = Path.Combine(_packages, package, "LocalCache", "Roaming", relative);
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, name);
        File.WriteAllText(path, "{}");
        return path;
    }

    [Fact]
    public void TheProbeNamesThePackageItLandedIn()
    {
        Directory.CreateDirectory(Path.Combine(_packages, "Other_abc"));
        Cached("Claude_pzs8sxrjxfjjc", "PhoneBox", ".package-probe-1");
        Assert.Equal(Path.Combine(_packages, "Claude_pzs8sxrjxfjjc"), PackageSandbox.FindProbe(_packages, "PhoneBox", ".package-probe-1"));
    }

    [Fact]
    public void NoProbeOrNoPackagesFolderIsNoRedirect()
    {
        Cached("Claude_pzs8sxrjxfjjc", "PhoneBox", "config.json");
        Assert.Null(PackageSandbox.FindProbe(_packages, "PhoneBox", ".package-probe-1"));
        Assert.Null(PackageSandbox.FindProbe(Path.Combine(_packages, "missing"), "PhoneBox", ".package-probe-1"));
    }

    [Fact]
    public void OnlyCopiesNewerThanTheRealSettingsAreReported()
    {
        var newer = Cached("Claude_pzs8sxrjxfjjc", "PhoneBox", "config.json");
        var older = Cached("Other_abc", "PhoneBox", "config.json");
        var real = new DateTime(2026, 11, 21, 22, 56, 0, DateTimeKind.Utc);
        File.SetLastWriteTimeUtc(newer, real.AddHours(2));
        File.SetLastWriteTimeUtc(older, real.AddHours(-2));
        Assert.Equal([newer], PackageSandbox.NewerCopies(_packages, Path.Combine("PhoneBox", "config.json"), real));
        Assert.Equal([newer, older], PackageSandbox.NewerCopies(_packages, Path.Combine("PhoneBox", "config.json"), DateTime.MinValue).Order());
    }

    [Theory]
    [InlineData("--port", "--port")]
    [InlineData(@"C:\Program Files\PhoneBox\PhoneBoxAgent.exe", "\"C:\\Program Files\\PhoneBox\\PhoneBoxAgent.exe\"")]
    [InlineData("", "\"\"")]
    [InlineData(@"C:\dir with space\", "\"C:\\dir with space\\\\\"")]
    [InlineData("say \"hi\"", "\"say \\\"hi\\\"\"")]
    [InlineData(@"a\\""b", "\"a\\\\\\\\\\\"b\"")]
    public void ArgumentsAreQuotedTheWayWindowsSplitsThem(string arg, string quoted) =>
        Assert.Equal(quoted, PackageSandbox.Quote(arg));

    [Fact]
    public void TheCommandLineKeepsEveryArgument() =>
        Assert.Equal("\"C:\\Program Files\\PhoneBoxAgent.exe\" --port 8766 --outside-package",
            PackageSandbox.CommandLine(@"C:\Program Files\PhoneBoxAgent.exe", ["--port", "8766", PackageSandbox.RelaunchedFlag]));
}
