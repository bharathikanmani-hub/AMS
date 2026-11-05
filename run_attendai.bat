@echo off
REM AttendAI launcher (Windows). Double-click to start.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3 -m venv .venv || goto :fail
)
call ".venv\Scripts\activate.bat"

echo Installing / checking requirements...
python -m pip install -q -r requirements.txt || goto :fail

if not exist ".env" (
  echo.
  echo [!] .env not found. Copy .env.example to .env and fill in your MySQL details first.
  goto :fail
)
if not exist "frontend_dist\index.html" (
  echo.
  echo [!] frontend_dist\ not found - the React app has not been built/copied yet.
  echo     The API will still run; run build_frontend.bat first.
)

echo.
echo Starting AttendAI at http://127.0.0.1:5000 ...
start "" "http://127.0.0.1:5000"
python run.py
goto :eof

:fail
echo.
echo Setup stopped - see the message above.
pause
