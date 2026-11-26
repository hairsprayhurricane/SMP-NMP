"""Локальная SQL-база (SQLite): пользователи, роли, права, журнал действий.

Медицинских данных пациентов здесь нет — они остаются на стороне API.
Все функции принимают открытое соединение `conn`, поэтому работают и внутри
Flask-запроса (get_db), и из командной строки (manage.py, connect).
Чтобы перейти на другую СУБД, достаточно заменить connect()/get_db() и
подправить SQL в schema.sql/seed.sql (см. комментарии там).
"""
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone

from flask import g, has_request_context, request
from werkzeug.security import generate_password_hash

import config

log = logging.getLogger("smp.db")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HASH_METHOD = "pbkdf2:sha256"  # доступен везде, в отличие от scrypt на старых системах
MIN_PASSWORD_LEN = 8
TS_FORMAT = "%Y-%m-%d %H:%M:%S"

# Для выравнивания времени проверки, когда такого логина нет
DUMMY_HASH = generate_password_hash("dummy-password", method=HASH_METHOD)


def now_str(plus_minutes=0):
    """Текущее время UTC строкой (формат совпадает с datetime('now') в SQLite)."""
    moment = datetime.now(timezone.utc) + timedelta(minutes=plus_minutes)
    return moment.strftime(TS_FORMAT)


# --- Соединение ------------------------------------------------------------
def connect():
    folder = os.path.dirname(config.DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    """Создаёт таблицы и начальные роли/права. Безопасно вызывать повторно."""
    for name in ("schema.sql", "seed.sql"):
        with open(os.path.join(BASE_DIR, name), encoding="utf-8") as f:
            conn.executescript(f.read())
    conn.commit()


def get_db():
    """Соединение на время одного запроса Flask."""
    if "db" not in g:
        g.db = connect()
    return g.db


def close_db(exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


# --- Пользователи, роли, права ---------------------------------------------
_USER_SELECT = (
    "SELECT u.*, r.code AS role_code, r.title AS role_title "
    "FROM users u JOIN roles r ON r.id = u.role_id "
)


def get_user(conn, user_id):
    return conn.execute(_USER_SELECT + "WHERE u.id = ?", (user_id,)).fetchone()


def get_user_by_username(conn, username):
    return conn.execute(
        _USER_SELECT + "WHERE u.username = ?", (username.strip().lower(),)
    ).fetchone()


def list_users(conn):
    return conn.execute(_USER_SELECT + "ORDER BY u.username").fetchall()


def list_roles(conn):
    return conn.execute("SELECT code, title FROM roles ORDER BY id").fetchall()


def role_permissions_matrix(conn):
    """[(название роли, [названия прав])] для страницы администратора."""
    result = []
    for role in conn.execute("SELECT id, title FROM roles ORDER BY id").fetchall():
        perms = conn.execute(
            "SELECT p.title FROM permissions p "
            "JOIN role_permissions rp ON rp.permission_id = p.id WHERE rp.role_id = ? ORDER BY p.id",
            (role["id"],),
        ).fetchall()
        result.append((role["title"], [p["title"] for p in perms]))
    return result


def get_permissions(conn, role_id):
    rows = conn.execute(
        "SELECT p.code FROM permissions p "
        "JOIN role_permissions rp ON rp.permission_id = p.id WHERE rp.role_id = ?",
        (role_id,),
    ).fetchall()
    return {r["code"] for r in rows}


def _check_password(password):
    if len(password) < MIN_PASSWORD_LEN:
        raise ValueError("Пароль должен быть не короче %d символов." % MIN_PASSWORD_LEN)


def _role_id(conn, role_code):
    row = conn.execute("SELECT id FROM roles WHERE code = ?", (role_code,)).fetchone()
    if not row:
        raise ValueError("Неизвестная роль: %s" % role_code)
    return row["id"]


def create_user(conn, username, full_name, password, role_code):
    username = username.strip().lower()
    if not username:
        raise ValueError("Логин не может быть пустым.")
    _check_password(password)
    role_id = _role_id(conn, role_code)
    try:
        conn.execute(
            "INSERT INTO users (username, full_name, password_hash, role_id) VALUES (?, ?, ?, ?)",
            (username, full_name.strip() or username,
             generate_password_hash(password, method=HASH_METHOD), role_id),
        )
    except sqlite3.IntegrityError:
        raise ValueError("Пользователь «%s» уже существует." % username)
    conn.commit()


def _require_user(conn, username):
    user = get_user_by_username(conn, username)
    if not user:
        raise ValueError("Пользователь «%s» не найден." % username)
    return user


def set_password(conn, username, password):
    user = _require_user(conn, username)
    _check_password(password)
    conn.execute(
        "UPDATE users SET password_hash = ?, failed_attempts = 0, locked_until = NULL WHERE id = ?",
        (generate_password_hash(password, method=HASH_METHOD), user["id"]),
    )
    conn.commit()


def set_role(conn, username, role_code):
    user = _require_user(conn, username)
    conn.execute("UPDATE users SET role_id = ? WHERE id = ?", (_role_id(conn, role_code), user["id"]))
    conn.commit()


def set_active(conn, username, active):
    user = _require_user(conn, username)
    conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if active else 0, user["id"]))
    conn.commit()


# --- Защита от подбора пароля ----------------------------------------------
def register_failed_login(conn, user_id):
    conn.execute("UPDATE users SET failed_attempts = failed_attempts + 1 WHERE id = ?", (user_id,))
    row = conn.execute("SELECT failed_attempts FROM users WHERE id = ?", (user_id,)).fetchone()
    if row and row["failed_attempts"] >= config.LOGIN_MAX_ATTEMPTS:
        conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = ? WHERE id = ?",
            (now_str(config.LOGIN_LOCK_MINUTES), user_id),
        )
    conn.commit()


def register_login_ok(conn, user_id):
    conn.execute(
        "UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = ? WHERE id = ?",
        (now_str(), user_id),
    )
    conn.commit()


# --- Журнал действий --------------------------------------------------------
def audit(conn, action, user=None, username=None, object_type=None, object_id=None, details=None):
    """Запись в журнал. Ошибка записи не должна ломать работу приложения."""
    try:
        ip = request.remote_addr if has_request_context() else None
        conn.execute(
            "INSERT INTO audit_log (at, user_id, username, action, object_type, object_id, ip, details) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now_str(),
                user["id"] if user else None,
                (user["username"] if user else (username or ""))[:64] or None,
                action,
                object_type,
                None if object_id is None else str(object_id)[:64],
                ip,
                details,
            ),
        )
        conn.commit()
    except sqlite3.Error:
        log.exception("Не удалось записать в журнал действий: %s", action)


def recent_audit(conn, limit=50):
    return conn.execute(
        "SELECT at, username, action, object_type, object_id, ip FROM audit_log "
        "ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
