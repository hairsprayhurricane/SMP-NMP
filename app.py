"""Веб-приложение для сотрудников СМП/НМП (Flask).

Данные вызовов и пациентов запрашиваются у API через api_client.py и нигде не
сохраняются. Локальная SQL-база (db.py) хранит только пользователей, роли, права
и журнал действий.

Помимо корневых экранов приложение включает второй набор страниц из ветки
Frontend (модуль fe_views.py, префикс /fe: список вызовов, карта, карточки).

Запуск для разработки:  python app.py  (слушает только 127.0.0.1)
Боевой запуск:          gunicorn -w 2 -b 0.0.0.0:8000 app:app

Внешние подключения принимает только Gunicorn — встроенный сервер Flask
привязан к 127.0.0.1 и доступен лишь с самой машины.
"""
import hmac
import logging
import os
import secrets
import sqlite3
from datetime import date, datetime, time, timedelta
from logging.handlers import RotatingFileHandler

from flask import Flask, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

import api_client as api
import auth
import config
import db
import fe_views
import maps
from api_client import ApiError, NotFoundError
from auth import permission_required

log = logging.getLogger("smp.app")


def setup_logging():
    """Лог в файл logs/app.log (с ротацией) и в консоль."""
    root = logging.getLogger()
    if any(getattr(h, "_smp", False) for h in root.handlers):
        return  # уже настроено (перезагрузка / повторный импорт)

    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console._smp = True
    root.addHandler(console)

    try:
        os.makedirs(config.LOG_DIR, exist_ok=True)
        fh = RotatingFileHandler(
            os.path.join(config.LOG_DIR, "app.log"),
            maxBytes=1_000_000,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        fh._smp = True
        root.addHandler(fh)
    except OSError as exc:
        logging.getLogger("smp.app").warning("Лог в файл недоступен: %s", exc)


setup_logging()

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=config.SESSION_HOURS)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = config.SESSION_COOKIE_SECURE
if config.TRUST_PROXY:
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

app.register_blueprint(auth.bp)
app.register_blueprint(fe_views.bp)
app.teardown_appcontext(db.close_db)

if config.SECRET_KEY_SOURCE == "file":
    log.info("SECRET_KEY не задан в .env — ключ сессий хранится в файле data/secret.key (в Git не попадает)")
elif config.SECRET_KEY_SOURCE == "memory":
    log.warning(
        "SECRET_KEY не задан в .env и записать data/secret.key не удалось — ключ случайный. "
        "После перезапуска все будут разлогинены, а при нескольких worker'ах Gunicorn вход не заработает."
    )
if not config.API_BASE_URL:
    log.warning("API_BASE_URL не задан — запросы к API выполняться не будут")


def init_database():
    """Создаёт таблицы и роли при первом запуске (повторный запуск безопасен)."""
    try:
        conn = db.connect()
        try:
            db.init_db(conn)
            if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                log.warning(
                    "В базе нет пользователей. Создайте первого: "
                    "python manage.py create-user admin --role admin"
                )
        finally:
            conn.close()
    except (OSError, sqlite3.Error):
        log.exception("Не удалось подготовить базу данных: %s", config.DB_PATH)


init_database()


# ---------------------------------------------------------------------------
# Вспомогательное для шаблонов
# ---------------------------------------------------------------------------
STATUS_CLASSES = {
    "новый": "danger",
    "в пути": "warning",
    "на месте": "primary",
    "завершён": "success",
    "завершен": "success",
}

SPECIALTIES = [
    "Терапевт",
    "Кардиолог",
    "Невролог",
    "Хирург",
    "Педиатр",
    "Эндокринолог",
]
OUTCOMES = [
    "Помощь оказана на месте",
    "Госпитализация",
    "Передан другой бригаде",
    "Отказ от помощи",
]

# Максимальная длина полей форм: сохраняется в API без обрезки, поэтому
# проверяем на входе, чтобы пользователю не приходилось гадать.
FIELD_LIMITS = {
    "complaints": (2000, "жалобы"),
    "diagnosis": (500, "диагноз"),
    "actions": (2000, "оказанная помощь"),
    "outcome": (200, "исход"),
    "specialty": (100, "врач"),
    "comment": (500, "комментарий"),
    "time": (5, "время"),
    "date": (10, "дата"),
    "text": (5000, "текст"),
}


def _validate_lengths(values, fields):
    """Проверка длины полей; возвращает текст ошибки или None."""
    for f in fields:
        limit, label = FIELD_LIMITS[f]
        if len(values.get(f, "")) > limit:
            return "Поле «%s» слишком длинное: не более %d символов." % (label, limit)
    return None


def _csrf_token():
    """Токен защиты форм от отправки с чужих страниц (CSRF), хранится в сессии."""
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


