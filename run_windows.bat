@echo off
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py
%PY% --version >nul 2>nul || (
    echo Python nao encontrado. Instale em https://www.python.org/downloads/ marcando "Add Python to PATH".
    pause
    exit /b 1
)
if not exist .venv\Scripts\activate.bat (
    echo Criando ambiente virtual...
    %PY% -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
echo.
echo CastFin em http://127.0.0.1:5000  (Ctrl+C para parar)
python app.py
pause
