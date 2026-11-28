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
import math
import os
import secrets
import sqlite3
import tempfile
from datetime import date, datetime, time, timedelta
from logging.handlers import RotatingFileHandler

import requests
from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
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
# Тайлы карты: локальный прокси, диск-кэш и предзагрузка для офлайна
# ---------------------------------------------------------------------------
def _latlon_to_tile(lat, lon, z):
    """Номер тайла Web Mercator (та же схема, что у 2ГИС)."""
    n = 1 << z
    lon = max(-180.0, min(180.0, float(lon)))
    lat = max(-85.05112878, min(85.05112878, float(lat)))
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int(
        (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi)
        / 2.0 * n
    )
    return max(0, min(n - 1, x)), max(0, min(n - 1, y))


def _precache_bbox():
    """min_lat, min_lon, max_lat, max_lon из конфигурации (с безопасным дефолтом)."""
    try:
        values = tuple(float(v) for v in config.MAP_PRECACHE_BBOX.split(","))
        if len(values) == 4 and values[0] < values[2] and values[1] < values[3]:
            return values
    except (TypeError, ValueError):
        pass
    return (43.40, 39.30, 43.95, 40.00)


def _precache_zooms():
    """Диапазон зумов «11-13» -> (11, 13)."""
    raw = (config.MAP_PRECACHE_ZOOMS or "").strip()
    try:
        if "-" in raw:
            zmin, zmax = (int(part) for part in raw.split("-", 1))
        else:
            zmin = zmax = int(raw)
    except ValueError:
        zmin, zmax = 11, 13
    zmin = max(0, min(18, zmin))
    zmax = max(0, min(18, zmax))
    return (zmin, zmax) if zmin <= zmax else (zmax, zmin)


@app.route("/tiles/manifest.json")
def map_tile_manifest():
    """Список тайлов для service worker: что скачать в кэш браузера."""
    min_lat, min_lon, max_lat, max_lon = _precache_bbox()
    zmin, zmax = _precache_zooms()
    tiles = []
    for z in range(zmin, zmax + 1):
        x1, y1 = _latlon_to_tile(max_lat, min_lon, z)
        x2, y2 = _latlon_to_tile(min_lat, max_lon, z)
        for x in range(x1, x2 + 1):
            for y in range(y1, y2 + 1):
                tiles.append("/tiles/%d/%d/%d.png" % (z, x, y))
    return jsonify({
        "tiles": tiles,
        "count": len(tiles),
        "zmin": zmin,
        "zmax": zmax,
        "bbox": [min_lat, min_lon, max_lat, max_lon],
    })


@app.route("/tiles/<int:z>/<int:x>/<int:y>.png")
def map_tile(z, x, y):
    """Отдаёт тайл из диска, а при промахе скачивает и кладёт в кэш.

    Скачивание идёт только на хост из MAP_TILE_UPSTREAM; z/x/y приходят
    целыми числами из маршрута, поэтому SSRF через параметры невозможен.
    """
    if z < 0 or z > 18:
        return Response(status=404)
    n = 1 << z
    if not (0 <= x < n and 0 <= y < n):
        return Response(status=404)

    path = os.path.join(config.MAP_TILE_CACHE_DIR, str(z), str(x), "%d.png" % y)
    if os.path.isfile(path):
        return send_file(path, mimetype="image/png", max_age=604800)

    upstream = config.MAP_TILE_UPSTREAM
    if not all(key in upstream for key in ("{x}", "{y}", "{z}")):
        log.error("MAP_TILE_UPSTREAM должен содержать {x}, {y} и {z}")
        return Response(status=404)

    url = upstream.format(x=x, y=y, z=z)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        ),
        "Referer": "https://2gis.ru/",
        "Accept": "image/png,image/*;q=0.8",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=config.API_TIMEOUT)
    except requests.RequestException as exc:
        log.warning("Тайл %s/%s/%s не скачан: %s", z, x, y, exc)
        return Response(status=404)
    if resp.status_code != 200 or not resp.content:
        log.warning("Тайл %s/%s/%s: HTTP %s", z, x, y, resp.status_code)
        return Response(status=404)

    ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype not in ("image/png", "image/jpeg", "image/webp"):
        log.warning("Тайл %s/%s/%s: неожиданный Content-Type %s", z, x, y, ctype)
        return Response(status=404)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="tile-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(resp.content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    return Response(
        resp.content,
        mimetype=ctype,
        headers={"Cache-Control": "public, max-age=604800"},
    )


@app.route("/sw.js")
def service_worker():
    """Service worker отдаётся с корня, чтобы управлять и /, и /fe/."""
    resp = send_from_directory(
        os.path.join(app.static_folder, "js"),
        "sw.js",
        mimetype="application/javascript",
    )
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


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
        "map_tile_url": config.MAP_TILE_URL,
        "map_attribution": config.MAP_ATTRIBUTION,
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
    calls, failed, read_only = [], False, False
    try:
        calls = api.get_calls()
    except ApiError as exc:
        stale, age = api.get_cached_calls()
        if stale is not None:
            calls = stale
            read_only = True
            flash(
                "Нет связи с сервером: показан последний загруженный список вызовов "
                "(возраст %d с). Данные только для чтения; создание новых записей "
                "временно недоступно." % age,
                "warning",
            )
        else:
            failed = True
            flash(exc.user_message, "danger")
    return render_template("index.html", calls=calls, failed=failed, read_only=read_only)


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
    read_only = False
    try:
        patient = api.get_patient(patient_id)
    except NotFoundError:
        return render_template("error.html", code=404, message="Пациент не найден."), 404
    except ApiError as exc:
        stale, age = api.get_cached_patient(patient_id)
        if stale is None:
            return render_template("error.html", code=502, message=exc.user_message), 502
        patient = stale
        read_only = True
        flash(
            "Нет связи с сервером: показана последняя загруженная карточка пациента "
            "(возраст %d с). Данные только для чтения; запись на приём "
            "временно недоступна." % age,
            "warning",
        )
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
        read_only=read_only,
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
