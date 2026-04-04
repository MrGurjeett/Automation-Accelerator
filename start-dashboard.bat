@echo off
echo ============================================================
echo   Automation Accelerator Dashboard
echo ============================================================
echo.

REM Check if node_modules exist for frontend
if not exist "dashboard\frontend\node_modules" (
    echo [1/3] Installing frontend dependencies...
    cd dashboard\frontend
    npm install
    cd ..\..
) else (
    echo [1/3] Frontend dependencies already installed.
)

REM Check if FastAPI is installed
python -c "import fastapi" 2>NUL
if errorlevel 1 (
    echo [2/3] Installing backend dependencies...
    pip install -r dashboard\requirements.txt
) else (
    echo [2/3] Backend dependencies already installed.
)

echo [3/3] Starting services...
echo.

REM Start backend
start "Dashboard Backend" cmd /k "python -m dashboard --port 8200"

REM Wait a moment for backend to start
timeout /t 2 /nobreak >NUL

REM Start frontend dev server
start "Dashboard Frontend" cmd /k "cd dashboard\frontend && npm run dev"

echo.
echo   Backend:  http://localhost:8200  (API + WebSocket)
echo   Frontend: http://localhost:5173  (React Dev Server)
echo   API Docs: http://localhost:8200/docs
echo.
echo   Both servers are running in separate windows.
echo   Press Ctrl+C in each window to stop.
echo ============================================================
pause
