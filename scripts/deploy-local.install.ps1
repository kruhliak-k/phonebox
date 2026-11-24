<#
  Started by deploy-local.ps1 through WMI, so it runs outside any packaged app and its writes reach the real
  %APPDATA% / %LOCALAPPDATA%. Don't run it from a Claude Desktop session directly.
#>
param([Parameter(Mandatory)][string]$Stage, [Parameter(Mandatory)][string]$Log)

$ErrorActionPreference = 'Stop'
function Out-Log([string]$Text) { Add-Content -Path $Log -Value $Text -Encoding utf8 }
Set-Content -Path $Log -Value "installer started $(Get-Date -Format s)" -Encoding utf8

try {
    $home_ = Join-Path $env:LOCALAPPDATA 'PhoneBox'
    $app = Join-Path $home_ 'app'
    $startup = [Environment]::GetFolderPath('Startup')

    # Helper scripts from local/: file -> Startup shortcut name. telegram-bridge.pyw stays out: the agent's own
    # Telegram notifications replaced it, and both together would show every message twice.
    $helpers = [ordered]@{ 'lock-follow.pyw' = 'PhoneBox Lock'; 'notes-sync.pyw' = 'PhoneBox Notes' }

    # stop the agent, the helpers it replaces and adb (an adb server orphaned by a killed agent stops answering)
    Get-Process PhoneBoxAgent -ErrorAction SilentlyContinue | Stop-Process -Force
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $cl = $_.CommandLine; $helpers.Keys | Where-Object { $cl -like "*$_*" } } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-Process adb -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep 2
    Out-Log 'stopped the agent, its helpers and adb'

    # keep the previous install, then copy the new one over it
    $backup = Join-Path $home_ 'app.previous'
    if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
    if (Test-Path $app) { Copy-Item $app $backup -Recurse }
    New-Item -ItemType Directory -Force $app | Out-Null
    Copy-Item "$Stage\app\*" $app -Recurse -Force
    Out-Log "agent installed to $app (previous one in $backup)"

    Copy-Item "$Stage\local\*" $home_ -Force
    $pythonw = Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\pythonw.exe" -ErrorAction SilentlyContinue |
        Sort-Object { [version]($_.VersionInfo.ProductVersion -replace '[^\d.].*$', '') } -Descending | Select-Object -First 1
    if (-not $pythonw) { Out-Log 'WARNING: no Python in %LOCALAPPDATA%\Programs\Python; helper scripts not started' }
    $shell = New-Object -ComObject WScript.Shell
    foreach ($file in $helpers.Keys) {
        $script = Join-Path $home_ $file
        if (-not $pythonw) { break }
        $lnk = $shell.CreateShortcut((Join-Path $startup "$($helpers[$file]).lnk"))
        $lnk.TargetPath = $pythonw.FullName
        $lnk.Arguments = "-I `"$script`""
        $lnk.WorkingDirectory = $home_
        $lnk.Save()
        Start-Process $pythonw.FullName -ArgumentList '-I', "`"$script`"" -WorkingDirectory $home_
        Out-Log "helper $file started and in Startup"
    }

    Start-Process (Join-Path $app 'PhoneBoxAgent.exe') -WorkingDirectory $app
    Out-Log 'agent started'
    Out-Log 'DONE'
}
catch { Out-Log "FAILED: $_" }
