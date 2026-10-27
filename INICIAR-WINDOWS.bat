@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto :error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :error
)
echo Abre http://127.0.0.1:8093/manager/
echo Password de demostracion: emby-demo-003
".venv\Scripts\python.exe" scripts\run_manager.py
if errorlevel 1 goto :error
exit /b 0
:error
echo No se pudo iniciar. Revisa Python 3.11+ y docs\INSTALLATION.md.
pause
exit /b 1