@app.before_request
def _check_csrf():
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        # Офлайн-очередь (static/js/form.js) досылает форму JSON-ом: токен
        # приходит в теле, а не в form-data. Без этой ветки такие POST'ы
        # отклонялись бы с 400 и поставленные в очередь записи терялись.
        if not sent and request.is_json:
            body = request.get_json(silent=True)
            if isinstance(body, dict):
                sent = body.get("_csrf", "")
        sent = (sent if isinstance(sent, str) else "").encode("utf-8")
        expected = session.get("_csrf", "").encode("utf-8")
        if not expected or not hmac.compare_digest(sent, expected):
            log.warning("CSRF: отклонён POST %s", request.path)
            abort(400, description="Сессия устарела. Откройте форму заново и повторите.")


@app.context_processor
def inject_globals():
    bootstrap_local = os.path.exists(
        os.path.join(app.static_folder, "vendor", "bootstrap.min.css")
    )
    perms = getattr(g, "perms", frozenset())
    leaflet_local = os.path.exists(os.path.join(app.static_folder, "vendor", "leaflet", "leaflet.js"))
    return {
        "leaflet_local": leaflet_local,
        "csrf_token": _csrf_token,
        "current_user": getattr(g, "user", None),
        "can": lambda code: code in perms,
        "doctor_portal_url": config.DOCTOR_PORTAL_URL,
        "bootstrap_local": bootstrap_local,
        "status_class": lambda s: STATUS_CLASSES.get(str(s).strip().lower(), "secondary"),
    }


@app.after_request
def _permissions_policy(resp):
    """Геолокацию разрешаем только страницам самого приложения; камера и микрофон не нужны."""
    resp.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
    # Страницы ошибок не кешируются: браузер не должен показывать устаревший
    # экран вместо повторного запроса.
    if resp.status_code >= 400:
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


def _audit(action, object_type=None, object_id=None):
    db.audit(db.get_db(), action, user=g.user, object_type=object_type, object_id=object_id)


# ---------------------------------------------------------------------------
# Экраны
# ---------------------------------------------------------------------------
@app.route("/")
@permission_required("calls.view")
def index():
    calls, failed = [], False
    try:
        calls = api.get_calls()
    except ApiError as exc:
        failed = True
        flash(exc.user_message, "danger")
    return render_template("index.html", calls=calls, failed=failed)


@app.route("/call/<call_id>")
@permission_required("calls.view")
def call_detail(call_id):
    try:
        call = api.get_call(call_id)
    except NotFoundError:
        return render_template("error.html", code=404, message="Вызов не найден."), 404
    except ApiError as exc:
        return render_template("error.html", code=502, message=exc.user_message), 502
    _audit("call.view", "call", call_id)

    # Случаи и дневники — дополнительные данные: их недоступность не ломает страницу.
    cases, diaries = [], []
    records_failed = False
    try:
        cases = api.get_cases(call_id)
        diaries = api.get_diaries(call_id)
    except ApiError as exc:
        records_failed = True
        flash("Не удалось загрузить случаи и дневники. " + exc.user_message, "warning")
    return render_template(
        "call_detail.html",
        call=call,
        map_info=maps.build(call),
        cases=cases,
        diaries=diaries,
        records_failed=records_failed,
    )


@app.route("/patient/<patient_id>")
@permission_required("patients.view")
def patient_detail(patient_id):
    call_id = request.args.get("call", "")
    try:
        patient = api.get_patient(patient_id)
    except NotFoundError:
        return render_template("error.html", code=404, message="Пациент не найден."), 404
    except ApiError as exc:
        return render_template("error.html", code=502, message=exc.user_message), 502
    _audit("patient.view", "patient", patient_id)

    appointments, appointments_failed = [], False
    try:
        appointments = api.get_appointments(patient_id)
    except ApiError as exc:
        appointments_failed = True
        flash("Не удалось загрузить записи на приём. " + exc.user_message, "warning")
    return render_template(
        "patient.html",
        patient=patient,
        call_id=call_id,
        appointments=appointments,
        appointments_failed=appointments_failed,
    )


# ---------------------------------------------------------------------------
# Формы создания записей
# ---------------------------------------------------------------------------
def _form_view(template, fields, required, send, success_url, success_msg, log_msg,
               audit=None, validate=None, initial=None, **ctx):
    """Общая логика трёх форм.

    fields   — имена полей формы;
    required — {поле: название для сообщения об ошибке};
    send     — функция отправки в API (получает словарь значений);
    audit    — (действие, тип объекта, id объекта) для журнала;
    initial  — значения полей по умолчанию при открытии формы.
    При ошибке введённые данные остаются в форме, чтобы их не пришлось набирать заново.
    """
    values = {f: "" for f in fields}
    if request.method == "POST":
        # Обычный POST приходит form-data, отложенный офлайн-записью — JSON.
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            data = request.form
        values = {f: str(data.get(f, "") or "").strip() for f in fields}
        missing = [label for f, label in required.items() if not values[f]]
        if missing:
            flash("Заполните обязательные поля: " + ", ".join(missing) + ".", "warning")
            return render_template(template, values=values, **ctx)
        problem = validate(values) if validate else None
        if problem:
            flash(problem, "warning")
            return render_template(template, values=values, **ctx)
        try:
            send(values)
        except ApiError as exc:
            flash("Запись не сохранена. " + exc.user_message, "danger")
            return render_template(template, values=values, **ctx)
        log.info("%s (пользователь %s)", log_msg, g.user["username"])
        if audit:
            _audit(*audit)
        flash(success_msg, "success")
        return redirect(success_url)
    if initial:
        values.update(initial)
    return render_template(template, values=values, **ctx)


