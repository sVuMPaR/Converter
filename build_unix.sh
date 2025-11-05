#!/usr/bin/env bash
# Unix build script for PyInstaller (Linux / macOS)
# Usage:
#   python -m venv venv
#   source venv/bin/activate
#   pip install -r requirements.txt pyinstaller
#   chmod +x build_unix.sh
#   ./build_unix.sh

MAIN="main.py"
NAME="converter"
ICON="assets/icon.icns" # set .icns for macOS, .png ignored by pyinstaller for icon on linux

QT_PLUGINS=$(python - <<PY
import os, importlib
try:
    m = importlib.import_module('PyQt5')
    print(os.path.join(os.path.dirname(m.__file__), 'Qt', 'plugins'))
except Exception:
    print('')
PY
)

if [ -n "$QT_PLUGINS" ]; then
    pyinstaller --noconfirm --onefile --windowed --name "$NAME" --icon "$ICON" --add-data "$QT_PLUGINS:PyQt5/Qt/plugins" "$MAIN"
else
    pyinstaller --noconfirm --onefile --windowed --name "$NAME" --icon "$ICON" "$MAIN"
fi

echo "Build finished. Dist dir: dist/$NAME"
