import sys
import os
import logging
import tempfile
from pathlib import Path
from logging.handlers import RotatingFileHandler

from PIL import Image, UnidentifiedImageError
import pillow_heif
import traceback
import json
import urllib.request
import urllib.error
import webbrowser
import shutil

# Импорты PyQt5
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QFileDialog, QProgressBar,
    QMessageBox, QSpinBox, QCheckBox, QComboBox
)
from PyQt5.QtCore import pyqtSlot

# Константы версии и репозитория
REPO_OWNER = "sVuMPaR"
REPO_NAME = "Converter"

def detect_current_version() -> str:
    """
    Определяет текущую версию приложения:
    1) Если есть git-репозиторий — пробует взять последний тег через git.
    2) Если есть файл version.txt рядом с main.py / exe — читает из него.
    3) Иначе возвращает "0.0.0".
    """
    # 1. Попытка через git (если не в frozen-сборке и git доступен)
    try:
        if not getattr(sys, "frozen", False):
            from subprocess import check_output, CalledProcessError

            # Путь к корню проекта (папка, где лежит main.py)
            base_dir = Path(__file__).resolve().parent

            # git describe --tags --abbrev=0 даст последний тег (например, v1.0.3)
            cmd = ["git", "-C", str(base_dir), "describe", "--tags", "--abbrev=0"]
            tag = check_output(cmd, stderr=open(os.devnull, "wb")).decode("utf-8").strip()
            if tag:
                return tag  # вернем с префиксом v, parse_version это переварит
    except Exception:
        pass

    # 2. Попытка через файл version.txt (подходит для собранных exe)
    try:
        if getattr(sys, "frozen", False):
            base_dir = Path(sys.executable).resolve().parent
        else:
            base_dir = Path(__file__).resolve().parent

        version_file = base_dir / "version.txt"
        if version_file.is_file():
            v = version_file.read_text(encoding="utf-8").strip()
            if v:
                return v
    except Exception:
        pass

    # 3. Фоллбек
    return "0.0.0"


CURRENT_VERSION = detect_current_version()
GITHUB_API_LATEST = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/releases/latest"

SUPPORTED_FORMATS = ["JPG", "JPEG", "PNG", "WEBP", "BMP", "TIFF", "HEIC", "HEIF", "GIF", "ICO"]


# Настройка логирования
def setup_logging():
    logger = logging.getLogger()

    # Удаляем старые обработчики
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Определяем путь к логу
    if getattr(sys, "frozen", False):  # PyInstaller
        exe_dir = Path(sys.executable).parent
    else:
        exe_dir = Path(__file__).parent

    log_path = exe_dir / "converter.log"

    # Попытка создать файловый обработчик
    try:
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
            errors="replace"
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
        logger.info(f"Лог-файл: {log_path}")
    except (IOError, OSError) as e:
        print(f"[LOG] Не удалось открыть {log_path}: {e}")
        # Fallback на Temp
        temp_log = Path(tempfile.gettempdir()) / "converter.log"
        try:
            file_handler = RotatingFileHandler(
                str(temp_log),
                maxBytes=5 * 1024 * 1024,
                backupCount=1,
                encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logger.info(f"Лог перенаправлен в {temp_log}")
        except Exception as fallback_e:
            print(f"[LOG] Не удалось создать лог во временной папке: {fallback_e}")

    # Консольный обработчик
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)
    logger.addHandler(console_handler)

    # Информативные логи
    logger.info("Запуск конвертера изображений")
    logger.info(f"Python: {sys.version}")
    logger.info(f"Система: {sys.platform}")
    logger.debug("PATH: %s", os.environ.get("PATH"))