@app.route("/call/<call_id>/case/new", methods=["GET", "POST"])
@permission_required("cases.add")
def case_new(call_id):
    return _form_view(
        "form_case.html",
        fields=["complaints", "diagnosis", "actions", "outcome"],
        required={
            "complaints": "жалобы",
            "diagnosis": "диагноз",
            "actions": "оказанная помощь",
            "outcome": "исход",
        },
        validate=lambda v: _validate_lengths(v, ("complaints", "diagnosis", "actions", "outcome")),
        send=lambda v: api.create_case(call_id, v),
        success_url=url_for("call_detail", call_id=call_id),
        success_msg="Случай медицинского обслуживания добавлен.",
        log_msg="Добавлен случай обслуживания по вызову %s" % call_id,
        audit=("case.add", "call", call_id),
        call_id=call_id,
        outcomes=OUTCOMES,
    )


@app.route("/call/<call_id>/diary/new", methods=["GET", "POST"])
@permission_required("diaries.add")
def diary_new(call_id):
    # Поле «автор» не редактируется пользователем: оно подставляется из учётной
    # записи вошедшего сотрудника (g.user) и в HTML-форме не выводится.
    return _form_view(
        "form_diary.html",
        fields=["text"],
        required={"text": "текст"},
        validate=lambda v: _validate_lengths(v, ("text",)),
        send=lambda v: api.create_diary(call_id, {"author": g.user["full_name"], **v}),
        success_url=url_for("call_detail", call_id=call_id),
        success_msg="Дневник добавлен.",
        log_msg="Добавлен дневник по вызову %s" % call_id,
        audit=("diary.add", "call", call_id),
        author=g.user["full_name"],
        call_id=call_id,
    )


def _validate_appointment(values):
    """Дата/время приёма: формат, не прошлое, не 00:00 (пустое значение поля time)."""
    try:
        day = datetime.strptime(values["date"], "%Y-%m-%d").date()
    except ValueError:
        return "Некорректная дата приёма."
    try:
        moment = datetime.strptime(values["time"], "%H:%M").time()
    except ValueError:
        return "Некорректное время приёма (нужен формат ЧЧ:ММ)."
    if moment == time(0, 0):
        return "Время 00:00 недопустимо: укажите реальное время приёма."
    if datetime.combine(day, moment) <= datetime.now():
        return "Дата и время приёма не могут быть в прошлом."
    if day < date.today():
        return "Дата приёма не может быть в прошлом."
    return None


@app.route("/patient/<patient_id>/appointment/new", methods=["GET", "POST"])
@permission_required("appointments.add")
def appointment_new(patient_id):
    call_id = request.args.get("call", "")
    return _form_view(
        "form_appointment.html",
        fields=["specialty", "date", "time", "comment"],
        required={"specialty": "врач", "date": "дата", "time": "время"},
        send=lambda v: api.create_appointment(patient_id, v),
        success_url=url_for("patient_detail", patient_id=patient_id, call=call_id or None),
        success_msg="Пациент записан на приём.",
        log_msg="Создана запись на приём для пациента %s" % patient_id,
        audit=("appointment.add", "patient", patient_id),
        validate=lambda v: _validate_appointment(v) or _validate_lengths(v, ("specialty", "comment")),
        patient_id=patient_id,
        call_id=call_id,
        specialties=SPECIALTIES,
        today=date.today().isoformat(),
    )


# ---------------------------------------------------------------------------
# Администрирование (только чтение): пользователи, роли и журнал действий
# ---------------------------------------------------------------------------
@app.route("/admin")
@permission_required("users.manage")
def admin():
    conn = db.get_db()
    return render_template(
        "admin.html",
        users=db.list_users(conn),
        role_matrix=db.role_permissions_matrix(conn),
        events=db.recent_audit(conn, 50),
    )


# ---------------------------------------------------------------------------
# Ошибки приложения: белого экрана с Traceback быть не должно
# ---------------------------------------------------------------------------
@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, HTTPException):
        code = exc.code or 500
        message = "Страница не найдена." if code == 404 else (exc.description or "Ошибка запроса.")
    else:
        log.exception("Необработанная ошибка приложения")
        code = 500
        message = "Внутренняя ошибка приложения. Попробуйте вернуться к списку вызовов."
    return render_template("error.html", code=code, message=message), code


if __name__ == "__main__":
    # Только 127.0.0.1: наружу приложение отдаёт Gunicorn (см. docstring).
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "8000")), debug=False)
