# main.py
import sys
from pathlib import Path
from typing import List, Optional

from PIL import Image, UnidentifiedImageError

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
            with Image.open(input_path) as img:
                try:
                    img.seek(0)
                except Exception:
                    pass

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

                rgb.save(output_path, "JPEG", quality=self.quality, optimize=True)
                return output_path
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
            # avoid duplicates
            existing = [Path(self.item(i).data(Qt.UserRole)) for i in range(self.count())]
            if path not in existing:
                item = QListWidgetItem(str(path))
                item.setData(Qt.UserRole, str(path))
                self.addItem(item)


class ConverterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image → JPG Converter (PyQt5)")
        self.resize(800, 480)

        self.files: List[Path] = []
        self.output_dir: Optional[Path] = None

        self._setup_ui()

        # thread related
        self.thread: Optional[QThread] = None
        self.worker: Optional[ConvertWorker] = None

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QVBoxLayout()
        central.setLayout(main_layout)

        # top buttons
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("Добавить файлы...")
        btn_add.clicked.connect(self.on_add_files)
        btn_layout.addWidget(btn_add)

        btn_remove = QPushButton("Удалить выделенные")
        btn_remove.clicked.connect(self.on_remove_selected)
        btn_layout.addWidget(btn_remove)

        btn_clear = QPushButton("Очистить список")
        btn_clear.clicked.connect(self.on_clear)
        btn_layout.addWidget(btn_clear)

        btn_out = QPushButton("Папка вывода...")
        btn_out.clicked.connect(self.on_choose_output)
        btn_layout.addWidget(btn_out)

        self.lbl_out = QLabel("Папка не выбрана")
        btn_layout.addWidget(self.lbl_out)

        main_layout.addLayout(btn_layout)

        # file list (supports drag-and-drop)
        self.list_widget = FileListWidget()
        main_layout.addWidget(self.list_widget)

        # bottom controls
        bottom_layout = QHBoxLayout()

        quality_label = QLabel("Качество (1-100):")
        bottom_layout.addWidget(quality_label)

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(85)
        bottom_layout.addWidget(self.quality_spin)

        self.overwrite_cb = QCheckBox("Перезаписывать существующие")
        bottom_layout.addWidget(self.overwrite_cb)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setMinimum(0)
        self.progress.setMaximum(100)
        bottom_layout.addWidget(self.progress)

        self.status_label = QLabel("Готов")
        bottom_layout.addWidget(self.status_label)

        main_layout.addLayout(bottom_layout)

        # convert button
        convert_btn = QPushButton("Конвертировать")
        convert_btn.clicked.connect(self.on_convert)
        main_layout.addWidget(convert_btn)

    def on_add_files(self):
        filetypes = "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp *.ico);;All files (*)"
        paths, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы для конвертации", filter=filetypes)
        if not paths:
            return
        for p in paths:
            self.list_widget.add_file(p)

    def on_remove_selected(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))

    def on_clear(self):
        self.list_widget.clear()
        self.output_dir = None
        self.lbl_out.setText("Папка не выбрана")

    def on_choose_output(self):
        d = QFileDialog.getExistingDirectory(self, "Выберите папку для сохранения JPG")
        if d:
            self.output_dir = Path(d)
            self.lbl_out.setText(str(self.output_dir))

    def _gather_files(self) -> List[Path]:
        files = []
        for i in range(self.list_widget.count()):
            path_str = self.list_widget.item(i).data(Qt.UserRole)
            if path_str:
                files.append(Path(path_str))
        return files

    def on_convert(self):
        files = self._gather_files()
        if not files:
            QMessageBox.warning(self, "Нет файлов", "Сначала добавьте файлы для конвертации.")
            return

        # if no output dir chosen, ask whether to save next to sources
        if self.output_dir is None:
            reply = QMessageBox.question(
                self,
                "Папка вывода не выбрана",
                "Сохранить JPG рядом с исходными файлами?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.No:
                return

        # disable UI
        self.setEnabled(False)
        self.progress.setMinimum(0)
        self.progress.setMaximum(len(files))
        self.progress.setValue(0)
        self.status_label.setText("Запуск...")

        # start worker thread
        self.thread = QThread()
        self.worker = ConvertWorker(
            files=files,
            output_dir=self.output_dir,
            quality=int(self.quality_spin.value()),
            overwrite=bool(self.overwrite_cb.isChecked()),
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_progress)
        self.worker.status.connect(self.on_status)
        self.worker.finished.connect(self.on_finished)
        self.thread.start()

    def on_progress(self, current: int, total: int):
        self.progress.setValue(current)
        self.status_label.setText(f"Обработка {current}/{total}")

    def on_status(self, text: str):
        self.status_label.setText(text)

    def on_finished(self, success: int, total: int, errors: list):
        # cleanup thread
        if self.thread and self.worker:
            self.thread.quit()
            self.thread.wait()
            self.worker = None
            self.thread = None

        # re-enable UI
        self.setEnabled(True)
        self.progress.setValue(total)
        self.status_label.setText(f"Готово: {success}/{total} успешно")

        if errors:
            msg = "Произошли ошибки при конвертации:\n\n" + "\n".join(errors[:20])
            if len(errors) > 20:
                msg += f"\n\n...и ещё {len(errors)-20} ошибок."
            QMessageBox.warning(self, "Ошибки", msg)
        else:
            QMessageBox.information(self, "Готово", f"Конвертация завершена: {success}/{total}")


def main():
    app = QApplication(sys.argv)
    win = ConverterWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