# Хук для необработанных исключений
def log_unhandled_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger = logging.getLogger()
    logger.critical("Необработанное исключение", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = log_unhandled_exception


# ===== Логика автообновления через GitHub =====

def parse_version(v: str):
    v = v.strip()
    if v.startswith("v") or v.startswith("V"):
        v = v[1:]
    parts = v.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return (0, 0, 0)


def is_newer_version(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def get_latest_release_info():
    logger = logging.getLogger(__name__)
    try:
        req = urllib.request.Request(
            GITHUB_API_LATEST,
            headers={"User-Agent": "Converter-Updater"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                logger.warning(f"GitHub API статус {resp.status}")
                return None
            data = json.loads(resp.read().decode("utf-8"))
            return data
    except urllib.error.URLError as e:
        logger.info(f"Не удалось проверить обновления (сеть): {e}")
    except Exception as e:
        logger.info(f"Ошибка при проверке обновлений: {e}", exc_info=True)
    return None


def check_for_updates(parent=None):
    """
    Проверяет GitHub Releases.
    Если есть новая версия — предлагает скачать и (для .exe) запустить.
    """
    logger = logging.getLogger(__name__)
    info = get_latest_release_info()
    if not info:
        return

    tag = info.get("tag_name") or ""
    latest_version = tag.strip()
    if not latest_version:
        return

    if not is_newer_version(latest_version, CURRENT_VERSION):
        logger.info(
            f"Текущая версия {CURRENT_VERSION} актуальна (последняя {latest_version})"
        )
        return

    logger.info(f"Доступна новая версия: {latest_version} (текущая {CURRENT_VERSION})")

    assets = info.get("assets") or []
    download_url = None
    asset_name = None

    # Ищем .exe для Windows с указанием windows в имени
    for a in assets:
        name = a.get("name", "").lower()
        if name.endswith(".exe") and "windows" in name:
            download_url = a.get("browser_download_url")
            asset_name = a.get("name")
            break

    # Если подходящий ассет не найден — предлагаем открыть страницу релиза
    if not download_url:
        html_url = info.get("html_url")
        if parent:
            res = QMessageBox.question(
                parent,
                "Доступно обновление",
                f"Доступна новая версия: {latest_version}\n"
                f"Открыть страницу релиза в браузере?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            if res == QMessageBox.Yes and html_url:
                webbrowser.open(html_url)
        else:
            if html_url:
                webbrowser.open(html_url)
        return

    # Спрашиваем пользователя, скачивать ли ассет
    if parent:
        res = QMessageBox.question(
            parent,
            "Доступно обновление",
            f"Доступна новая версия: {latest_version}\n"
            f"Файл: {asset_name}\n\n"
            f"Скачать и запустить обновление?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )
        if res != QMessageBox.Yes:
            return

    # Определяем путь для сохранения
    if getattr(sys, "frozen", False):
        base_dir = Path(sys.executable).parent
    else:
        base_dir = Path(__file__).parent

    target_path = base_dir / asset_name

    try:
        logger.info(f"Скачиваю обновление: {download_url} → {target_path}")
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "Converter-Updater"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp, open(target_path, "wb") as f:
            shutil.copyfileobj(resp, f)

        logger.info(f"Обновление скачано: {target_path}")

        # Пытаемся запустить .exe
        try:
            if sys.platform.startswith("win") and str(target_path).lower().endswith(".exe"):
                os.startfile(str(target_path))
                logger.info("Запущен установщик обновления")

                # Закрываем текущее приложение, чтобы не мешать обновлению
                if parent:
                    parent.close()
                sys.exit(0)
            else:
                # Если не .exe или не Windows — просто сообщаем путь
                if parent:
                    QMessageBox.information(
                        parent,
                        "Обновление скачано",
                        f"Файл обновления сохранён:\n{target_path}\n\n"
                        f"Запустите его вручную."
                    )
        except Exception as e:
            logger.error(f"Не удалось запустить обновление: {e}", exc_info=True)
            if parent:
                QMessageBox.warning(
                    parent,
                    "Ошибка запуска обновления",
                    f"Файл скачан:\n{target_path}\n\n"
                    f"Но не удалось запустить автоматически. Запустите вручную."
                )
    except Exception as e:
        logger.error(f"Ошибка скачивания обновления: {e}", exc_info=True)
        if parent:
            QMessageBox.warning(
                parent,
                "Ошибка обновления",
                f"Не удалось скачать обновление:\n{e}"
            )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Converter — Конвертер изображений")
        self.resize(900, 650)

        # Центральный виджет
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # Основной макет
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # Список файлов
        self.file_list = QListWidget()
        layout.addWidget(QLabel("Добавленные файлы:"))
        layout.addWidget(self.file_list)

        # Настройки
        settings_layout = QHBoxLayout()
        layout.addWidget(QLabel("Настройки конвертации:"))

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(85)
        settings_layout.addWidget(QLabel("Качество (для форматов с поддержкой качества):"))
        settings_layout.addWidget(self.quality_spin)

        self.overwrite_checkbox = QCheckBox("Перезаписывать файлы")
        settings_layout.addWidget(self.overwrite_checkbox)

        layout.addLayout(settings_layout)

        # Формат вывода и папка
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Формат вывода:"))
        self.format_selector = QComboBox()
        self.format_selector.addItems(SUPPORTED_FORMATS)
        self.format_selector.setCurrentText("JPG")  # по умолчанию
        format_layout.addWidget(self.format_selector)

        # Кнопка выбора папки вывода
        output_layout = QHBoxLayout()
        self.output_button = QPushButton("Выбрать папку для сохранения")
        self.output_button.clicked.connect(self.select_output_folder)
        self.output_label = QLabel("📁 По умолчанию: рядом с исходными файлами")
        output_layout.addWidget(self.output_button)
        output_layout.addWidget(self.output_label)

        layout.addLayout(format_layout)
        layout.addLayout(output_layout)

        # Кнопки
        button_layout = QHBoxLayout()
        self.add_button = QPushButton("Добавить файлы")
        self.convert_button = QPushButton("Конвертировать")
        self.clear_button = QPushButton("Очистить список")

        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.convert_button)
        button_layout.addWidget(self.clear_button)

        layout.addLayout(button_layout)

        # Прогресс-бар
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Статус-бар
        self.status_bar = QLabel("Готов к работе")
        layout.addWidget(self.status_bar)

        # Подключение сигналов
        try:
            self.add_button.clicked.connect(self.on_add_files_clicked)
            self.convert_button.clicked.connect(self.start_conversion)
            self.clear_button.clicked.connect(self.clear_files)
            logger.info("Сигналы подключены успешно")
        except Exception as e:
            logger.critical(f"Ошибка подключения сигналов: {e}", exc_info=True)
            QMessageBox.critical(self, "Критическая ошибка", f"Не удалось подключить сигналы: {e}")

        self.worker_thread = None
        self.worker = None
        self.output_dir = None

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения")
        if folder:
            self.output_dir = Path(folder)
            self.output_label.setText(f"📁 {folder}")

    @pyqtSlot()
    def on_add_files_clicked(self):
        try:
            logger.info("=== НАЧАЛО on_add_files_clicked ===")

            file_paths, _ = QFileDialog.getOpenFileNames(
                self,
                "Выбрать изображения",
                "",
                "Изображения (*.jpg *.jpeg *.png *.heic *.heif *.tiff *.bmp *.webp *.gif *.ico)"
            )

            logger.debug(f"Получено путей: {len(file_paths)}")

            if not file_paths:
                logger.info("Нет выбранных файлов")
                return

            added_count = 0
            for path in file_paths:
                logger.debug(f"Проверяю файл: {path} → существует: {os.path.exists(path)}")
                if not os.path.isfile(path):
                    logger.warning(f"Файл не найден: {path}")
                    continue

                self.file_list.addItem(path)
                added_count += 1

            self.status_bar.setText(f"Добавлено {added_count} файлов")
            logger.info(f"Завершено добавление {added_count} файлов")

        except Exception as e:
            logger.critical(
                f"ФАТАЛЬНАЯ ОШИБКА в on_add_files_clicked: {type(e).__name__}: {e}",
                exc_info=True
            )
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Произошла ошибка: {e}\nПроверьте лог converter.log для деталей."
            )

    def save_heif_safe(
        self,
        img: Image.Image,
        output_path: Path,
        quality: int = 85,
        fallback_format: str = "JPG"
    ) -> bool:
        """
        Безопасно сохраняет изображение в HEIC/HEIF, если библиотека поддерживает это.
        При ошибке сохраняет fallback в указанный формат.
        Возвращает True при успешном сохранении HEIC, False если использован fallback.
        """
        logger = logging.getLogger(__name__)

        try:
            # Старый API (до 1.0): есть write_heif
            if hasattr(pillow_heif, "write_heif"):
                heif_data = pillow_heif.from_pillow(img)
                pillow_heif.write_heif(
                    heif_data,
                    output_path,
                    quality=quality,
                    save_mode="lossy",
                )
                logger.info(f"Сохранено в HEIC (через write_heif): {output_path}")
                return True

            # Новый API (1.x.x): есть from_pillow, но нет write_heif
            elif hasattr(pillow_heif, "from_pillow"):
                logger.warning("write_heif() отсутствует. Прямая запись HEIC невозможна.")
                fallback_path = output_path.with_suffix(f".{fallback_format.lower()}")
                img.convert("RGB").save(
                    fallback_path,
                    fallback_format.upper(),
                    quality=quality,
                    optimize=True
                )
                logger.info(
                    f"Сохранено fallback ({fallback_format.upper()}): {fallback_path}"
                )
                return False

            else:
                logger.warning(
                    "pillow-heif не поддерживает сохранение HEIC в этой версии."
                )
                fallback_path = output_path.with_suffix(f".{fallback_format.lower()}")
                img.convert("RGB").save(
                    fallback_path,
                    fallback_format.upper(),
                    quality=quality,
                    optimize=True
                )
                logger.info(
                    f"Сохранено fallback ({fallback_format.upper()}): {fallback_path}"
                )
                return False

        except Exception as e:
            logger.warning(f"Ошибка при сохранении HEIC: {e}. Использую fallback.")
            try:
                fallback_path = output_path.with_suffix(f".{fallback_format.lower()}")
                img.convert("RGB").save(
                    fallback_path,
                    fallback_format.upper(),
                    quality=quality,
                    optimize=True
                )
                logger.info(
                    f"Сохранено fallback ({fallback_format.upper()}): {fallback_path}"
                )
            except Exception as e2:
                logger.error(f"Ошибка fallback сохранения: {e2}")
            return False

    @pyqtSlot()
    def start_conversion(self):
        try:
            logger.info("=== НАЧАЛО start_conversion ===")

            if self.file_list.count() == 0:
                logger.warning("Нет файлов для конвертации")
                QMessageBox.warning(
                    self,
                    "Предупреждение",
                    "Добавьте файлы перед конвертацией"
                )
                return

            quality = self.quality_spin.value()
            overwrite = self.overwrite_checkbox.isChecked()
            out_format = self.format_selector.currentText().upper()

            logger.debug(
                f"Настройки конвертации: качество={quality}, "
                f"перезапись={overwrite}, формат={out_format}"
            )

            # Сбор валидных путей
            file_paths = []
            for i in range(self.file_list.count()):
                file_path = self.file_list.item(i).text()
                if os.path.isfile(file_path):
                    file_paths.append(file_path)
                else:
                    logger.warning(f"Файл не существует (пропущен): {file_path}")

            if not file_paths:
                logger.error("Нет валидных файлов для конвертации")
                QMessageBox.critical(
                    self,
                    "Ошибка",
                    "Нет доступных файлов для конвертации"
                )
                return

            self.progress_bar.setRange(0, len(file_paths))
            self.progress_bar.setValue(0)

            # Регистрируем поддержку HEIC/HEIF
            try:
                pillow_heif.register_heif_opener()
                logger.info("Поддержка HEIC/HEIF активирована")
            except Exception as e:
                logger.warning(f"Не удалось зарегистрировать pillow-heif: {e}")

            for idx, path in enumerate(file_paths):
                input_path = Path(path)
                output_dir = self.output_dir or input_path.parent

                try:
                    output_dir.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    logger.warning(
                        f"Не удалось создать папку {output_dir}: {e}"
                    )

                ext = out_format.lower()
                output_name = f"{input_path.stem}.{ext}"
                output_path = output_dir / output_name

                # Уникальное имя при запрете перезаписи
                if output_path.exists() and not overwrite:
                    i = 1
                    while True:
                        candidate = output_dir / f"{input_path.stem}_{i}.{ext}"
                        if not candidate.exists():
                            output_path = candidate
                            break
                        i += 1

                # Открытие изображения
                try:
                    with Image.open(input_path) as im:
                        img = im.copy()
                except UnidentifiedImageError as e:
                    logger.error(
                        f"Не удалось определить формат изображения {path}: {e}"
                    )
                    QMessageBox.warning(
                        self,
                        "Ошибка конвертации",
                        f"Формат не поддерживается:\n{path}"
                    )
                    continue
                except Exception as e:
                    logger.error(f"Ошибка открытия файла {path}: {e}")
                    continue

                # Подготовка RGB с учётом прозрачности
                try:
                    if img.mode in ("RGBA", "LA") or (
                        img.mode == "P" and "transparency" in img.info
                    ):
                        bg = Image.new("RGB", img.size, (255, 255, 255))
                        if img.mode != "RGBA":
                            img = img.convert("RGBA")
                        bg.paste(img, mask=img.split()[-1])
                        rgb = bg
                    else:
                        rgb = img.convert("RGB")
                except Exception as e:
                    logger.debug(
                        f"Ошибка при конвертации в RGB: {e}"
                    )
                    rgb = img.convert("RGB")

                # Параметры сохранения
                save_kwargs = {}
                if out_format in ("JPG", "JPEG", "WEBP", "TIFF"):
                    save_kwargs["quality"] = quality
                if out_format == "PNG":
                    save_kwargs["optimize"] = True

                # Сохранение
                try:
                    if out_format in ("HEIC", "HEIF"):
                        success = self.save_heif_safe(
                            rgb,
                            output_path,
                            quality=quality,
                            fallback_format="JPG"
                        )
                        if not success:
                            logger.warning(
                                f"Формат HEIC/HEIF недоступен, "
                                f"использован fallback для {input_path.name}"
                            )
                    else:
                        fmt = "JPEG" if out_format in ("JPG", "JPEG") else out_format
                        rgb.save(output_path, fmt, **save_kwargs)
                        logger.info(f"Сохранено: {output_path}")
                except Exception as e:
                    logger.error(
                        f"Ошибка сохранения {output_path}: {e}",
                        exc_info=True
                    )
                    QMessageBox.warning(
                        self,
                        "Ошибка",
                        f"Ошибка при сохранении:\n{output_path}\n{e}"
                    )

                # Обновление прогресса
                self.progress_bar.setValue(idx + 1)
                self.status_bar.setText(
                    f"Конвертировано {idx + 1}/{len(file_paths)}"
                )

            self.status_bar.setText("Конвертация завершена")
            QMessageBox.information(
                self,
                "Готово",
                "Конвертация выполнена успешно!"
            )

        except Exception as e:
            logger.critical(
                f"ФАТАЛЬНАЯ ОШИБКА в start_conversion: {type(e).__name__}: {e}",
                exc_info=True
            )
            QMessageBox.critical(
                self,
                "Критическая ошибка",
                f"Произошла ошибка при конвертации:\n{e}\n\n"
                f"Проверьте лог converter.log для деталей."
            )

    @pyqtSlot()
    def clear_files(self):
        try:
            logger.info("=== НАЧАЛО clear_files ===")
            self.file_list.clear()
            self.progress_bar.reset()
            self.status_bar.setText("Список очищен")
            logger.info("Список файлов очищен")
        except Exception as e:
            logger.critical(f"Ошибка в clear_files: {e}", exc_info=True)


# Основной запуск
if __name__ == "__main__":
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        app = QApplication(sys.argv)

        window = MainWindow()
        window.show()
        logger.info("Приложение запущено")

        # Проверка обновлений при запуске
        check_for_updates(parent=window)

        sys.exit(app.exec_())
    except Exception as e:
        logger.critical(
            f"Критическая ошибка при запуске приложения: {e}",
            exc_info=True
        )
        sys.exit(1)
