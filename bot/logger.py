import logging
import os
from datetime import datetime
from functools import wraps
from aiogram import Bot
from aiogram.types import Message


# Создаем директорию для логов, если она не существует
if not os.path.exists("logs"):
    os.makedirs("logs")


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,  # Уровень логирования (INFO, DEBUG, WARNING, ERROR, CRITICAL)
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",  # Формат сообщений
    handlers=[
        logging.FileHandler(f"logs/bot_{datetime.now().strftime('%Y-%m-%d')}.log"),  # Логирование в файл с датой
        logging.StreamHandler()  # Логирование в консоль
    ]
)


logger = logging.getLogger(__name__)
