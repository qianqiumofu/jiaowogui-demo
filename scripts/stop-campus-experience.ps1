$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$recordPath = Join-Path $projectRoot 'tmp/campus-experience-processes.json'
if (-not (Test-Path -LiteralPath $recordPath)) {
    Write-Output '没有记录中的体验进程。'
    exit 0
}
$record = Get-Content -LiteralPath $recordPath -Raw -Encoding utf8 | ConvertFrom-Json
$processes = @(Get-CimInstance Win32_Process)
$targets = [System.Collections.Generic.HashSet[int]]::new()
foreach ($kind in @('api','web','worker')) {
    $recordedId = [int]$record.$kind
    $process = $processes | Where-Object ProcessId -eq $recordedId | Select-Object -First 1
    if (-not $process) { continue }
    $command = [string]$process.CommandLine
    $expected = switch ($kind) {
        'api' { 'uvicorn app.main:app' }
        'web' { 'vite' }
        'worker' { 'app.worker.main' }
    }
    if (-not $command.Contains($projectRoot) -or -not $command.Contains($expected)) {
        throw "PID $recordedId 已不属于本项目的 $kind 进程，拒绝停止。"
    }
    [void]$targets.Add($recordedId)
}
# Windows 的 Python 启动器、旧 --reload 会产生子进程，连同已确认的根一起关闭。
do {
    $before = $targets.Count
    foreach ($process in $processes) {
        if ($targets.Contains([int]$process.ParentProcessId)) { [void]$targets.Add([int]$process.ProcessId) }
    }
} while ($targets.Count -gt $before)
foreach ($targetId in $targets) {
    Stop-Process -Id $targetId -ErrorAction SilentlyContinue
}
Write-Output "已停止本项目记录的体验进程（$($targets.Count) 个），数据库与时钟保持原样。"
