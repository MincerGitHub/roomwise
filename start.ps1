param([int]$Port=8765,[switch]$OpenBrowser)
$ErrorActionPreference='Stop'
$taskRoot=$PSScriptRoot
$python=Join-Path $taskRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw '缺少Python环境。先运行 setup.ps1。' }
if (-not (Test-Path -LiteralPath (Join-Path $taskRoot 'frontend/dist/index.html'))) { throw '缺少网页构建。先运行 setup.ps1 或在frontend运行 npm run build。' }
$url="http://127.0.0.1:$Port"
$healthy=$false
try { $r=Invoke-RestMethod "$url/api/health" -TimeoutSec 2; $healthy=$r.status -eq 'ok' } catch { }
if (-not $healthy) {
    $logs=Join-Path $taskRoot 'runtime'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    $process=Start-Process -FilePath $python -WorkingDirectory $taskRoot -ArgumentList @('-m','uvicorn','roomwise.main:app','--app-dir','backend','--host','127.0.0.1','--port',"$Port") -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs 'server.log') -RedirectStandardError (Join-Path $logs 'server-error.log') -PassThru
    $process.Id | Set-Content -LiteralPath (Join-Path $logs 'server.pid') -Encoding ASCII
    for ($n=0;$n -lt 35;$n++) {
        Start-Sleep -Milliseconds 400
        try { $r=Invoke-RestMethod "$url/api/health" -TimeoutSec 2; if ($r.status -eq 'ok') {$healthy=$true;break} } catch { }
        if ($process.HasExited) { throw '服务启动失败，请查看runtime/server-error.log。' }
    }
    if (-not $healthy) { throw '服务启动超时，请查看runtime/server-error.log。' }
}
Write-Host "归置 Roomwise 已运行：$url"
Write-Host '数据保存于本机runtime目录；关闭网页不会删除方案。'
if ($OpenBrowser) { Start-Process $url }
