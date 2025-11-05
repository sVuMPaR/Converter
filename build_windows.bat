@echo off
REM Windows build script for PyInstaller (run inside activated venv)
REM Usage: open cmd, activate venv, run build_windows.bat

SET MAIN=main.py
SET NAME=converter
SET ICON=assets\icon.ico

REM Install pyinstaller if needed:
REM pip install pyinstaller

REM Try to detect PyQt5 plugins path and pass to pyinstaller
python - <<PY
import os, sys, importlib
try:
    m = importlib.import_module('PyQt5')
    qt_path = os.path.join(os.path.dirname(m.__file__), 'Qt', 'plugins')
    print(qt_path)
except Exception:
    print('')
PY > _qt_plugins_path.txt

set /p QT_PLUGINS=<_qt_plugins_path.txt
del _qt_plugins_path.txt

if defined QT_PLUGINS (
    pyinstaller --noconfirm --onefile --windowed --name %NAME% --icon "%ICON%" --add-data "%QT_PLUGINS%;PyQt5/Qt/plugins" "%MAIN%"
) else (
    pyinstaller --noconfirm --onefile --windowed --name %NAME% --icon "%ICON%" "%MAIN%"
)

echo Build finished. Dist dir: dist\%NAME%
pause
