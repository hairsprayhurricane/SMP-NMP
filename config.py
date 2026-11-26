"""Конфигурация приложения. Всё читается из переменных окружения / файла .env."""
import os
import secrets
import time

from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


# Адрес API СМП/НМП (без завершающего слэша). Пусто = API не настроен.
API_BASE_URL = os.getenv("API_BASE_URL", "").strip().rstrip("/")
# Токен авторизации (если API его требует). Отправляется как Bearer.
API_TOKEN = os.getenv("API_TOKEN", "").strip()
# Таймаут одного запроса к API, секунды.
API_TIMEOUT = _float("API_TIMEOUT", 5)

# Ссылка на портал врача (открывается в новой вкладке).
DOCTOR_PORTAL_URL = os.getenv("DOCTOR_PORTAL_URL", "").strip()

# Логи
LOG_DIR = os.getenv("LOG_DIR", os.path.join(BASE_DIR, "logs"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Локальная SQL-база (SQLite): пользователи, роли, права, журнал действий
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "data", "app.db"))
# Сколько часов сессия входа живёт без активности (каждый запрос продлевает её).
# 24 часа: сотрудник, вышедший на вызов вечером, не должен вводить пароль заново.
SESSION_HOURS = _float("SESSION_HOURS", 24)
# Включить, когда приложение открывается по HTTPS: кука сессии пойдёт только по шифрованному каналу
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "").strip().lower() in ("1", "true", "yes")
# Включить, если перед приложением стоит nginx/другой прокси: тогда в журнале будут настоящие IP
TRUST_PROXY = os.getenv("TRUST_PROXY", "").strip().lower() in ("1", "true", "yes")
# Блокировка входа после N неудачных попыток подряд, на M минут
LOGIN_MAX_ATTEMPTS = int(_float("LOGIN_MAX_ATTEMPTS", 5))
LOGIN_LOCK_MINUTES = int(_float("LOGIN_LOCK_MINUTES", 5))

# Карта в карточке вызова (Leaflet). Плитки карты грузит браузер планшета.
MAP_ENABLED = os.getenv("MAP_ENABLED", "1").strip().lower() not in ("0", "false", "no")
# Адрес плиток. Для закрытого контура укажите свой сервер плиток.
MAP_TILE_URL = os.getenv("MAP_TILE_URL", "https://tile.openstreetmap.org/{z}/{x}/{y}.png").strip()
MAP_ATTRIBUTION = os.getenv("MAP_ATTRIBUTION", "© участники OpenStreetMap").strip()
MAP_ZOOM = int(_float("MAP_ZOOM", 16))


def _secret_from_file(path):
    """Ключ, сохранённый в файле: он общий для всех worker'ов и переживает перезапуск.

    Без этого после перезапуска сервера все сотрудники были бы разлогинены,
    а при нескольких worker'ах Gunicorn вход бы не работал.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            fd = None
        if fd is not None:  # файл создали мы: пишем новый ключ
            with os.fdopen(fd, "w") as f:
                f.write(secrets.token_hex(32))
        for _ in range(50):  # другой worker мог создать файл только что
            with open(path, encoding="utf-8") as f:
                value = f.read().strip()
            if len(value) >= 32:
                return value
            time.sleep(0.1)
    except OSError:
        pass
    return ""


# Ключ подписи сессии. Лучше задать свой в .env; если не задан, создаётся файл data/secret.key.
SECRET_KEY = os.getenv("SECRET_KEY", "").strip()
SECRET_KEY_SOURCE = "env"
if not SECRET_KEY:
    SECRET_KEY = _secret_from_file(os.path.join(os.path.dirname(DB_PATH) or ".", "secret.key"))
    SECRET_KEY_SOURCE = "file"
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    SECRET_KEY_SOURCE = "memory"

# Только для mock_api.py
MOCK_PORT = int(_float("MOCK_PORT", 5001))
