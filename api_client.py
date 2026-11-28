"""Клиент API СМП/НМП.

ВСЁ общение с внешним API живёт здесь. Шаблоны и app.py работают только с
нормализованными словарями (фиксированные имена полей). Если реальный API
называет поля иначе или у него другие адреса endpoint'ов — правится только
этот файл (константы EP_* и функции _norm_*).

В лог пишутся метод, адрес и код ответа. Тела запросов и ответов НЕ
логируются — там персональные и медицинские данные.
"""
import logging

import requests

import config
import secure_cache

log = logging.getLogger("smp.api")

# --- Endpoint'ы (под реальное API поменять здесь) --------------------------
EP_CALLS = "/api/calls"
EP_CALL = "/api/calls/{call_id}"
EP_CASES = "/api/calls/{call_id}/cases"
EP_DIARIES = "/api/calls/{call_id}/diaries"
EP_CALL_INFO = "/api/calls/{call_id}/info"
EP_CALL_INFO_MARK = "/api/calls/{call_id}/info/{item_id}/mark_incorrect"
EP_CALL_PROBLEMS = "/api/calls/{call_id}/problems"
EP_CALL_PROBLEM_MARK = "/api/calls/{call_id}/problems/{item_id}/mark_incorrect"
EP_PATIENT = "/api/patients/{patient_id}"
EP_APPOINTMENTS = "/api/patients/{patient_id}/appointments"


class ApiError(Exception):
    """Ошибка обращения к API. user_message показываем пользователю."""

    def __init__(self, user_message, detail=""):
        super().__init__(detail or user_message)
        self.user_message = user_message


class NotFoundError(ApiError):
    """API ответило 404."""


def _request(method, path, payload=None):
    if not config.API_BASE_URL:
        log.error("API_BASE_URL не задан в конфигурации")
        raise ApiError("Адрес API не настроен. Обратитесь к администратору.")

    url = config.API_BASE_URL + path
    headers = {"Accept": "application/json"}
    if config.API_TOKEN:
        headers["Authorization"] = "Bearer " + config.API_TOKEN

    log.info("API запрос: %s %s", method, url)
    try:
        resp = requests.request(
            method, url, json=payload, headers=headers, timeout=config.API_TIMEOUT
        )
    except requests.exceptions.Timeout:
        log.error("API таймаут (%ss): %s %s", config.API_TIMEOUT, method, url)
        raise ApiError("Сервер не ответил вовремя. Попробуйте ещё раз через несколько секунд.")
    except requests.exceptions.ConnectionError as exc:
        log.error("API нет связи: %s %s (%s)", method, url, exc.__class__.__name__)
        raise ApiError("Нет связи с сервером. Проверьте подключение (VPN) и повторите попытку.")
    except requests.exceptions.RequestException as exc:
        log.error("API ошибка запроса: %s %s (%s)", method, url, exc.__class__.__name__)
        raise ApiError("Не удалось выполнить запрос к серверу.")

    log.info("API ответ: %s %s -> %s", method, url, resp.status_code)

    if resp.status_code == 404:
        raise NotFoundError("Запись не найдена на сервере.")
    if 400 <= resp.status_code < 500:
        reason = _error_text(resp)
        log.error("API отклонило запрос: %s %s -> %s", method, url, resp.status_code)
        msg = "Сервер отклонил запрос (код %s)." % resp.status_code
        if reason:
            msg += " " + reason
        raise ApiError(msg)
    if resp.status_code >= 500:
        log.error("API ошибка сервера: %s %s -> %s", method, url, resp.status_code)
        raise ApiError("Ошибка на стороне сервера (код %s). Попробуйте позже." % resp.status_code)

    try:
        return resp.json()
    except ValueError:
        log.error("API вернуло не-JSON: %s %s", method, url)
        raise ApiError("Сервер вернул ответ в непонятном формате.")


