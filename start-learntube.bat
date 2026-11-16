@echo off
setlocal
set "PROJECT_ROOT=%~dp0"

echo Starting LearnTube API and frontend...
start "LearnTube API" cmd /k "cd /d ""%PROJECT_ROOT%backend"" && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001"
timeout /t 2 /nobreak >nul
start "LearnTube Frontend" cmd /k "cd /d ""%PROJECT_ROOT%frontend"" && npm.cmd run dev"
timeout /t 3 /nobreak >nul
start "" http://localhost:5173

echo LearnTube is starting at http://localhost:5173
echo Keep the two LearnTube command windows open while using the app.
endlocal
