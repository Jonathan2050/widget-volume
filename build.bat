@echo off
rem Construit dist\WidgetVolume.exe (crée l'environnement virtuel si besoin).
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe (
    py -3 -m venv .venv || exit /b 1
)
.venv\Scripts\python.exe -m pip install -q -r requirements.txt || exit /b 1

.venv\Scripts\pyinstaller.exe --noconfirm --clean --onefile --windowed ^
    --name WidgetVolume main.py || exit /b 1

echo.
echo Executable : %~dp0dist\WidgetVolume.exe