def _error_text(resp):
    """Короткий текст причины из ответа API, если он есть (поле error/message)."""
    try:
        data = resp.json()
    except ValueError:
        return ""
    if isinstance(data, dict):
        text = data.get("error") or data.get("message") or ""
        return str(text)[:200]
    return ""


# --- Нормализаторы: raw JSON API -> фиксированные поля для шаблонов --------
def _pick(raw, *keys, default=""):
    """Первое непустое значение из raw по списку возможных имён поля."""
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return default


def _as_list(data, *keys):
    """API может вернуть список или объект со списком внутри."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return data[key]
    raise ApiError("Сервер вернул данные в неожиданном формате.")


def _as_dict(data):
    if isinstance(data, dict):
        return data
    raise ApiError("Сервер вернул данные в неожиданном формате.")


def _coord(raw, keys, low, high):
    """Координата из raw (число или строка) или None, если её нет или она некорректна."""
    for key in keys:
        value = raw.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(str(value).replace(",", "."))
        except ValueError:
            return None
        return number if low <= number <= high else None  # NaN тоже даёт None
    return None


def _norm_call(raw):
    lat = _coord(raw, ("lat", "latitude"), -90, 90)
    lon = _coord(raw, ("lon", "lng", "longitude"), -180, 180)
    if lat is None or lon is None or (lat == 0 and lon == 0):
        lat = lon = None  # нужна пара; (0, 0) обычно означает «координат нет»
    return {
        "lat": lat,
        "lon": lon,
        "id": _pick(raw, "id", "call_id"),
        "number": _pick(raw, "number", "call_number"),
        "address": _pick(raw, "address"),
        "reason": _pick(raw, "reason", "complaint"),
        "status": _pick(raw, "status"),
        "received_at": _pick(raw, "received_at", "created_at"),
        "patient_id": _pick(raw, "patient_id"),
        "patient_name": _pick(raw, "patient_name", "patient_full_name"),
        # Поля состояния вызова для интерфейса /fe. Реальное API может их
        # не отдавать — тогда значения по умолчанию, и страницы /fe деградируют
        # мягечно (без взятия вызовов).
        "priority": _pick(raw, "priority"),
        "active_owner": _pick(raw, "active_owner") or None,
        "status_progress": _pick(raw, "status_progress") or None,
        "is_completed": bool(raw.get("completed", raw.get("is_completed", False))),
        "result": _pick(raw, "result") or None,
    }


def _norm_patient(raw):
    return {
        "id": _pick(raw, "id", "patient_id"),
        "full_name": _pick(raw, "full_name", "fio", "name"),
        "birth_date": _pick(raw, "birth_date", "birthday"),
        "gender": _pick(raw, "gender", "sex"),
        "oms_policy": _pick(raw, "oms_policy", "polis_oms", "oms"),
        "phone": _pick(raw, "phone"),
        "allergies": _pick(raw, "allergies"),
        "chronic_diseases": _pick(raw, "chronic_diseases", "chronic"),
    }


def _norm_case(raw):
    return {
        "id": _pick(raw, "id"),
        "created_at": _pick(raw, "created_at"),
        "complaints": _pick(raw, "complaints"),
        "diagnosis": _pick(raw, "diagnosis"),
        "actions": _pick(raw, "actions"),
        "outcome": _pick(raw, "outcome"),
        # Поля варианта /fe
        "author": _pick(raw, "author"),
        "type": _pick(raw, "type"),
        "result": _pick(raw, "result"),
        "text": _pick(raw, "text"),
        "time": _pick(raw, "created_at"),
    }


def _norm_diary(raw):
    return {
        "id": _pick(raw, "id"),
        "created_at": _pick(raw, "created_at"),
        "author": _pick(raw, "author"),
        "text": _pick(raw, "text"),
        "type": _pick(raw, "type"),
        "time": _pick(raw, "created_at"),
    }


def _norm_info(raw):
    """Запись «информация про пациента» или «проблема на вызове» (интерфейс /fe)."""
    return {
        "id": _pick(raw, "id"),
        "author": _pick(raw, "author"),
        "type": _pick(raw, "type"),
        "text": _pick(raw, "text"),
        "time": _pick(raw, "time"),
        "incorrect": bool(raw.get("incorrect", False)),
    }


def _norm_appointment(raw):
    return {
        "id": _pick(raw, "id"),
        "specialty": _pick(raw, "specialty", "doctor"),
        "date": _pick(raw, "date"),
        "time": _pick(raw, "time"),
        "comment": _pick(raw, "comment", "note"),
        "created_by": _pick(raw, "created_by"),
    }


# --- Публичные функции ------------------------------------------------------
def get_calls():
    data = _request("GET", EP_CALLS)
    calls = [_norm_call(r) for r in _as_list(data, "calls", "items") if isinstance(r, dict)]
    secure_cache.store("calls", calls)
    return calls


def get_cached_calls():
    """Последний загруженный список вызовов из кэша в ОЗУ: (список, возраст_сек)."""
    return secure_cache.fetch("calls")


def get_call(call_id):
    return _norm_call(_as_dict(_request("GET", EP_CALL.format(call_id=call_id))))


def get_patient(patient_id):
    patient = _norm_patient(_as_dict(_request("GET", EP_PATIENT.format(patient_id=patient_id))))
    secure_cache.store("patient:%s" % patient_id, patient)
    return patient


def get_cached_patient(patient_id):
    """Последняя загруженная карточка пациента из кэша в ОЗУ: (данные, возраст_сек)."""
    return secure_cache.fetch("patient:%s" % patient_id)


def get_cases(call_id):
    data = _request("GET", EP_CASES.format(call_id=call_id))
    return [_norm_case(r) for r in _as_list(data, "cases", "items") if isinstance(r, dict)]


def get_diaries(call_id):
    data = _request("GET", EP_DIARIES.format(call_id=call_id))
    return [_norm_diary(r) for r in _as_list(data, "diaries", "items") if isinstance(r, dict)]


def get_appointments(patient_id):
    data = _request("GET", EP_APPOINTMENTS.format(patient_id=patient_id))
    return [
        _norm_appointment(r)
        for r in _as_list(data, "appointments", "items")
        if isinstance(r, dict)
    ]


def create_case(call_id, values):
    return _request("POST", EP_CASES.format(call_id=call_id), values)


def create_diary(call_id, values):
    return _request("POST", EP_DIARIES.format(call_id=call_id), values)


def create_appointment(patient_id, values):
    return _request("POST", EP_APPOINTMENTS.format(patient_id=patient_id), values)


# --- Управление состоянием вызова и записи интерфейса /fe -------------------
def update_call(call_id, values):
    """Взятие/освобождение вызова, этап бригады, завершение (ложный/нормальный)."""
    return _request("PATCH", EP_CALL.format(call_id=call_id), values)


def get_call_info(call_id):
    data = _request("GET", EP_CALL_INFO.format(call_id=call_id))
    return [_norm_info(r) for r in _as_list(data, "items") if isinstance(r, dict)]


def create_call_info(call_id, values):
    return _request("POST", EP_CALL_INFO.format(call_id=call_id), values)


def mark_call_info_incorrect(call_id, item_id):
    return _request("POST", EP_CALL_INFO_MARK.format(call_id=call_id, item_id=item_id), {})


def get_call_problems(call_id):
    data = _request("GET", EP_CALL_PROBLEMS.format(call_id=call_id))
    return [_norm_info(r) for r in _as_list(data, "items") if isinstance(r, dict)]


def create_call_problem(call_id, values):
    return _request("POST", EP_CALL_PROBLEMS.format(call_id=call_id), values)


def mark_call_problem_incorrect(call_id, item_id):
    return _request("POST", EP_CALL_PROBLEM_MARK.format(call_id=call_id, item_id=item_id), {})
