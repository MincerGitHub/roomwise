$ErrorActionPreference='Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) { python -m venv .venv; if ($LASTEXITCODE) {throw 'Python环境创建失败'} }
& ./.venv/Scripts/python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE) {throw 'Python依赖安装失败'}
Push-Location frontend
try { npm ci --cache .npm-cache; if ($LASTEXITCODE) {throw '前端依赖安装失败'}; npm run build; if ($LASTEXITCODE) {throw '网页构建失败'} } finally { Pop-Location }
Write-Host '安装完成。运行 start.ps1 或双击 start.bat。'
