# Working on this fork

This checkout is the owner's personal PhoneBox: upstream is `origin` (ersinkoc/phonebox), the fork is `fork`.

## One branch holds everything this PC runs: `my-build`

- Build each feature on its own branch from `main` (that branch is what goes upstream as a PR).
- When it works, merge it into `my-build`. Never build or install the agent from a feature branch: a build from one
  branch silently drops every feature that lives only on another (that is how Telegram, the lock sync and the notes
  sync went missing).
- Commit before deploying. Uncommitted work is not in the next build.

## Installing on this PC: `scripts/deploy-local.ps1` only

```powershell
git switch my-build
.\scripts\deploy-local.ps1          # -DryRun: only the checks; -SkipTests: no tests
```

It refuses to install while any local or `fork/` branch has a commit that `my-build` lacks (merge it, or list the
branch in `scripts/deploy-local.ignore` with the reason), then tests, publishes, installs the agent and the helper
scripts in `local/`, and restarts everything. Don't use `install.ps1`, `setup.ps1` or hand copies here.

## Claude Desktop sessions: files in AppData are virtualized

Claude Desktop is a packaged (MSIX) app. Whatever its sessions write under `%APPDATA%` or `%LOCALAPPDATA%` (copies,
new files, Startup shortcuts) lands in `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\...`, which only processes started
from Claude see; after a reboot Windows uses the real folders, where those files don't exist. Deletions of existing real
files do reach the real folders. So:

- Install only through `scripts/deploy-local.ps1`: it does the AppData part in a process started through WMI
  (`Win32_Process.Create`), which runs outside the package.
- To read real AppData files from a session, copy them out with a WMI-started `cmd /c copy ... D:\...` first.
- Don't stop/start `PhoneBoxAgent.exe` from a session by hand: an agent started inside the package uses the package's
  copy of the settings. Run the deploy script.

## Helper scripts: `local/`

`lock-follow.pyw` and `notes-sync.pyw` run beside the agent (see `local/README.md`). Change them in `local/` and deploy;
never edit only the copies in `%LOCALAPPDATA%\PhoneBox`.
