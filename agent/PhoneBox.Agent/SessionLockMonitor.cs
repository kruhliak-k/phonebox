using System.Runtime.InteropServices;

namespace PhoneBox.Agent;

/// <summary>Follows the current macOS or Windows console session while the option is enabled.</summary>
public sealed class SessionLockMonitor(ConfigStore cfg, AdbReverse adb, ILogger<SessionLockMonitor> log) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        var warned = false;
        while (!ct.IsCancellationRequested)
        {
            try
            {
                if (cfg.Get().Display.FollowComputerLock && ComputerLock.Supported)
                {
                    var available = await adb.SyncSessionAsync(ct);
                    if (!available && !warned)
                    {
                        log.LogWarning("Lock sync is unavailable; start the agent in the signed-in desktop session");
                    }
                    warned = !available;
                }
                else
                {
                    await adb.ResetSessionAsync(ct);
                    warned = false;
                }
                await Task.Delay(TimeSpan.FromSeconds(1), ct);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { return; }
            catch (Exception ex)
            {
                log.LogWarning(ex, "Could not follow the computer lock");
                await Task.Delay(TimeSpan.FromSeconds(5), ct);
            }
        }
    }
}

/// <summary>The lock state of the session the agent runs in: true locked, false unlocked, null unknown.</summary>
internal static class ComputerLock
{
    public static bool Supported => OperatingSystem.IsMacOS() || OperatingSystem.IsWindows();

    public static bool? IsLocked() =>
        OperatingSystem.IsMacOS() ? MacSessionLock.IsLocked()
        : OperatingSystem.IsWindows() ? WindowsSessionLock.IsLocked()
        : null;
}

/// <summary>Reads the agent's own Windows session. A session that is not the active console one (switched user,
/// disconnected remote desktop) counts as locked: nobody sees this desktop.</summary>
internal static class WindowsSessionLock
{
    private const int WTSSessionInfoEx = 25;
    private const int WTSActive = 0;
    private const int WTS_SESSIONSTATE_LOCK = 0;
    private const int WTS_SESSIONSTATE_UNLOCK = 1;

    public static bool? IsLocked()
    {
        if (!OperatingSystem.IsWindows()) return null;
        if (!WTSQuerySessionInformationW(IntPtr.Zero, -1, WTSSessionInfoEx, out var buffer, out var bytes) || buffer == IntPtr.Zero)
            return null;
        try
        {
            // WTSINFOEXW: DWORD Level; then the union WTSINFOEX_LEVEL1_W { ULONG SessionId; WTS_CONNECTSTATE_CLASS SessionState;
            // LONG SessionFlags; ... LARGE_INTEGER ... }. The LARGE_INTEGERs align the union to 8 bytes, so it starts at offset 8.
            if (bytes < 20 || Marshal.ReadInt32(buffer, 0) != 1) return null;
            var state = Marshal.ReadInt32(buffer, 12);
            var flags = Marshal.ReadInt32(buffer, 16);
            if (state != WTSActive) return true;
            return flags switch
            {
                WTS_SESSIONSTATE_LOCK => true,
                WTS_SESSIONSTATE_UNLOCK => false,
                _ => null,
            };
        }
        finally { WTSFreeMemory(buffer); }
    }

    [DllImport("wtsapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool WTSQuerySessionInformationW(IntPtr server, int sessionId, int infoClass, out IntPtr buffer, out int bytes);
    [DllImport("wtsapi32.dll")]
    private static extern void WTSFreeMemory(IntPtr memory);
}

/// <summary>Reads the caller's window-server session. An absent lock key means unlocked.</summary>
internal static class MacSessionLock
{
    public static bool? IsLocked()
    {
        if (!OperatingSystem.IsMacOS()) return null;
        var session = CGSessionCopyCurrentDictionary();
        if (session == IntPtr.Zero) return null;
        try
        {
            var onConsole = GetBoolean(session, "kCGSSessionOnConsoleKey");
            var locked = GetBoolean(session, "CGSSessionScreenIsLocked");
            return onConsole == false || locked == true;
        }
        finally { CFRelease(session); }
    }

    private static bool? GetBoolean(IntPtr dictionary, string name)
    {
        var key = CFStringCreateWithCString(IntPtr.Zero, name, 0x08000100); // UTF-8
        if (key == IntPtr.Zero) return null;
        try
        {
            var value = CFDictionaryGetValue(dictionary, key);
            return value == IntPtr.Zero || CFGetTypeID(value) != CFBooleanGetTypeID()
                ? null : CFBooleanGetValue(value) != 0;
        }
        finally { CFRelease(key); }
    }

    [DllImport("/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")]
    private static extern IntPtr CGSessionCopyCurrentDictionary();
    [DllImport("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation", CharSet = CharSet.Ansi)]
    private static extern IntPtr CFStringCreateWithCString(IntPtr allocator, string text, uint encoding);
    [DllImport("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")]
    private static extern IntPtr CFDictionaryGetValue(IntPtr dictionary, IntPtr key);
    [DllImport("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")]
    private static extern nint CFGetTypeID(IntPtr value);
    [DllImport("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")]
    private static extern nint CFBooleanGetTypeID();
    [DllImport("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")]
    private static extern byte CFBooleanGetValue(IntPtr value);
    [DllImport("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")]
    private static extern void CFRelease(IntPtr value);
}
