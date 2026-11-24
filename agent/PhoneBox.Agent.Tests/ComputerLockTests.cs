using PhoneBox.Agent;
using Xunit;

public sealed class ComputerLockTests
{
    [Fact]
    public void WindowsReadsTheSessionLockState()
    {
        if (!OperatingSystem.IsWindows()) return;
        Assert.True(ComputerLock.Supported);
        // Any session (a signed-in desktop or a CI service session) has a known state; null means the struct was misread.
        var locked = ComputerLock.IsLocked();
        Assert.NotNull(locked);
        // PHONEBOX_EXPECT_UNLOCKED=1 when the tests run on an unlocked desktop: checks the flag offsets, not just the call.
        if (Environment.GetEnvironmentVariable("PHONEBOX_EXPECT_UNLOCKED") == "1") Assert.False(locked);
    }
}
