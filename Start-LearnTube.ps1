param([switch]$NoBrowser, [switch]$Check)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendRoot = Join-Path $projectRoot 'backend'
$frontendRoot = Join-Path $projectRoot 'frontend'
$pythonPath = Join-Path $backendRoot '.venv\Scripts\python.exe'
$vitePath = Join-Path $frontendRoot 'node_modules\vite\bin\vite.js'
$runtimeRoot = Join-Path $backendRoot '.runtime'
$statePath = Join-Path $runtimeRoot 'processes.json'
$apiUrl = 'http://127.0.0.1:8001/api/health'
$uiUrl = 'http://127.0.0.1:5173/'

function Show-Error([string]$message) {
    if ($Check) { Write-Error $message; return }
    (New-Object -ComObject WScript.Shell).Popup($message, 0, 'LearnTube could not start', 16) | Out-Null
}

function Test-Ready([string]$url, [string]$expected) {
    try {
        $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content.Contains($expected)
    } catch { return $false }
}

function Test-Port([int]$port) {
    $socket = New-Object System.Net.Sockets.TcpClient
    try {
        $attempt = $socket.ConnectAsync('127.0.0.1', $port)
        return $attempt.Wait(500) -and $socket.Connected
    } catch { return $false }
    finally { $socket.Dispose() }
}

function Wait-Ready([string]$url, [string]$expected) {
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if (Test-Ready $url $expected) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Python environment missing in backend\.venv.' }
    if (-not (Test-Path -LiteralPath $vitePath)) { throw 'Frontend packages missing. Run npm install in frontend first.' }
    $nodePath = (Get-Command node.exe -ErrorAction Stop).Source
    if ($Check) {
        Write-Output 'LearnTube dependencies are ready.'
        exit 0
    }

    New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
    $inputPath = Join-Path $runtimeRoot 'stdin.txt'
    if (-not (Test-Path -LiteralPath $inputPath)) { New-Item -ItemType File -Path $inputPath | Out-Null }
    $state = @{ apiPid = $null; uiPid = $null }
    if (Test-Path -LiteralPath $statePath) {
        try {
            $previous = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            $state.apiPid = $previous.apiPid
            $state.uiPid = $previous.uiPid
        } catch { }
    }

    if (-not (Test-Ready $apiUrl 'ok')) {
        if (Test-Port 8001) { throw 'Port 8001 is in use by another service.' }
        $api = Start-Process -FilePath $pythonPath -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8001' -WorkingDirectory $backendRoot -WindowStyle Hidden -RedirectStandardInput $inputPath -RedirectStandardOutput (Join-Path $runtimeRoot 'api.out.log') -RedirectStandardError (Join-Path $runtimeRoot 'api.err.log') -PassThru
        $state.apiPid = $api.Id
        $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        if (-not (Wait-Ready $apiUrl 'ok')) { throw "API did not start. Check backend\.runtime\api.err.log." }
    }

    if (-not (Test-Ready $uiUrl '<title>LearnTube</title>')) {
        if (Test-Port 5173) { throw 'Port 5173 is in use by another service.' }
        $viteArgs = @('"' + $vitePath + '"', '--host', '127.0.0.1', '--port', '5173', '--strictPort')
        $tailscale = Get-Command tailscale.exe -ErrorAction SilentlyContinue
        if (-not $tailscale -and (Test-Path -LiteralPath 'C:\Program Files\Tailscale\tailscale.exe')) {
            $tailscale = @{ Source = 'C:\Program Files\Tailscale\tailscale.exe' }
        }
        if ($tailscale) {
            try {
                $tailnet = & $tailscale.Source status --json 2>$null | ConvertFrom-Json
                if ($tailnet.BackendState -eq 'Running' -and $tailnet.Self.DNSName) {
                    $env:__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS = $tailnet.Self.DNSName.TrimEnd('.')
                    $mobileEnv = Join-Path $frontendRoot '.env.mobile'
                    if (-not (Test-Path -LiteralPath $mobileEnv)) {
                        Copy-Item -LiteralPath (Join-Path $frontendRoot 'mobile.env.template') -Destination $mobileEnv
                    }
                    $viteArgs += @('--config', 'vite.mobile.config.ts', '--mode', 'mobile')
                }
            } catch { } # PC access remains available when Tailscale is disconnected.
        }
        $ui = Start-Process -FilePath $nodePath -ArgumentList $viteArgs -WorkingDirectory $frontendRoot -WindowStyle Hidden -RedirectStandardInput $inputPath -RedirectStandardOutput (Join-Path $runtimeRoot 'ui.out.log') -RedirectStandardError (Join-Path $runtimeRoot 'ui.err.log') -PassThru
        $state.uiPid = $ui.Id
        $state | ConvertTo-Json | Set-Content -LiteralPath $statePath -Encoding UTF8
        if (-not (Wait-Ready $uiUrl '<title>LearnTube</title>')) { throw "Frontend did not start. Check backend\.runtime\ui.err.log." }
    }

    if (-not $NoBrowser) { Start-Process $uiUrl }
} catch {
    Show-Error $_.Exception.Message
    exit 1
}
