param([switch]$ResetData)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot 'apps/api/.venv/Scripts/python.exe'
$env:DATABASE_URL = 'postgresql+psycopg://demo:demo@localhost:5432/jwg_campus_experience'
$env:PYTHONPATH = Join-Path $projectRoot 'apps/api'
$env:DEMO_CLOCK_FILE = Join-Path $projectRoot 'tmp/campus-experience-clock.json'
$env:JWG_API_TARGET = 'http://127.0.0.1:8001'
New-Item -ItemType Directory -Path (Join-Path $projectRoot 'tmp') -Force | Out-Null
foreach ($port in @(8001,5174)) {
    if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
        throw "体验端口 $port 已被占用，请先检查现有体验进程。"
    }
}
Push-Location (Join-Path $projectRoot 'apps/api')
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw '体验库迁移失败；请先创建 jwg_campus_experience 数据库。' }
} finally { Pop-Location }
if ($ResetData) {
    & $python -c 'from app.core.clock import build_clock,Clock; c=build_clock(); now=Clock("Asia/Shanghai").now(); c.offset=now.replace(hour=18,minute=0,second=0,microsecond=0)-now'
    if ($LASTEXITCODE -ne 0) { throw '设置体验时钟失败。' }
    & $python -m app.db.experience --reset
    if ($LASTEXITCODE -ne 0) { throw '生成千人体验数据失败，服务未启动。' }
}
$apiProcess = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--app-dir','apps/api','--port','8001','--reload','--reload-dir','apps/api/app') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'tmp/campus-api.log' -RedirectStandardError 'tmp/campus-api-error.log'
$vite = Join-Path $projectRoot 'apps/web/node_modules/vite/bin/vite.js'
$webProcess = Start-Process -FilePath 'node.exe' -ArgumentList @('"'+$vite+'"','--host','127.0.0.1','--port','5174','--strictPort') -WorkingDirectory (Join-Path $projectRoot 'apps/web') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'tmp/campus-web.log') -RedirectStandardError (Join-Path $projectRoot 'tmp/campus-web-error.log')
$workerProcess = Start-Process -FilePath $python -ArgumentList @('-m','app.worker.main','--interval','5') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'tmp/campus-worker.log' -RedirectStandardError 'tmp/campus-worker-error.log'
@{api=$apiProcess.Id;web=$webProcess.Id;worker=$workerProcess.Id;database='jwg_campus_experience';url='http://127.0.0.1:5174'} | ConvertTo-Json | Set-Content -LiteralPath 'tmp/campus-experience-processes.json' -Encoding utf8
Write-Output '千人体验入口：http://127.0.0.1:5174；进程及日志保存在 tmp/campus-*。'
