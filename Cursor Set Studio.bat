@echo off
rem Launch Cursor Set Studio using the project's virtual environment.
rem pythonw.exe runs it without a console window behind the app.

setlocal
set "HERE=%~dp0"

if not exist "%HERE%.venv\Scripts\pythonw.exe" (
    echo The virtual environment is missing.
    echo.
    echo Create it once with:
    echo     python -m venv .venv
    echo     .venv\Scripts\python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

start "" "%HERE%.venv\Scripts\pythonw.exe" "%HERE%cursor_set_studio\main.py"
endlocal
