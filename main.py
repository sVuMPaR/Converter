import sys
import os
import logging
import tempfile
from pathlib import Path
from logging.handlers import RotatingFileHandler

from PIL import Image, UnidentifiedImageError
import pillow_heif
import traceback

# Импорты PyQt5
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QFileDialog, QProgressBar,
    QMessageBox, QSpinBox, QCheckBox, QComboBox
)
from PyQt5.QtCore import pyqtSlot

# Настройка логирования
def setup_logging():
    logger = logging.getLogger()
    
    # Удаляем старые обработчики
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Определяем путь к логу
    if getattr(sys, 'frozen', False):  # PyInstaller
        exe_dir = Path(sys.executable).parent
    else:
        exe_dir = Path(__file__).parent

    log_path = exe_dir / "converter.log"

    # Попытка создать файловый обработчик
    file_handler = None
    try:
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8',
            errors='replace'
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
                encoding='utf-8'
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

SUPPORTED_FORMATS = ["JPG", "JPEG", "PNG", "WEBP", "BMP", "TIFF", "HEIC", "HEIF", "GIF", "ICO"]


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
        # По умолчанию JPG
        self.format_selector.setCurrentText("JPG")
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
                # Проверка пути
                logger.debug(f"Проверяю файл: {path} → существует: {os.path.exists(path)}")
                if not os.path.isfile(path):
                    logger.warning(f"Файл не найден: {path}")
                    continue

                # Добавление в список
                self.file_list.addItem(path)
                added_count += 1

            self.status_bar.setText(f"Добавлено {added_count} файлов")
            logger.info(f"Завершено добавление {added_count} файлов")

        except Exception as e:
            logger.critical(f"ФАТАЛЬНАЯ ОШИБКА в on_add_files_clicked: {type(e).__name__}: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Ошибка",
                f"Произошла ошибка:{e} Проверьте лог converter.log для деталей.")

    def save_heif_safe(img: Image.Image, output_path: Path, quality: int = 85, fallback_format: str = "JPG") -> bool:
        """
        Безопасно сохраняет изображение в HEIC/HEIF, если библиотека поддерживает это.
        При ошибке сохраняет fallback в указанный формат (например, JPG, PNG и т.д.).
        Возвращает True при успешном сохранении HEIC, False если использован fallback.
        """
        import pillow_heif
        logger = logging.getLogger(__name__)
    
        try:
            # Старый API (до v1.0)
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
    
            # Новый API (v1.x.x) — write_heif отсутствует
            elif hasattr(pillow_heif, "from_pillow"):
                logger.warning("write_heif() отсутствует. Прямая запись HEIC невозможна.")
                # fallback
                fallback_path = output_path.with_suffix(f'.{fallback_format.lower()}')
                img.convert("RGB").save(fallback_path, fallback_format.upper(), quality=quality, optimize=True)
                logger.info(f"Сохранено fallback ({fallback_format.upper()}): {fallback_path}")
                return False
    
            else:
                logger.warning("pillow-heif не поддерживает сохранение HEIC в этой версии.")
                fallback_path = output_path.with_suffix(f'.{fallback_format.lower()}')
                img.convert("RGB").save(fallback_path, fallback_format.upper(), quality=quality, optimize=True)
                logger.info(f"Сохранено fallback ({fallback_format.upper()}): {fallback_path}")
                return False
    
        except Exception as e:
            logger.warning(f"Ошибка при сохранении HEIC: {e}. Использую fallback.")
            try:
                fallback_path = output_path.with_suffix(f'.{fallback_format.lower()}')
                img.convert("RGB").save(fallback_path, fallback_format.upper(), quality=quality, optimize=True)
                logger.info(f"Сохранено fallback ({fallback_format.upper()}): {fallback_path}")
            except Exception as e2:
                logger.error(f"Ошибка fallback сохранения: {e2}")
            return False
    
    @pyqtSlot()
    def start_conversion(self):
        try:
            logger.info("=== НАЧАЛО start_conversion ===")
    
            if self.file_list.count() == 0:
                logger.warning("Нет файлов для конвертации")
                QMessageBox.warning(self, "Предупреждение", "Добавьте файлы перед конвертацией")
                return
    
            quality = self.quality_spin.value()
            overwrite = self.overwrite_checkbox.isChecked()
            out_format = self.format_selector.currentText().upper()
    
            logger.debug(f"Настройки конвертации: качество={quality}, перезапись={overwrite}, формат={out_format}")
    
            file_paths = []
            for i in range(self.file_list.count()):
                file_path = self.file_list.item(i).text()
                if os.path.isfile(file_path):
                    file_paths.append(file_path)
                else:
                    logger.warning(f"Файл не существует (пропущен): {file_path}")
    
            if not file_paths:
                logger.error("Нет валидных файлов для конвертации")
                QMessageBox.critical(self, "Ошибка", "Нет доступных файлов для конвертации")
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
                    logger.warning(f"Не удалось создать папку {output_dir}: {e}")
    
                ext = out_format.lower()
                output_name = f"{input_path.stem}.{ext}"
                output_path = output_dir / output_name
    
                # Если перезапись запрещена — подставляем уникальное имя
                if output_path.exists() and not overwrite:
                    i = 1
                    while True:
                        candidate = output_dir / f"{input_path.stem}_{i}.{ext}"
                        if not candidate.exists():
                            output_path = candidate
                            break
                        i += 1
    
                img = None
                try:
                    with Image.open(input_path) as im:
                        img = im.copy()  # создаём копию в памяти
                except UnidentifiedImageError as e:
                    logger.error(f"Не удалось определить формат изображения {path}: {e}")
                    QMessageBox.warning(self, "Ошибка конвертации", f"Формат не поддерживается:\n{path}")
                    continue
                except Exception as e:
                    logger.error(f"Ошибка открытия файла {path}: {e}")
                    continue
    
                # Подготовка RGB
                try:
                    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                        bg = Image.new("RGB", img.size, (255, 255, 255))
                        if img.mode != "RGBA":
                            img = img.convert("RGBA")
                        bg.paste(img, mask=img.split()[-1])
                        rgb = bg
                    else:
                        rgb = img.convert("RGB")
                except Exception as e:
                    logger.debug(f"Ошибка при конвертации в RGB: {e}")
                    rgb = img.convert("RGB")
    
                save_kwargs = {}
                if out_format in ("JPG", "JPEG", "WEBP", "TIFF"):
                    save_kwargs["quality"] = quality
                if out_format == "PNG":
                    save_kwargs["optimize"] = True
    
                try:
                    if out_format in ("HEIC", "HEIF"):
                        # безопасная функция с fallback
                        success = save_heif_safe(
                            rgb,
                            output_path,
                            quality,
                            fallback_format=self.format_selector.currentText()
                        )
                        if not success:
                            logger.warning(f"Формат HEIC недоступен, fallback в {self.format_selector.currentText().upper()}")
                        except Exception as e:
                            logger.warning(f"Сохранение HEIF напрямую не удалось: {e}. Сохраняю JPEG fallback.")
                            fallback_path = output_path.with_suffix(".jpg")
                            rgb.save(fallback_path, "JPEG", quality=quality, optimize=True)
                            logger.info(f"Сохранено JPEG fallback: {fallback_path}")
                    else:
                        fmt = "JPEG" if out_format in ("JPG", "JPEG") else out_format
                        rgb.save(output_path, fmt, **save_kwargs)
                        logger.info(f"Сохранено: {output_path}")
    
                except Exception as e:
                    logger.error(f"Ошибка сохранения {output_path}: {e}", exc_info=True)
                    QMessageBox.warning(self, "Ошибка", f"Ошибка при сохранении:\n{output_path}\n{e}")
    
                self.progress_bar.setValue(idx + 1)
                self.status_bar.setText(f"Конвертировано {idx + 1}/{len(file_paths)}")
    
            self.status_bar.setText("Конвертация завершена")
            QMessageBox.information(self, "Готово", "Конвертация выполнена успешно!")
    
        except Exception as e:
            logger.critical(f"ФАТАЛЬНАЯ ОШИБКА в start_conversion: {type(e).__name__}: {e}", exc_info=True)
            QMessageBox.critical(
                self,
                "Критическая ошибка",
                f"Произошла ошибка при конвертации:\n{e}\n\nПроверьте лог converter.log для деталей."
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
    # Настройка логирования
    setup_logging()
    logger = logging.getLogger(__name__)

    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        logger.info("Приложение запущено")
        sys.exit(app.exec_())
    except Exception as e:
        logger.critical(f"Критическая ошибка при запуске приложения: {e}", exc_info=True)
        sys.exit(1)
