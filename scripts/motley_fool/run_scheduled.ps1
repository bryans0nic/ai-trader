# Do NOT set $ErrorActionPreference = "Stop" here: our Python logger writes
# normal INFO lines to stderr by design, and with ErrorActionPreference=Stop,
# PowerShell treats the first stderr line from a native process as a fatal
# terminating error -- aborting the script even though Python is running fine.
$ErrorActionPreference = "Continue"
# PS 7.3+ also wraps a native command's stderr lines as ErrorRecords by default
# (adding "CategoryInfo"/"NativeCommandError" boilerplate into redirected output).
# Since our Python logger's stderr output is normal, not an error, disable that.
$PSNativeCommandUseErrorActionPreference = $false

$repoDir = "C:\Users\Bryan\Dropbox (Personal)\5.0 Projects & Hobbies\Coding\GitHub Repos\ai-trader"
$uvExe = "C:\Users\Bryan\.local\bin\uv.exe"
$logDir = Join-Path $repoDir "data\motley_fool\logs"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "scheduler.log"

Set-Location $repoDir

Add-Content -Path $logFile -Encoding utf8 -Value "===== Run started $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ====="

# 2>&1 merges stderr into the success stream as plain strings (avoiding the
# ErrorRecord/NativeCommandError wrapping that `*>>` file redirection causes),
# then Out-File writes with explicit utf8 to match Add-Content's encoding.
& $uvExe run python scripts\motley_fool\ai_reconcile.py 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8
$exitCode = $LASTEXITCODE

Add-Content -Path $logFile -Encoding utf8 -Value "===== Run finished $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') (exit code $exitCode) ====="
exit $exitCode
