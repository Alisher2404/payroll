@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 goto fail
)
.venv\Scripts\python.exe -c "import streamlit, pandas, openpyxl, reportlab, pyarrow, tzdata" >nul 2>&1
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install -r requirements.txt
  if errorlevel 1 goto fail
)
.venv\Scripts\pythonw.exe launcher.py --address 127.0.0.1 --port 8501
exit /b
:fail
echo Installation failed. Install Python 3.11 or newer and check Internet connection.
pause
