# main.py


import requests
import tkinter as tk
from tkinter import messagebox
import urllib.request
import os
import subprocess
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

# --- Блок с версиями ---
def get_current_version():
    """Читает текущую версию из файла version.txt"""
    try:
        with open("version.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "0.0.0"

def check_latest_version():
    """Запрашивает последнюю версию из GitHub API"""
    url = "https://api.github.com/repos/sVuMPaR/Converter/releases/latest"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return data["tag_name"]  # например, "v1.0.1"
        else:
            print(f"Ошибка API: {response.status_code}")
            return None
    except Exception as e:
        print(f"Ошибка сети: {e}")
        return None

def is_new_version_available(current, latest):
    """Сравнивает версии (возвращает True, если есть обновление)"""
    current = current.lstrip("v")
    latest = latest.lstrip("v")
    curr_parts = list(map(int, current.split(".")))
    latest_parts = list(map(int, latest.split(".")))

    for i in range(min(len(curr_parts), len(latest_parts))):
        if latest_parts[i] > curr_parts[i]:
            return True
        elif latest_parts[i] < curr_parts[i]:
            return False
    return len(latest_parts) > len(curr_parts)
# Конец блока


# --- Диалог и скачивание ---
def show_update_prompt(latest_version, download_url):
    """Показывает окно с предложением обновиться"""
    root = tk.Tk()
    root.withdraw()  # Скрываем основное окно Tk

    result = messagebox.askyesno(
        "Обновление доступно",
        f"Найдена новая версия: {latest_version}\n\n"
        "Хотите обновиться?\n(Это закроет текущее приложение)",
        icon="question"
    )

    if result:
        download_and_install(download_url)
    else:
        root.destroy()

def download_and_install(download_url):
    """Скачивает новый файл и запускает его"""
    try:
        # Имя файла из URL
        filename = download_url.split("/")[-1]
        
        # Скачиваем
        urllib.request.urlretrieve(download_url, filename)
        print(f"Скачано: {filename}")

        # Запускаем новый файл и закрываем текущий
        subprocess.Popen([filename], shell=True)
        os._exit(0)  # Надёжное завершение


    except Exception as e:
        messagebox.showerror("Ошибка", f"Не удалось обновить: {e}")
# Конец блока



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




class FileProcessorWorker(QThread):
    """Рабочий поток для конвертации изображений в JPG"""
    
    # Сигналы для взаимодействия с GUI
    finished = pyqtSignal(bool, str)        # (успех, сообщение)
    progress = pyqtSignal(int)              # процент выполнения (0–100)
    file_processed = pyqtSignal(str, str)    # (исходный_путь, результат)

    def __init__(self, file_paths, quality, overwrite):
        super().__init__()
        self.file_paths = file_paths
        self.quality = quality
        self.overwrite = overwrite

    def run(self):
        """Основной метод потока — выполняется в фоне"""
        try:
            total = len(self.file_paths)
            if total == 0:
                self.finished.emit(True, "Нет файлов для обработки")
                return

            success_count = 0
            for i, src_path in enumerate(self.file_paths):
                try:
                    # Открываем изображение
                    with Image.open(src_path) as img:
                        # Конвертируем в RGB (обязательно для JPG)
                        if img.mode in ("RGBA", "LA", "P"):
                            img = img.convert("RGB")

                        # Формируем путь для сохранения
                        base_name = os.path.splitext(os.path.basename(src_path))[0]
                        dest_path = os.path.join(
                            os.path.dirname(src_path),
                            f"{base_name}.jpg"
                        )

                        # Проверяем перезапись
                        if os.path.exists(dest_path) and not self.overwrite:
                            self.file_processed.emit(src_path, "Пропущено (файл существует)")
                            continue

                        # Сохраняем в JPG
                        img.save(dest_path, "JPEG", quality=self.quality, optimize=True)
                        self.file_processed.emit(src_path, "Успешно")
                        success_count += 1

                except Exception as e:
                    logger.error(f"Ошибка при обработке {src_path}: {e}")
                    self.file_processed.emit(src_path, f"Ошибка: {str(e)}")

                # Обновляем прогресс
                self.progress.emit(int((i + 1) / total * 100))

            # Завершаем работу
            if success_count == total:
                self.finished.emit(True, f"Конвертация завершена: {success_count} файлов")
            else:
                self.finished.emit(False, f"Частично успешно: {success_count}/{total} файлов")

        except Exception as e:
            logger.critical(f"Критическая ошибка в потоке: {e}", exc_info=True)
            self.finished.emit(False, f"Критическая ошибка: {str(e)}")



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
        self.add_button.clicked.connect(self.on_add_files_clicked)
        self.convert_button.clicked.connect(self.start_conversion)
        self.clear_button.clicked.connect(self.clear_files)


        # Рабочий поток
        self.worker_thread = None
        self.worker = None


    def on_add_files_clicked(self):
        try:
            file_paths, _ = QFileDialog.getOpenFileNames(
                self,
                "Выбрать изображения",
                os.path.expanduser("~/Pictures"),  # стартовая папка
                "Изображения (*.jpg *.jpeg *.png)"
            )
            if not file_paths:
                return

            for path in file_paths:
                if os.path.isfile(path):  # проверка на файл
                    self.file_list.addItem(path)
            self.status_bar.setText(f!Добавлено {len(file_paths)} файлов")

        except Exception as e:
            logger.critical(f!Ошибка в on_add_files_clicked: {e}", exc_info=True)
            QMessageBox.critical(self, "Критическая ошибка", str(e))

    def process_files_in_background(self, file_paths):
        """Запускает обработку файлов в отдельном потоке"""
        # Создаём рабочий поток
        self.worker = FileProcessorWorker(file_paths, self.quality_spin.value(), self.overwrite_checkbox.isChecked())
        
        # Подключаем сигналы
        self.worker.finished.connect(self.on_processing_finished)
        self.worker.progress.connect(self.update_progress)  # если есть прогресс
        
        # Запускаем поток
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.start()
    
        logger.info("Обработка запущена в фоновом режиме")
    
    def on_processing_finished(self, success, message):
        """Вызывается после завершения фоновой обработки"""
        if success:
            logger.info(message)
            QMessageBox.information(self, "Успех", message)
            self.status_bar.setText("Конвертация завершена")
        else:
            logger.error(message)
            QMessageBox.critical(self, "Ошибка", message)
            self.status_bar.setText("Ошибка конвертации")
    
        # Очищаем потоки
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
        self.worker = None
        self.worker_thread = None
    
        # Сбрасываем прогресс
        self.progress_bar.setValue(0)

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

    # Запуск проверки при старте
    current_version = get_current_version()
    latest_tag = check_latest_version()

    if latest_tag and is_new_version_available(current_version, latest_tag):
        # Формируем URL скачивания (подставьте имя вашего EXE)
        download_url = (
            f"https://github.com/sVuMPaR/Converter/"
            f"releases/download/{latest_tag}/release_bundle.zip"
        )
        show_update_prompt(latest_tag, download_url)

    # Конец блока
    
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
