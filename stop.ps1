$ErrorActionPreference='Stop'
$taskPidFile=Join-Path $PSScriptRoot 'runtime/server.pid'
if (-not (Test-Path -LiteralPath $taskPidFile)) { Write-Host 'No recorded Roomwise process.'; exit 0 }
$taskPid=[int](Get-Content -LiteralPath $taskPidFile -Raw)
$taskProcess=Get-CimInstance Win32_Process -Filter "ProcessId=$taskPid" -ErrorAction SilentlyContinue
if (-not $taskProcess) { Write-Host 'Recorded process has already stopped.'; exit 0 }
if ($taskProcess.CommandLine -notmatch 'uvicorn' -or $taskProcess.CommandLine -notmatch 'roomwise.main:app') { throw 'Process identity mismatch; no process was stopped.' }
$taskChildren=Get-CimInstance Win32_Process -Filter "ParentProcessId=$taskPid" | Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'roomwise.main:app' }
foreach ($taskChild in $taskChildren) { Stop-Process -Id $taskChild.ProcessId -ErrorAction SilentlyContinue }
Stop-Process -Id $taskPid -ErrorAction SilentlyContinue
Write-Host 'Roomwise stopped. Saved projects remain in runtime.'
