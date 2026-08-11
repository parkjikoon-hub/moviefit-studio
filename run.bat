@echo off
REM ============================================================
REM  MovieFit Studio launcher
REM
REM  IMPORTANT: This file must stay ASCII-only.
REM  cmd.exe cannot read Korean text inside a .bat file reliably
REM  (it garbles the lines and treats them as commands).
REM  All Korean messages live in tools/launch.py instead.
REM ============================================================
chcp 65001 > nul
title MovieFit Studio
cd /d "%~dp0"

python --version > nul 2>&1
if errorlevel 1 goto NOPYTHON

python tools\launch.py
goto END

:NOPYTHON
echo.
echo   [ERROR] Python was not found. / Python(파이썬)을 찾을 수 없습니다.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$f='tools\messages\no_python.txt'; if (Test-Path $f) { Get-Content -Path $f -Encoding UTF8 | ForEach-Object { Write-Host $_ } }"
echo.
pause
exit /b 1

:END
echo.
pause
