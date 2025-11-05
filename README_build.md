```markdown
# Сборка исполняемого файла (PyInstaller)

Краткие шаги для сборки .exe (Windows) или для сборки на Unix-подобных систем.

1) Подготовка окружения
   python -m venv venv
   source venv/bin/activate        # Linux / macOS
   venv\Scripts\activate           # Windows
   pip install -r requirements.txt
   pip install pyinstaller

2) Быстрая команда (Windows, в активированном venv):
   pyinstaller --noconfirm --onefile --windowed --name converter --icon assets\\icon.ico main.py

3) Если PyInstaller не подхватывает Qt-плагины, определите путь к плагинам:
   python -c "import PyQt5, os; print(os.path.join(os.path.dirname(PyQt5.__file__), 'Qt', 'plugins'))"
   и добавьте --add-data "<path_to_plugins>;PyQt5/Qt/plugins"

4) После сборки результат будет в dist/converter (если --onefile — в dist/converter(.exe))
   Проверьте запуск и drag-and-drop, форматы изображений и отсутствие ошибок про missing plugins.

5) Частые проблемы
   - Ошибка про 'xcb' на Linux: установите системные зависимости (на Ubuntu: libxcb-xinerama0 и т.п.).
   - PyInstaller может не включить все плагины: используйте --add-data или spec-файл.
   - Для macOS лучше собирать .app (onedir) и подписывать приложение.

6) CI
   В репозитории уже есть workflow для сборки на windows-latest и загрузки артефакта (см. .github/workflows/build-windows.yml).
```
