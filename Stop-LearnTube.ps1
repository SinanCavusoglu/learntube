$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$statePath = Join-Path $projectRoot 'backend\.runtime\processes.json'
if (-not (Test-Path -LiteralPath $statePath)) { exit 0 }

try {
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    foreach ($entry in @(@('uiPid', 'frontend\node_modules\vite\bin\vite.js'), @('apiPid', 'backend\.venv\Scripts\python.exe'))) {
        $processId = $state.($entry[0])
        if (-not $processId) { continue }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        $expected = Join-Path $projectRoot $entry[1]
        if ($process.CommandLine -and $process.CommandLine.Contains($expected)) {
            & taskkill.exe /PID $processId /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "Could not stop LearnTube process $processId." }
        }
    }
    Remove-Item -LiteralPath $statePath -Force
} catch {
    [Console]::Error.WriteLine($_.ToString())
    [Console]::Error.WriteLine($_.ScriptStackTrace)
    (New-Object -ComObject WScript.Shell).Popup($_.Exception.Message, 0, 'LearnTube could not stop', 16) | Out-Null
    exit 1
}
