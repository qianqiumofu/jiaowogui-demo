param(
    [ValidatePattern('^[a-z][a-z0-9_]*$')][string]$DatabaseName = 'jwg_campus_experience',
    [string]$ClockFile = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$python = Join-Path $projectRoot 'apps/api/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw '请先按 data/demo/README.md 安装后端依赖。' }
$manifest = Get-Content -LiteralPath 'data/demo/campus-1000.manifest.json' -Raw -Encoding utf8 | ConvertFrom-Json
$snapshot = Join-Path $projectRoot 'data/demo/campus-1000.pgcustom'
$digest = (Get-FileHash -LiteralPath $snapshot -Algorithm SHA256).Hash.ToLowerInvariant()
if ($digest -ne $manifest.sha256) { throw '数据库快照校验失败，请重新下载完整文件。' }
# 只创建新体验库；若已存在则退出，绝不清空同学已有的修改。
docker exec jiaowogui-postgres createdb -U demo $DatabaseName
if ($LASTEXITCODE -ne 0) { throw '创建体验库失败；若库已存在，请直接启动，不要重复恢复。' }
docker cp $snapshot 'jiaowogui-postgres:/tmp/jwg-campus-1000-import.pgcustom'
if ($LASTEXITCODE -ne 0) { throw '复制数据库快照失败。' }
docker exec jiaowogui-postgres pg_restore -U demo -d $DatabaseName --no-owner --no-privileges --exit-on-error /tmp/jwg-campus-1000-import.pgcustom
if ($LASTEXITCODE -ne 0) { throw '数据库恢复失败；保留现场，不启动服务。' }
$studentCount = docker exec jiaowogui-postgres psql -U demo -d $DatabaseName -Atc 'SELECT count(*) FROM students'
if ($LASTEXITCODE -ne 0 -or $studentCount.Trim() -ne '1000') { throw '恢复后学生人数验证失败。' }
New-Item -ItemType Directory -Path (Join-Path $projectRoot 'tmp') -Force | Out-Null
$env:DEMO_CLOCK_FILE = if ($ClockFile) { [System.IO.Path]::GetFullPath($ClockFile) } else { Join-Path $projectRoot 'tmp/campus-experience-clock.json' }
$env:PYTHONPATH = Join-Path $projectRoot 'apps/api'
$env:DATABASE_URL = "postgresql+psycopg://demo:demo@localhost:5432/$DatabaseName"
Push-Location (Join-Path $projectRoot 'apps/api')
try {
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw '数据库已恢复，但增量迁移失败；保留现场，不启动服务。' }
} finally { Pop-Location }
& $python -m app.db.upgrade_demo_snapshot
if ($LASTEXITCODE -ne 0) { throw '数据库已恢复，但合成目录升级失败；保留现场，不启动服务。' }
& $python -c 'import json; from datetime import datetime; from pathlib import Path; from app.core.clock import build_clock,Clock; raw=json.loads(Path("data/demo/campus-1000.manifest.json").read_text(encoding="utf-8")); now=Clock("Asia/Shanghai").now(); build_clock().offset=datetime.fromisoformat(raw["server_clock"]["now"])-now'
if ($LASTEXITCODE -ne 0) { throw '数据库已恢复，但演示时钟恢复失败，请检查后端依赖。' }
Write-Output "已恢复 1000 人数据库与演示时钟；运行 ./scripts/start-campus-experience.ps1 -DatabaseName $DatabaseName -ClockFile `"$env:DEMO_CLOCK_FILE`" 启动，勿加 -ResetData。"
