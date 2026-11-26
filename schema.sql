-- Схема локальной базы (SQLite). Хранит ТОЛЬКО пользователей приложения, роли, права
-- и журнал действий. Медицинские данные пациентов здесь не хранятся — они остаются в API.
--
-- Перенос на PostgreSQL: INTEGER PRIMARY KEY AUTOINCREMENT -> BIGSERIAL PRIMARY KEY (или
-- GENERATED ALWAYS AS IDENTITY), datetime('now') -> now() AT TIME ZONE 'utc', TEXT-даты -> timestamptz.

PRAGMA foreign_keys = ON;

-- Роли сотрудников (набор уточняется у заказчика, см. seed.sql)
CREATE TABLE IF NOT EXISTS roles (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    code  TEXT NOT NULL UNIQUE,          -- латиницей, используется в коде и manage.py
    title TEXT NOT NULL                  -- название для интерфейса
);

-- Права (что можно делать в приложении)
CREATE TABLE IF NOT EXISTS permissions (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    code  TEXT NOT NULL UNIQUE,          -- например calls.view, cases.add
    title TEXT NOT NULL
);

-- Какая роль какие права имеет
CREATE TABLE IF NOT EXISTS role_permissions (
    role_id       INTEGER NOT NULL REFERENCES roles(id)       ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

-- Пользователи приложения (одна роль на пользователя)
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT    NOT NULL UNIQUE,      -- хранится в нижнем регистре
    full_name       TEXT    NOT NULL,
    password_hash   TEXT    NOT NULL,             -- хэш, пароль в открытом виде не хранится
    role_id         INTEGER NOT NULL REFERENCES roles(id),
    is_active       INTEGER NOT NULL DEFAULT 1,   -- 0 = вход запрещён
    failed_attempts INTEGER NOT NULL DEFAULT 0,   -- подряд неудачных входов
    locked_until    TEXT,                         -- UTC, до какого времени вход заблокирован
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    last_login_at   TEXT
);

-- Журнал действий: кто, когда, что делал. Содержимое записей (текст дневников,
-- диагнозы и т.п.) сюда НЕ пишется — только тип действия и идентификатор объекта.
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT    NOT NULL DEFAULT (datetime('now')),   -- UTC
    user_id     INTEGER REFERENCES users(id),
    username    TEXT,                -- копия логина (в т.ч. для неудачных входов)
    action      TEXT    NOT NULL,    -- login.ok, call.view, case.add, access.denied ...
    object_type TEXT,                -- call / patient
    object_id   TEXT,
    ip          TEXT,
    details     TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_at   ON audit_log(at);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
