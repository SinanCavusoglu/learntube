@echo off
setlocal
set "PROJECT_ROOT=%~dp0"

if not exist "%PROJECT_ROOT%backend\.venv\Scripts\python.exe" (
  echo Python environment missing: backend\.venv
  echo Run: cd backend ^&^& py -m venv .venv ^&^& .venv\Scripts\python.exe -m pip install -r requirements.txt
  exit /b 1
)
if not exist "%PROJECT_ROOT%frontend\node_modules\.bin\vite.cmd" (
  echo Frontend dependencies missing. Run: cd frontend ^&^& npm.cmd install
  exit /b 1
)
where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo npm.cmd was not found on PATH. Install Node.js or reopen your terminal.
  exit /b 1
)

if /I "%~1"=="--check" (
  echo LearnTube dependencies are ready.
  exit /b 0
)

call :backend_ready
if not errorlevel 1 (
  echo LearnTube API is already running.
  goto backend_ready_label
)
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>nul
if not errorlevel 1 (
  echo Port 8001 is occupied by another service. LearnTube API was not started.
  exit /b 1
)
echo Starting LearnTube API...
start "LearnTube API" cmd /k "cd /d ""%PROJECT_ROOT%backend"" && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001"
for /l %%I in (1,1,30) do (
  call :backend_ready
  if not errorlevel 1 goto backend_ready_label
  timeout /t 1 /nobreak >nul
)
echo LearnTube API did not become ready. Check the LearnTube API window.
exit /b 1

:backend_ready_label
call :frontend_ready
if not errorlevel 1 (
  echo LearnTube frontend is already running.
  goto frontend_ready_label
)
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 5173 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>nul
if not errorlevel 1 (
  echo Port 5173 is occupied by another service. LearnTube frontend was not started.
  exit /b 1
)
echo Starting LearnTube frontend...
start "LearnTube Frontend" cmd /k "cd /d ""%PROJECT_ROOT%frontend"" && npm.cmd run dev -- --host 127.0.0.1 --port 5173 --strictPort"
for /l %%I in (1,1,30) do (
  call :frontend_ready
  if not errorlevel 1 goto frontend_ready_label
  timeout /t 1 /nobreak >nul
)
echo LearnTube frontend did not become ready. Check the LearnTube Frontend window.
exit /b 1

:frontend_ready_label
if /I not "%~1"=="--no-browser" start "" http://127.0.0.1:5173
echo LearnTube is ready at http://127.0.0.1:5173
echo Close the LearnTube API and LearnTube Frontend windows to stop it.
exit /b 0

:backend_ready
curl.exe -fsS --max-time 2 http://127.0.0.1:8001/api/health 2>nul | findstr /C:"ok" >nul
exit /b %errorlevel%

:frontend_ready
curl.exe -fsS --max-time 2 http://127.0.0.1:5173/ 2>nul | findstr /C:"<title>LearnTube</title>" >nul
exit /b %errorlevel%
