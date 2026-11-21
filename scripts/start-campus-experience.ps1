param(
    [switch]$ResetData,
    [ValidatePattern('^[a-z][a-z0-9_]*$')][string]$DatabaseName = 'jwg_campus_experience',
    [string]$ClockFile = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot 'apps/api/.venv/Scripts/python.exe'
$env:DATABASE_URL = "postgresql+psycopg://demo:demo@localhost:5432/$DatabaseName"
$env:PYTHONPATH = Join-Path $projectRoot 'apps/api'
$env:DEMO_CLOCK_FILE = if ($ClockFile) { [System.IO.Path]::GetFullPath($ClockFile) } else { Join-Path $projectRoot 'tmp/campus-experience-clock.json' }
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
$apiProcess = Start-Process -FilePath $python -ArgumentList @('-m','uvicorn','app.main:app','--app-dir','apps/api','--port','8001') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'tmp/campus-api.log' -RedirectStandardError 'tmp/campus-api-error.log'
$vite = Join-Path $projectRoot 'apps/web/node_modules/vite/bin/vite.js'
$webProcess = Start-Process -FilePath 'node.exe' -ArgumentList @('"'+$vite+'"','--host','127.0.0.1','--port','5174','--strictPort') -WorkingDirectory (Join-Path $projectRoot 'apps/web') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $projectRoot 'tmp/campus-web.log') -RedirectStandardError (Join-Path $projectRoot 'tmp/campus-web-error.log')
$workerProcess = Start-Process -FilePath $python -ArgumentList @('-m','app.worker.main','--interval','5') -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput 'tmp/campus-worker.log' -RedirectStandardError 'tmp/campus-worker-error.log'
$started = @($apiProcess,$webProcess,$workerProcess)
try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        foreach ($child in $started) {
            $child.Refresh()
            if ($child.HasExited) { throw "体验进程 $($child.Id) 已退出，请检查 tmp/campus-*-error.log。" }
        }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8001/healthz' -TimeoutSec 2
            $page = Invoke-WebRequest 'http://127.0.0.1:5174' -TimeoutSec 2
            if ($health.database -eq 'ready' -and $page.StatusCode -eq 200) { $ready = $true; break }
        } catch { Start-Sleep -Milliseconds 250 }
    }
    if (-not $ready) { throw '启动超时或数据库不可用，请检查 tmp/campus-* 日志。' }
} catch {
    foreach ($child in $started) {
        if (-not $child.HasExited) { Stop-Process -Id $child.Id -ErrorAction SilentlyContinue }
    }
    throw
}
@{api=$apiProcess.Id;web=$webProcess.Id;worker=$workerProcess.Id;database=$DatabaseName;clock_file=$env:DEMO_CLOCK_FILE;url='http://127.0.0.1:5174'} | ConvertTo-Json | Set-Content -LiteralPath 'tmp/campus-experience-processes.json' -Encoding utf8
Write-Output '千人体验入口：http://127.0.0.1:5174；进程及日志保存在 tmp/campus-*。'
