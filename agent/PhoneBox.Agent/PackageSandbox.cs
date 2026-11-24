namespace PhoneBox.Agent;

/// <summary>
/// Windows: an agent started from a packaged (MSIX) app — a Claude Desktop session, for one — inherits that app's file
/// virtualization. Its writes to %APPDATA% and %LOCALAPPDATA% land in
/// <c>%LOCALAPPDATA%\Packages\&lt;package&gt;\LocalCache\Roaming|Local</c>, so it keeps a settings file of its own there,
/// while the copy the Startup shortcut starts after a reboot reads the real %APPDATA%\PhoneBox and shows another layout.
/// The process has no package identity (GetCurrentPackageFullName says none), so the redirect is found with a probe file,
/// and the agent hands over to a copy started through WMI, which runs outside the package.
/// </summary>
public static class PackageSandbox
{
    /// <summary>Passed to the copy started outside, so a redirect that is still there doesn't start another one.</summary>
    public const string RelaunchedFlag = "--outside-package";

    private static string Packages =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData, Environment.SpecialFolderOption.DoNotVerify), "Packages");

    private static string Roaming =>
        Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData, Environment.SpecialFolderOption.DoNotVerify);

    /// <summary>
    /// The package folder this process's writes to <paramref name="dir"/> (a folder under %APPDATA%) land in, or null when
    /// they reach the real folder. Writes a probe file there and looks for it in each package's LocalCache\Roaming.
    /// </summary>
    public static string? RedirectedTo(string dir)
    {
        if (!OperatingSystem.IsWindows()) return null;
        var relative = Path.GetRelativePath(Roaming, dir);
        if (relative.StartsWith("..", StringComparison.Ordinal) || Path.IsPathRooted(relative)) return null;
        var probe = $".package-probe-{Guid.NewGuid():N}";
        var probePath = Path.Combine(dir, probe);
        try
        {
            Directory.CreateDirectory(dir);
            File.WriteAllBytes(probePath, []);
            return FindProbe(Packages, relative, probe);
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { return null; }
        finally { try { File.Delete(probePath); } catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { } }
    }

    /// <summary>The package whose LocalCache\Roaming\<paramref name="relative"/> holds <paramref name="probe"/>.</summary>
    internal static string? FindProbe(string packagesDir, string relative, string probe)
    {
        if (!Directory.Exists(packagesDir)) return null;
        foreach (var package in Directory.EnumerateDirectories(packagesDir))
            if (File.Exists(Path.Combine(package, "LocalCache", "Roaming", relative, probe))) return package;
        return null;
    }

    /// <summary>
    /// Settings left in a package's LocalCache by an agent that ran inside it, newer than <paramref name="realConfig"/>:
    /// the layout the user last edited may be there, not in the file this agent reads.
    /// </summary>
    public static IReadOnlyList<string> NewerCopies(string realConfig)
    {
        if (!OperatingSystem.IsWindows()) return [];
        var relative = Path.GetRelativePath(Roaming, realConfig);
        if (relative.StartsWith("..", StringComparison.Ordinal) || Path.IsPathRooted(relative)) return [];
        try { return NewerCopies(Packages, relative, File.Exists(realConfig) ? File.GetLastWriteTimeUtc(realConfig) : DateTime.MinValue); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { return []; }
    }

    internal static IReadOnlyList<string> NewerCopies(string packagesDir, string relative, DateTime realWritten)
    {
        if (!Directory.Exists(packagesDir)) return [];
        return Directory.EnumerateDirectories(packagesDir)
            .Select(p => Path.Combine(p, "LocalCache", "Roaming", relative))
            .Where(f => File.Exists(f) && File.GetLastWriteTimeUtc(f) > realWritten)
            .ToList();
    }

    /// <summary>
    /// Starts <paramref name="exe"/> with <paramref name="args"/> through WMI (Win32_Process.Create), whose processes
    /// run outside the package. Null when it started, otherwise why not.
    /// </summary>
    public static string? StartOutside(string exe, IEnumerable<string> args)
    {
        if (!OperatingSystem.IsWindows()) return "not Windows";
        try
        {
            var locatorType = Type.GetTypeFromProgID("WbemScripting.SWbemLocator");
            if (locatorType is null) return "WMI is not available";
            dynamic locator = Activator.CreateInstance(locatorType)!;
            dynamic service = locator.ConnectServer(".", @"root\cimv2");
            dynamic process = service.Get("Win32_Process");
            dynamic input = process.Methods_.Item("Create").InParameters.SpawnInstance_();
            input.Properties_.Item("CommandLine").Value = CommandLine(exe, args);
            input.Properties_.Item("CurrentDirectory").Value = AppContext.BaseDirectory;
            dynamic output = process.ExecMethod_("Create", input);
            var code = Convert.ToInt32(output.Properties_.Item("ReturnValue").Value, System.Globalization.CultureInfo.InvariantCulture);
            return code == 0 ? null : $"Win32_Process.Create returned {code}";
        }
        catch (Exception ex) { return ex.Message; }
    }

    /// <summary>A Windows command line that CommandLineToArgvW / the .NET runtime split back into exactly these arguments.</summary>
    internal static string CommandLine(string exe, IEnumerable<string> args) =>
        string.Join(' ', new[] { exe }.Concat(args).Select(Quote));

    internal static string Quote(string arg)
    {
        if (arg.Length > 0 && arg.IndexOfAny([' ', '\t', '\n', '\v', '"']) < 0) return arg;
        var sb = new System.Text.StringBuilder("\"");
        var slashes = 0;
        foreach (var c in arg)
        {
            if (c == '\\') { slashes++; continue; }
            // backslashes before a quote are doubled, and the quote escaped; elsewhere they stay as they are
            sb.Append('\\', c == '"' ? slashes * 2 + 1 : slashes).Append(c);
            slashes = 0;
        }
        return sb.Append('\\', slashes * 2).Append('"').ToString();
    }
}
