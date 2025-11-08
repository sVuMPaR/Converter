# main.py
import sys
from pathlib import Path
from typing import List, Optional

from PIL import Image, UnidentifiedImageError
import pillow_heif  # ← добавлен импорт
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

class ImageConverter:
    """
    Класс, отвечающий за конвертацию одного файла в JPG.
    Поддерживает HEIC через pillow-heif.
    """

    def __init__(self, quality: int = 85, overwrite: bool = False, background_color=(255, 255, 255)):
        self.quality = max(1, min(100, quality))
        self.overwrite = overwrite
        self.background_color = background_color

    def _prepare_rgb(self, img: Image.Image) -> Image.Image:
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
        if not input_path.exists():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        try:
            # Регистрация обработчика HEIC перед открытием
            if input_path.suffix.lower() in ['.heic', '.heif']:
                pillow_heif.register_heif_opener()

            with Image.open(input_path) as img:
                try:
                    img.seek(0)
                except Exception:
                    pass

                # Логирование для отладки
                print(f"Processing {input_path.name} (mode: {img.mode}, size: {img.size})")

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

                # Сохранение EXIF-данных (если есть)
                exif = img.getexif() if hasattr(img, 'getexif') else None
                rgb.save(
                    output_path,
                    "JPEG",
                    quality=self.quality,
                    optimize=True,
                    exif=exif
                )
                return output_path
        except pillow_heif.HeifError as e:  # ← Обработка ошибок HEIC
            raise ValueError(f"HEIC decode error: {input_path} - {e}") from e
        except UnidentifiedImageError as e:
            raise ValueError(f"Cannot identify image file: {input_path}") from e
        except Exception as e:
            raise RuntimeError(f"Failed to convert {input_path}: {e}") from e


class ConvertWorker(QObject):
    progress = pyqtSignal(int, int)  # current, total
    status = pyqtSignal(str)
    finished = pyqtSignal(int, int, list)  # success, total, errors

    def __init__(self, files: List[Path], output_dir: Optional[Path], quality: int, overwrite: bool):
        super().__init__()
        self.files = files
        self.output_dir = output_dir
        self.quality = quality
        self.overwrite = overwrite
        self._is_running = True

    def stop(self):
        self._is_running = False

    def run(self):
        converter = ImageConverter(quality=self.quality, overwrite=self.overwrite)
        total = len(self.files)
        success = 0
        errors = []

        for idx, input_path in enumerate(self.files, start=1):
            if not self._is_running:
                break
            self.status.emit(f"Обработка {idx}/{total}: {input_path.name}")
            try:
                out_dir = self.output_dir if self.output_dir is not None else input_path.parent
                converter.convert(input_path, out_dir)
                success += 1
            except Exception as e:
                errors.append(f"{input_path.name}: {e}")
            self.progress.emit(idx, total)

        self.finished.emit(success, total, errors)

class FileListWidget(QListWidget):
    """
    QListWidget, поддерживающий drag-and-drop файлов из файлового менеджера.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)

    def dragEnterEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                if isinstance(url, QUrl):
                    local = url.toLocalFile()
                else:
                    local = url.toString()
                if local:
                    self.add_file(local)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def add_file(self, path_str: str):
        path = Path(path_str)
        if path.exists() and path.is_file():
            # avoid
