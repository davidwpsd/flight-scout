@echo off
rem Flight Scout launcher for Windows. Batch files bypass the PowerShell
rem execution policy, so this works even when .ps1 scripts are blocked.
rem   run.cmd              -> http://127.0.0.1:8777   (only this computer)
rem   run.cmd 9000         -> custom port
rem   run.cmd --share      -> open to the local network so colleagues can join
setlocal

set "PORT=8777"
set "SHARE="
if /I "%~1"=="--share" (
    set "SHARE=--host 0.0.0.0"
) else if not "%~1"=="" (
    set "PORT=%~1"
)

set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
if exist "%PY%" goto run

set "PY="
where py.exe >nul 2>nul && set "PY=py.exe"
if not defined PY where python.exe >nul 2>nul && set "PY=python.exe"
if not defined PY (
    echo [x] Python 3.10+ not found. Install it, or run: python flightscout.py serve
    exit /b 1
)

:run
echo Using Python: %PY%
"%PY%" "%~dp0flightscout.py" serve --port %PORT% %SHARE%
