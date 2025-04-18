import json
import os
from dotenv import load_dotenv
import re


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


if os.path.exists(os.path.join(BASE_DIR, '.env.local')):
    load_dotenv(os.path.join(BASE_DIR, '.env.local'))
else:
    load_dotenv(os.path.join(BASE_DIR, '.env'))


class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    DB_URL = os.getenv('DB_URL')
    ADMIN_IDS = json.loads(os.getenv('ADMIN_IDS', '[]'))
    GOOGLE_CREDENTIALS_PATH = os.getenv('GOOGLE_CREDENTIALS_PATH')
    GOOGLE_SCOPES = json.loads(os.getenv('GOOGLE_SCOPES', '[]'))
    GOOGLE_SHEET_LINK = os.getenv('GOOGLE_SHEET_LINK')
    GOOGLE_SHEETS_FILE_ID = re.search(r'/d/([a-zA-Z0-9-_]+)', GOOGLE_SHEET_LINK).group(1) if GOOGLE_SHEET_LINK else None
    BOT_USERNAME = os.getenv('BOT_USERNAME')


def is_admin(user_id: int):
    return user_id in Config.ADMIN_IDS