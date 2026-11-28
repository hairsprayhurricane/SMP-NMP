"""Защищённый кэш чтения (задача «со звёздочкой» из ТЗ).

Последние успешно загруженные вызовы и карточки пациентов держатся в
оперативной памяти процесса — в виде шифротекста (Fernet), с ключом,
сгенерированным при старте и живущим только в ОЗУ. На диск ничего не
пишется; после перезапуска приложения ключ и кэш бесследно исчезают.

При обрыве связи с API страницы чтения отдают эти данные в режиме
«только чтение»: срок жизни записи ограничен TTL (CACHE_TTL_SECONDS),
просроченное считается отсутствующим.

Gunicorn с несколькими worker'ами: у каждого процесса свой ключ и свой
кэш (данные не покидают процесс) — поведение корректно, просто кэш не
общий между воркерами.
"""
import json
import logging
import threading
import time

import config

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - без библиотеки кэш просто выключен
    Fernet = None
    InvalidToken = Exception

log = logging.getLogger("smp.cache")

_cipher = None
_store = {}
_lock = threading.Lock()


def _ttl():
    return config.CACHE_TTL_SECONDS


def _fernet():
    """Шифратор с ключом только в памяти процесса (создаётся при первом обращении)."""
    global _cipher
    if _cipher is None:
        _cipher = Fernet(Fernet.generate_key())
    return _cipher


def available():
    return Fernet is not None and _ttl() > 0


def store(key, value):
    """Запомнить данные: шифруем и держим только в ОЗУ, с меткой времени."""
    if not available():
        return
    try:
        blob = _fernet().encrypt(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        return
    now = time.monotonic()
    with _lock:
        _store[key] = (now, blob)
        # подчистить просроченное, чтобы память не росла бесконечно
        for k in [k for k, (ts, _) in _store.items() if now - ts > _ttl()]:
            _store.pop(k, None)


def fetch(key):
    """Вернуть (данные, возраст_в_секундах) или (None, None).

    None — если записи нет, TTL истёк или расшифровать не удалось
    (например, после подмены ключа/памяти).
    """
    if not available():
        return (None, None)
    with _lock:
        entry = _store.get(key)
        if entry is None:
            return (None, None)
        stamp, blob = entry
    age = time.monotonic() - stamp
    if age > _ttl():
        with _lock:
            _store.pop(key, None)
        return (None, None)
    try:
        data = json.loads(_fernet().decrypt(blob).decode("utf-8"))
    except (InvalidToken, ValueError):
        log.warning("Кэш %r не расшифрован — запись отброшена", key)
        with _lock:
            _store.pop(key, None)
        return (None, None)
    return data, int(age)


def drop(key=None):
    """Забыть запись (или всё) — например, при успешном сохранении новых данных."""
    with _lock:
        if key is None:
            _store.clear()
        else:
            _store.pop(key, None)
