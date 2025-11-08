# main.py

import os
import logging
import sys
from pathlib import Path
from typing import List, Optional

from logging.handlers import RotatingFileHandler

from PIL import Image, UnidentifiedImageError
import pillow_heif
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QObject, QUrl
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QHBoxLayout,
    QProgressBar,
    QSpinBox,
    QCheckBox,
)


# --- Настройка логирования ---
def setup_logging():
    """Настраивает логирование в файл с ротацией (в папке с EXE)."""
    logger = logging.getLogger()
    
    # Если обработчики уже настроены — не делаем ничего
    if logger.handlers:
        return

    logger.setLevel(logging.DEBUG)

    # Форматировщик
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Путь к логу: папка с исполняемым файлом
    if getattr(sys, 'frozen', False):  # PyInstaller: EXE запущен
        exe_dir = Path(sys.executable).parent
    else:  # Запуск из .py (разработка)
        exe_dir = Path(__file__).parent

    log_path = exe_dir / "converter.log"

    # Обработчик для файла
    try:
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=5 * 1024 * 1024,  # 5 МБ
            backupCount=3,
            encoding='utf-8',
            errors='replace'
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    except (IOError, OSError) as e:
        print(f"[LOG] Не удалось открыть лог-файл {log_path}: {e}")

    # Обработчик для консоли
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.WARNING)
    logger.addHandler(console_handler)

    # Логируем старт
    logger.info("Запуск конвертера изображений")
    logger.debug("PATH: %s", os.environ.get("PATH"))




# Инициализируем логирование
setup_logging()



# --- Классы приложения ---

class ImageConverter:
    """Класс, отвечающий за конвертацию одного файла в JPG. Поддерживает HEIC через pillow-heif."""

    def __init__(self, quality: int = 85, overwrite: bool = False, background_color=(255, 255, 255)):
        self.quality = max(1, min(100, quality))
        self.overwrite = overwrite
        self.background_color = background_color
        logging.debug("ImageConverter инициализирован: quality=%d, overwrite=%s", self.quality, self.overwrite)


        # Проверка регистрации pillow_heif
        try:
            pillow_heif.register_heif_opener()
            logging.debug("pillow_heif успешно зарегистрирован")
        except Exception as e:
            logging.error("Ошибка регистрации pillow_heif: %s", e)
            raise

    def _prepare_rgb(self, img: Image.Image) -> Image.Image:
        logging.debug("Подготовка RGB для изображения: mode=%s, size=%s", img.mode, img.size)
        if img.mode == "RGB":
            return img
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            bg = Image.new("RGB", img.size, self.background_color)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            bg.paste(img, mask=img.split()[-1])
            return bg
        return img.convert("RGB")


    def convert(self, input_path: Path, output_dir: Path) -> Path:
        logging.info("Начало конвертации: %s -> %s", input_path, output_dir)
        if not input_path.exists():
            logging.error("Файл не найден: %s", input_path)
            raise FileNotFoundError(f"Input file not found: {input_path}")


        try:
            with Image.open(input_path) as img:
                try:
                    img.seek(0)
                except Exception as e:
                    logging.debug("img.seek(0) не поддерживается: %s", e)

                logging.info("Обработка %s (mode: %s, size: %s)", input_path.name, img.mode, img.size)
                rgb = self._prepare_rgb(img)
                output_name = input_path.stem + ".jpg"
                output_path = output_dir / output_name


                if output_path.exists() and not self.overwrite:
                    i = 1
                    while True:
                        candidate = output_dir / f"{input_path.stem}_{i}.jpg"
                        if not candidate.exists():
                            output_path = candidate
                            break
                        i += 1

                exif = img.getexif() if hasattr(img, 'getexif') else None
                rgb.save(
                    output_path,
                    "JPEG",
                    quality=self.quality,
                    optimize=True,
                    exif=exif
                )
                logging.info("Конвертация успешна: %s", output_path)
                return output_path

        except pillow_heif.HeifError as e:
            logging.error("Ошибка HEIF при обработке %s: %s", input_path, e)
            raise ValueError(f"HEIC decode error: {input_path} - {e}") from e
        except UnidentifiedImageError as e:
            logging.error("Не удаётся определить формат изображения %s: %s", input_path, e)
            raise ValueError(f"Cannot identify image file: {input_path}") from e
        except Exception as e:
            logging.exception("Ошибка при конвертации %s: %s", input_path, e)
            raise RuntimeError(f"Failed to convert {input_path}: {e}") from e




