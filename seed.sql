-- Начальные роли и права. Выполняются ТОЛЬКО при первом создании базы
-- (db.init_db проверяет, что таблица roles пуста). Поэтому отозванное
-- SQL-запросом право не вернётся после перезапуска приложения.
-- Для изменения прав на живой базе меняйте таблицу role_permissions напрямую.
--
-- ВАЖНО: набор ролей и прав — рабочая заготовка. ТЗ говорит, что конкретная роль
-- «уточняется», поэтому заказчик может поменять состав.
-- Для PostgreSQL: INSERT OR IGNORE -> INSERT ... ON CONFLICT DO NOTHING.

INSERT OR IGNORE INTO roles (code, title) VALUES
    ('admin',      'Администратор'),
    ('doctor',     'Врач'),
    ('paramedic',  'Фельдшер бригады'),
    ('dispatcher', 'Диспетчер');

INSERT OR IGNORE INTO permissions (code, title) VALUES
    ('calls.view',       'Просмотр списка и карточки вызова'),
    ('patients.view',    'Просмотр карточки пациента'),
    ('cases.add',        'Добавление случая медицинского обслуживания'),
    ('diaries.add',      'Добавление «Дневника»'),
    ('appointments.add', 'Запись пациента на приём'),
    ('portal.open',      'Переход на портал врача'),
    ('users.manage',     'Страница администратора: пользователи и журнал'),
    ('calls.manage',      'Взятие вызова, этап бригады, завершение (интерфейс /fe)');

-- Права по умолчанию
INSERT OR IGNORE INTO role_permissions (role_id, permission_id)
SELECT r.id, p.id
FROM roles r
JOIN permissions p ON
       r.code = 'admin'
    OR (r.code = 'doctor'     AND p.code IN ('calls.view', 'patients.view', 'cases.add', 'diaries.add', 'appointments.add', 'portal.open', 'calls.manage'))
    OR (r.code = 'paramedic'  AND p.code IN ('calls.view', 'patients.view', 'cases.add', 'diaries.add', 'portal.open', 'calls.manage'))
    OR (r.code = 'dispatcher' AND p.code IN ('calls.view'));
