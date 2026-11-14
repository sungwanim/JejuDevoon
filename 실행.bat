@echo off
chcp 65001 >nul
cd /d "%~dp0backend"
if exist "..\.venv\Scripts\python.exe" (set PY="..\.venv\Scripts\python.exe") else (set PY=python)
%PY% -m jejuagent %*
if errorlevel 1 (echo.
echo 실행에 실패했습니다. Python 3.14 설치와 README의 설치 단계를 확인하세요.
pause)