class ConvertWorker(QObject):
    progress = pyqtSignal(int, int)
    status = pyqtSignal(str)
    finished = pyqtSignal(int, int, list)

    def __init__(self, files: List[Path], output_dir: Optional[Path], quality: int, overwrite: bool):
        super().__init__()
        self.files = files
        self.output_dir = output_dir
        self.quality = quality
        self.overwrite = overwrite
        self._is_running = True
        logging.debug(
            "ConvertWorker инициализирован: файлов=%d, качество=%d, перезапись=%s",
            len(files), quality, overwrite
        )

    def stop(self):
        self._is_running = False
        logging.info("ConvertWorker остановлен по запросу")

    def run(self):
        converter = ImageConverter(quality=self.quality, overwrite=self.overwrite)
        total = len(self.files)
        success = 0
        errors = []

        for idx, input_path in enumerate(self.files, start=1):
            if not self._is_running:
                logging.warning("ConvertWorker прерван на файле %d/%d: %s", idx, total, input_path)
                break

            self.status.emit(f"Обработка {idx}/{total}: {input_path.name}")
            try:
                out_dir = self.output_dir if self.output_dir is not None else input_path.parent
                output_path = converter.convert(input_path, out_dir)
                success += 1
                logging.info("Конвертация завершена: %s -> %s", input_path, output_path)
            except Exception as e:
                err_msg = f"{input_path.name}: {str(e)}"
                errors.append(err_msg)
                logging.error("Ошибка конвертации %s: %s", input_path, e)
            self.progress.emit(idx, total)

        self.finished.emit(success, total, errors)
        logging.info("ConvertWorker завершён: успешно=%d/%d, ошибок=%d", success, total, len(errors))



# --- Главное окно приложения ---
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

        # Подключение сигналов
        self.add_button.clicked.connect(self.add_files)
        self.convert_button.clicked.connect(self.start_conversion)
        self.clear_button.clicked.connect(self.clear_files)


        # Рабочий поток
        self.worker_thread = None
        self.worker = None

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            (self, "Выбрать изображения", "", "Изображения (*.jpg *.jpeg *.png *.bmp *.heic *.heif)")
        if files:
            for file in files:
                item = QListWidgetItem(Path(file).name)
                item.setData(Qt.UserRole, Path(file))
                self.file_list.addItem(item)
            self.status_bar.setText(f"Добавлено {len(files)} файлов")

    def clear_files(self):
        self.file_list.clear()
        self.status_bar.setText("Список очищен")


    def start_conversion(self):
        if self.file_list.count() == 0:
            QMessageBox.warning(self, "Ошибка", "Нет файлов для конвертации!")
            return

        # Собираем пути
        files = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            files.append(item.data(Qt.UserRole))

        # Настройки
        quality = self.quality_spin.value()
        overwrite = self.overwrite_checkbox.isChecked()

        # Запускаем поток
        self.worker_thread = QThread()
        self.worker = ConvertWorker(files, None, quality, overwrite)

        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.on_conversion_finished)
        self.worker.progress.connect(self.update_progress)
        self.worker.status.connect(self.status_bar.setText)


        self.worker_thread.start()
        self.convert_button.setEnabled(False)
        self.status_bar.setText("Конвертация начата...")

    def update_progress(self, current, total):
        self.progress_bar.setValue(int((current / total) * 100))

    def on_conversion_finished(self, success, total, errors):
        self.convert_button.setEnabled(True)
        self.worker_thread.quit()
        self.worker_thread.wait()

        if errors:
            err_text = "\n".join(errors)
            QMessageBox.critical(self, "Ошибки конвертации", f"Не удалось конвертировать {len(errors)} файлов:\n{err_text}")
        
        self.status_bar.setText(f"Готово: {success}/{total} файлов успешно конвертировано")
        self.progress_bar.setValue(0)



# --- Запуск приложения ---
if __name__ == "__main__":
    try:
        logging.info("Начало инициализации приложения")
        app = QApplication(sys.argv)
        logging.info("QApplication создан")

        window = MainWindow()
        window.show()
        logging.info("Окно создано и показано")

        sys.exit(app.exec_())

    except Exception as e:
        logging.exception("Критическая ошибка при запуске: %s", e)
        try:
            msg_box = QMessageBox()
            msg_box.setWindowTitle("Ошибка")
            msg_box.setText(f"Произошла критическая ошибка:\n{str(e)}")
            msg_box.exec_()
        except:
            print(f"Не удалось показать окно ошибки: {e}")
