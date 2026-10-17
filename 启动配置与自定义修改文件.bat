@echo off
cd /d "%~dp0"
set "PY=%~dp0..\..\..\.venv\Scripts\pythonw.exe"
if not exist "%PY%" set "PY=pythonw"
start "" "%PY%" "%~dp0modifier_gui.pyw"
