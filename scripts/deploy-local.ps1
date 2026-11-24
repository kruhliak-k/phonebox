<#
.SYNOPSIS
  Builds this PC's own PhoneBox from the my-build branch and installs it, without ever dropping a feature.

.DESCRIPTION
  Use this instead of install.ps1, setup.ps1 or copying files by hand. It:
    1. Refuses to build when the working tree has uncommitted changes, or when any local branch (or any branch on the
       "fork" remote) has a commit that my-build doesn't contain. Merge that branch into my-build first, or list it in
       scripts/deploy-local.ignore with the reason (for a branch whose work landed in another form).
    2. Runs the agent tests (skip with -SkipTests) and publishes the agent like install.ps1 does.
    3. Installs it, together with the helper scripts in local/, from a process started through WMI. That process runs
       outside any packaged app: started from Claude Desktop (an MSIX app), plain file copies into %APPDATA% and
       %LOCALAPPDATA% land in the package's LocalCache, which Windows never sees after a reboot.
    4. Restarts the agent and checks that it answers.

.PARAMETER Branch
  The branch that holds every feature this PC runs. Default: my-build.
.PARAMETER SkipTests
  Do not run the agent tests before installing.
.PARAMETER DryRun
  Only run the checks and say what would be installed.
#>
param(
    [string]$Branch = 'my-build',
    [switch]$SkipTests,
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
function Invoke-Git { & git -C $root @args; if ($LASTEXITCODE) { throw "git $args failed" } }
function Write-Step([string]$Text) { Write-Host ''; Write-Host "==> $Text" -ForegroundColor Cyan }

# ---- 1. nothing may be left out ------------------------------------------------------------------------------------
Write-Step "Checking that $Branch holds every feature"
$current = (Invoke-Git rev-parse --abbrev-ref HEAD).Trim()
if ($current -ne $Branch) { throw "Switch to $Branch first (git switch $Branch); this checkout is on $current." }
$dirty = Invoke-Git status --porcelain
if ($dirty) { throw "Commit (or stash) these changes first, so the next build can't lose them:`n$($dirty -join "`n")" }

$ignoreFile = Join-Path $PSScriptRoot 'deploy-local.ignore'
$ignored = if (Test-Path $ignoreFile) {
    Get-Content $ignoreFile | ForEach-Object { ($_ -split '#')[0].Trim() } | Where-Object { $_ }
} else { @() }

# best effort: a branch pushed from elsewhere counts too (BatchMode: never wait for an SSH passphrase)
$env:GIT_SSH_COMMAND = 'ssh -o BatchMode=yes -o ConnectTimeout=10'
try { & git -C $root fetch fork --quiet 2>$null } catch { Write-Host '    (could not fetch the fork remote; checking the branches known here)' }
$refs = Invoke-Git for-each-ref --format='%(refname:short)' refs/heads refs/remotes/fork
$missing = @()
foreach ($ref in $refs) {
    $name = $ref -replace '^fork/', ''
    if ($ref -eq 'fork/HEAD' -or $name -eq $Branch -or $ignored -contains $name -or $ignored -contains $ref) { continue }
    # "+" = a commit whose change isn't in HEAD under any hash (cherry-picks and rebases count as present)
    $absent = Invoke-Git cherry HEAD $ref | Where-Object { $_ -like '+*' }
    foreach ($line in $absent) { $missing += "  $ref  $(Invoke-Git log -1 --format='%h %s' $line.Substring(2))" }
}
if ($missing) {
    throw ("These commits are not in ${Branch}; merge their branches (git merge <branch>) or list the branch in " +
        "scripts/deploy-local.ignore:`n" + ($missing -join "`n"))
}
$commit = (Invoke-Git log -1 --format='%h %s').Trim()
Write-Host "    OK  $Branch at $commit"
if ($DryRun) { Write-Host '    Dry run: nothing built or installed.'; return }

# ---- 2. build -------------------------------------------------------------------------------------------------------
if (-not $SkipTests) {
    Write-Step 'Running the agent tests'
    dotnet test (Join-Path $root 'agent\PhoneBox.Agent.Tests') --nologo -v q
    if ($LASTEXITCODE) { throw 'Tests failed; nothing was installed.' }
}
Write-Step 'Publishing the agent'
$stage = Join-Path $root '.deploy-stage'
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
dotnet publish (Join-Path $root 'agent\PhoneBox.Agent') -c Release -f net10.0-windows10.0.19041.0 -o "$stage\app" --nologo -v q --disable-build-servers
if ($LASTEXITCODE) { throw 'dotnet publish failed; nothing was installed.' }
Copy-Item (Join-Path $root 'local') "$stage\local" -Recurse
$included = Invoke-Git for-each-ref --merged HEAD --format='%(refname:short)' refs/heads
Set-Content "$stage\app\BUILD.txt" -Encoding utf8 -Value @(
    "branch: $Branch", "commit: $(Invoke-Git rev-parse HEAD)", "built: $(Get-Date -Format s)", 'branches included:'
    $included | ForEach-Object { "  $_" })

# ---- 3. install outside any package ------------------------------------------------------------------------------
Write-Step 'Installing (outside any packaged app)'
$log = "$stage\install.log"
$installer = Join-Path $PSScriptRoot 'deploy-local.install.ps1'
$cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$installer`" -Stage `"$stage`" -Log `"$log`""
$started = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cmd }
if ($started.ReturnValue -ne 0) { throw "Could not start the installer (Win32_Process.Create returned $($started.ReturnValue))" }
$deadline = (Get-Date).AddMinutes(3)
while (Get-Process -Id $started.ProcessId -ErrorAction SilentlyContinue) {
    if ((Get-Date) -gt $deadline) { throw "The installer is still running after 3 minutes; see $log" }
    Start-Sleep -Milliseconds 500
}
if (Test-Path $log) { Get-Content $log | ForEach-Object { Write-Host "    $_" } }
if (-not (Select-String -Path $log -Pattern '^DONE' -Quiet)) { throw "The installer did not finish; see $log" }

# ---- 4. check ---------------------------------------------------------------------------------------------------
Write-Step 'Waiting for the agent'
$deadline = (Get-Date).AddSeconds(40)
do {
    try { if ((Invoke-WebRequest http://127.0.0.1:8765/ -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { break } } catch { }
    Start-Sleep 1
} while ((Get-Date) -lt $deadline)
if ((Get-Date) -ge $deadline) { throw 'The agent did not answer on http://127.0.0.1:8765 within 40 s.' }
Write-Host "    OK  PhoneBox from $Branch ($commit) is running"
