@echo off
REM Builds the React app and copies it to frontend_dist\ so Flask can serve it.
REM Needs Node.js 22 (https://nodejs.org). Run once, and again after changing the frontend.
cd /d "%~dp0frontend"

where node >nul 2>nul || ( echo [!] Node.js is not installed. Install Node 22 from https://nodejs.org and run this again. & goto :fail )
where pnpm >nul 2>nul || ( echo Installing pnpm... & call npm install -g pnpm || goto :fail )

call pnpm install || goto :fail
call pnpm build || goto :fail

cd /d "%~dp0"
if exist "frontend_dist" rmdir /s /q "frontend_dist"
xcopy /e /i /y "frontend\dist" "frontend_dist" >nul || goto :fail
echo.
echo Frontend built. Now run run_attendai.bat
pause
goto :eof

:fail
echo.
echo Build stopped - see the message above.
pause
