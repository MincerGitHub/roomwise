param([int]$Port=8765,[switch]$OpenBrowser)
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
$python=$env:ROOMWISE_PYTHON
if (-not $python) {
    $conda=Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($conda) {
        $environments=(& $conda.Source env list --json | ConvertFrom-Json).envs
        $roomwiseEnv=$environments | Where-Object { (Split-Path $_ -Leaf) -eq 'roomwise' } | Select-Object -First 1
        if ($roomwiseEnv) { $python=Join-Path $roomwiseEnv 'python.exe' }
    }
}
if (-not $python) { $python=Join-Path $taskRoot '.venv/Scripts/python.exe' }
if (-not (Test-Path -LiteralPath $python)) { throw '缺少Python环境。请使用现有 roomwise conda 环境，或设置 ROOMWISE_PYTHON 指向其 python.exe。' }
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'frontend/dist/index.html'))) { throw '缺少网页构建。先运行 setup.ps1 或在frontend运行 npm run build。' }
$url="http://127.0.0.1:$Port"
$healthy=$false
try { $r=Invoke-RestMethod "$url/api/health" -TimeoutSec 2; $healthy=$r.status -eq 'ok' -and $r.application -eq 'roomwise' } catch { }
if (-not $healthy -and (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)) { throw "端口 $Port 已被其他服务或旧版本占用。不会停止该进程；请使用 -Port 8768 等空闲端口。" }
if (-not $healthy) {
    $logs=Join-Path $taskRoot 'runtime'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $process=Start-Process -FilePath $python -WorkingDirectory $taskRoot -ArgumentList @('-m','uvicorn','roomwise.main:app','--app-dir','backend','--host','127.0.0.1','--port',"$Port") -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'server.log') -RedirectStandardError (Join-Path $logs 'server-error.log') -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $logs 'server.pid') -Encoding ASCII
    for ($n=0;$n -lt 35;$n++) {
        Start-Sleep -Milliseconds 400
        try { $r=Invoke-RestMethod "$url/api/health" -TimeoutSec 2; if ($r.status -eq 'ok' -and $r.application -eq 'roomwise') {$healthy=$true;break} } catch { }
        if ($process.HasExited) { throw '服务启动失败，请查看runtime/server-error.log。' }
    }
    if (-not $healthy) { throw '服务启动超时，请查看runtime/server-error.log。' }
}
Write-Host "归置 Roomwise 已运行：$url"
Write-Host '数据保存于本机runtime目录；关闭网页不会删除方案。'
if ($OpenBrowser) { Start-Process $url }
