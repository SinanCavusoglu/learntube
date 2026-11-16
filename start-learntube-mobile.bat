@echo off
setlocal
set "PROJECT_ROOT=%~dp0"
set "TAILSCALE_EXE=C:\Program Files\Tailscale\tailscale.exe"

if not exist "%TAILSCALE_EXE%" (
  echo Tailscale is not installed. Install it from https://tailscale.com/download/windows
  pause
  exit /b 1
)

for /f "delims=" %%H in ('powershell -NoProfile -Command "$s = & '%TAILSCALE_EXE%' status --json 2>$null | ConvertFrom-Json; if ($s.BackendState -eq 'Running') { $s.Self.DNSName.TrimEnd('.') }"') do set "TAILNET_HOST=%%H"
if not defined TAILNET_HOST (
  echo Sign in to Tailscale on this PC before starting LearnTube Mobile.
  pause
  exit /b 1
)

powershell -NoProfile -Command "if (Get-NetTCPConnection -State Listen -LocalPort 5173,8001 -ErrorAction SilentlyContinue) { exit 1 }"
if errorlevel 1 (
  echo Port 5173 or 8001 is already in use. Close the existing LearnTube windows first.
  pause
  exit /b 1
)

if not exist "%PROJECT_ROOT%frontend\.env.mobile" copy /y "%PROJECT_ROOT%frontend\mobile.env.template" "%PROJECT_ROOT%frontend\.env.mobile" >nul
set "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS=%TAILNET_HOST%"

echo Starting LearnTube for private access at https://%TAILNET_HOST%/
start "LearnTube API" cmd /k "cd /d ""%PROJECT_ROOT%backend"" && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001"
timeout /t 2 /nobreak >nul
start "LearnTube Mobile UI" cmd /k "cd /d ""%PROJECT_ROOT%frontend"" && npm.cmd run dev -- --config vite.mobile.config.ts --mode mobile --host 127.0.0.1"

echo Keep both LearnTube windows open and this PC awake.
echo Open https://%TAILNET_HOST%/ in Safari after connecting your iPhone to Tailscale.
pause
endlocal
