# main.py

import os
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

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
            if input_path.suffix.lower() in ['.heic', '.heif']:
                pillow_heif.register_heif_opener()
                logging.debug("Зарегистрирован обработчик HEIF для %s", input_path)

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
        logging.debug("ConvertWorker инициализирован: файлов=%d, качество=%d, перезапись=%s", len(files), quality, overwrite)

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
                converter.convert(input_path, out_dir)
                success += 1
            except Exception as e:
                err_msg = f"{input_path.name}: {e}"
                errors.append(err_msg)
                logging.error("Ошибка конвертации %s: %s", input_path, e)
            self.progress.emit(idx, total)

        self.finished.emit(success, total, errors)
        logging.info("ConvertWorker завершён: успешно=%d/%d, ошибок=%d", success, total, len(errors))
