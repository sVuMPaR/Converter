import sys
import os
import logging
import tempfile
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Импорты PyQt5
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QListWidget, QFileDialog, QProgressBar,
    QMessageBox, QSpinBox, QCheckBox
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
        logger.info(f!Лог-файл: {log_path}")
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Конвертер изображений в JPG")
        self.resize(800, 600)

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
        settings_layout.addWidget(QLabel("Качество JPG:"))
        settings_layout.addWidget(self.quality_spin)

        self.overwrite_checkbox = QCheckBox("Перезаписывать файлы")
        settings_layout.addWidget(self.overwrite_checkbox)

        layout.addLayout(settings_layout)

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

        # Подключение сигналов (с проверкой)
        try:
            self.add_button.clicked.connect(self.on_add_files_clicked)
            self.convert_button.clicked.connect(self.start_conversion)
            self.clear_button.clicked.connect(self.clear_files)
            logger.info("Сигналы подключены успешно")
        except Exception as e:
            logger.critical(f"Ошибка подключения сигналов: {e}", exc_info=True)
            QMessageBox.critical(self, "Критическая ошибка", f"Не удалось подключить сигналы: {e}")

        # Рабочий поток
        self.worker_thread = None
        self.worker = None

    @pyqtSlot()
    def on_add_files_clicked(self):
        try:
            logger.info("=== НАЧАЛО on_add_files_clicked ===")

            # Проверка существования виджета
            if not hasattr(self, 'file_list'):
                logger.error("Виджет file_list не создан!")
                return

            file_paths, _ = QFileDialog.getOpenFileNames(
                self,
                "Выбрать изображения",
                "",
                "Изображения (*.jpg *.jpeg *.png *.heic *.heif *.tiff *.bmp *.webp)"
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
                f"Произошла ошибка:\n{e}\n\nПроверьте лог converter.log для деталей."
            )

    @pyqtSlot()
    def start_conversion(self):
        try:
            logger.info("=== НАЧАЛО start_conversion ===")

            # Проверка наличия файлов
            if self.file_list.count() == 0:
                logger.warning("Нет файлов для конвертации")
                QMessageBox.warning(self, "Предупреждение", "Добавьте файлы перед конвертацией")
                return

            # Получение настроек
            quality = self.quality_spin.value()
            overwrite = self.overwrite_checkbox.isChecked()

            logger.debug(f"Настройки конвертации: качество={quality}, перезапись={overwrite}")

            # Сбор путей
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

            logger.info(f"Начинаем конвертацию {len(file_paths)} файлов")

            # Временная заглушка: имитация конвертации
            self.progress_bar.setRange(0, len(file_paths))
            self.progress_bar.setValue(0)

            for idx, path in enumerate(file_paths):
                try:
                    logger.debug(f"Конвертируем: {path}")

                    # Здесь должна быть логика конвертации
                    # Например, через Pillow:
                    # image = Image.open(path)
                    # # ... обработка ...
                    # image.save(output_path, "JPEG", quality=quality)

                    # Имитация работы
                    import time
                    time.sleep(0.1)  # Задержка для видимости прогресса

                    self.progress_bar.setValue(idx + 1)
                    self.status_bar.setText(f"Конвертировано {idx + 1}/{len(file_paths)}")

                except Exception as e:
                    logger.error(f"Ошибка при конвертации {path}: {e}")
                    QMessageBox.warning(
                        self,
                        "Ошибка конвертации",
                        f"Не удалось обработать файл:\n{path}\nОшибка: {e}"
                    )

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
