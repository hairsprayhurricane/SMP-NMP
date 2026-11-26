"""Интерфейс из ветки Frontend (префикс /fe).

Шаблоны — templates/fe/, статика — static/css|js/. В отличие от исходной ветки
Frontend, данные здесь берутся не из словарей в памяти, а через api_client.py из
API (мок или реального), а пользователи и роли — из локальной SQL-базы
(auth.py). Таким образом обе версии страниц (корневая и /fe) работают с одним
источником данных.

Соответствие ролей БД и старых ролей Frontend:
    doctor / paramedic -> фельдшер (в шаблонах /fe это 'doctor')
    admin             -> админ
    superadmin в БД нет; соответствующие ветки шаблонов просто не активируются.
"""
import math
from datetime import datetime

from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, session, url_for

import api_client as api
import config
import db
from api_client import ApiError, NotFoundError
from auth import permission_required

bp = Blueprint("fe", __name__, url_prefix="/fe")

PER_PAGE = 5
SEARCH_FIELDS = ("name", "address", "phone")

# Подстанция по умолчанию (Сочи). Здесь считается «расстояние до вызова» для
# сортировки и здесь же показываются машины без GPS.
BASE_LAT = 43.585
BASE_LNG = 39.723

PRIORITY_LABELS = {"emergency": "Экстренный", "urgent": "Неотложный", "planned": "Плановый"}
STATUS_LABELS = {"accepted": "Принят", "en_route": "В пути", "arrived": "Прибыл"}

INFO_TYPES = [
    "Данные о здоровье пациента",
    "Жалобы пациента",
    "Витальные показатели",
    "Лекарства / аллергии",
    "Другое",
]
PROBLEM_TYPES = ["Проблемы с автомобилем", "Проблемы с пациентом", "Другое"]
CASE_TYPES = ["Первичный вызов", "Повторный вызов", "Консультация", "Другое"]
DIARY_TYPES = ["Осмотр", "Наблюдение", "Изменение состояния", "Другое"]


def fe_role():
    """Роль текущего пользователя в терминах шаблонов /fe."""
    code = (g.user["role_code"] if g.user and "role_code" in g.user.keys() else "") or ""
    return "doctor" if code in ("doctor", "paramedic") else code


@bp.context_processor
def inject_fe_globals():
    user = g.get("user")
    current = None
    if user:
        current = {
            "login": user["username"],
            "name": user["full_name"],
            "role": fe_role(),
        }
    return {
        "current_user": current,
        "priority_labels": PRIORITY_LABELS,
        "status_labels": STATUS_LABELS,
        "doctor_portal_url": config.DOCTOR_PORTAL_URL,
    }


# ---------------------------------------------------------------------------
# Подготовка данных
# ---------------------------------------------------------------------------
def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _all_calls():
    """Все вызовы из API. При недоступности — пустой список + flash."""
    try:
        return api.get_calls()
    except ApiError as exc:
        flash("Не удалось загрузить вызовы. " + exc.user_message, "danger")
        return []


def _patients_for(calls):
    """Телефоны пациентов одним словарём {id: patient} для списка вызовов."""
    result = {}
    for call in calls:
        pid = str(call.get("patient_id") or "")
        if not pid or pid in result:
            continue
        try:
            result[pid] = api.get_patient(pid)
        except ApiError:
            result[pid] = None
    return result


def enrich_call(call, patient=None):
    lat, lng = call.get("lat"), call.get("lon")
    dist = round(haversine_km(BASE_LAT, BASE_LNG, lat, lng), 1) if lat and lng else None
    me = g.user["username"] if g.get("user") else None
    return {
        **call,
        "lng": call.get("lon"),
        "patient_name": call.get("patient_name") or "—",
        "patient_phone": (patient or {}).get("phone", "—"),
        "distance_km": dist,
        "is_completed": bool(call.get("is_completed")),
        "result": call.get("result"),
        "active_owner": call.get("active_owner"),
        "is_active_for_me": call.get("active_owner") == me,
        "status_progress": call.get("status_progress"),
        "priority_label": PRIORITY_LABELS.get(call.get("priority"), call.get("priority") or ""),
        "status_label": STATUS_LABELS.get(call.get("status_progress"), "Принят"),
    }


def _filter_calls(all_calls, q, field):
    if not q:
        return all_calls
    q_low = q.lower()

    def match(c):
        if field == "name":
            return q_low in (c.get("patient_name") or "").lower()
        if field == "address":
            return q_low in (c.get("address") or "").lower()
        if field == "phone":
            norm_q = "".join(ch for ch in q if ch.isdigit())
            norm_p = "".join(ch for ch in (c.get("patient_phone") or "") if ch.isdigit())
            if norm_p.startswith("7"):
                norm_p = norm_p[1:]
            return norm_p.startswith(norm_q) and bool(norm_q)
        return False

    return [c for c in all_calls if match(c)]


PRIORITY_ORDER = {"emergency": 0, "urgent": 1, "planned": 2}


def _paginate(items, page):
    total = len(items)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = min(max(page, 1), total_pages)
    start = (page - 1) * PER_PAGE
    return items[start:start + PER_PAGE], page, total_pages


def _prepare(all_calls, q, field, view, page):
    me = g.user["username"] if g.get("user") else None
    items = list(all_calls)
    if q:
        items = _filter_calls(items, q, field)
    items.sort(key=lambda c: (c.get("created_at") or c.get("received_at") or ""), reverse=True)
    items.sort(key=lambda c: (bool(c.get("is_completed")), c.get("active_owner") != me))
    items.sort(key=lambda c: PRIORITY_ORDER.get(c.get("priority"), 99))
    if view == "nearest":
        items.sort(key=lambda c: (c.get("distance_km") is None, c.get("distance_km") or 0))
        return items[:1], 1, 1
    return _paginate(items, page)


def phone_mask_display(digits):
    template = "XXX XXX-XX-XX"
    out, di = "", 0
    for ch in template:
        if ch == "X":
            out += digits[di] if di < len(digits) else "X"
            di += 1
        else:
            out += ch
    return "+7 " + out


def _my_active(all_calls):
    me = g.user["username"] if g.get("user") else None
    return next((c for c in all_calls if c.get("active_owner") == me), None)


# ---------------------------------------------------------------------------
# Список и поиск вызовов
# ---------------------------------------------------------------------------
@bp.route("")
@bp.route("/")
@permission_required("calls.view")
def calls_list():
    page = request.args.get("page", 1, type=int) or 1
    q = (request.args.get("q") or "").strip()
    field = request.args.get("field") or "name"
    view = request.args.get("view") or "all"
    map_on = request.args.get("map") == "on"
    is_doctor = fe_role() == "doctor"
    list_on = request.args.get("list") == "on" or is_doctor
    accept_id = request.args.get("accept_id", type=int)
    focus_call = request.args.get("focus", type=int)
    if field not in SEARCH_FIELDS:
        field = "name"

    all_calls = _all_calls()
    my_active_raw = _my_active(all_calls)

    # Телефоны пациентов нужны: для страницы, поиска по телефону и активного вызова.
    need_patients = field == "phone" or bool(q and field == "phone") or my_active_raw is not None
    patients = _patients_for(all_calls) if need_patients else {}
    for c in all_calls:
        c["patient_phone"] = (patients.get(str(c.get("patient_id") or "")) or {}).get("phone", "")
    my_active = enrich_call(my_active_raw) if my_active_raw else None

    if view == "nearest":
        for c in all_calls:
            c["distance_km"] = enrich_call(c)["distance_km"]
        page_calls, page, total_pages = _prepare(all_calls, q, field, view, page)
    else:
        page_calls, page, total_pages = _prepare(all_calls, q, field, view, page)

    q_display = phone_mask_display("".join(ch for ch in q if ch.isdigit())) if field == "phone" and q else q
    page_calls = [enrich_call(c) for c in page_calls]

    return render_template(
        "fe/calls_list.html",
        calls=page_calls, page=page, total_pages=total_pages, total=len(all_calls),
        q=q, q_display=q_display, field=field, view=view,
        active_call_id=(my_active["id"] if my_active else None), my_active_call=my_active,
        map_on=map_on, list_on=list_on, accept_id=accept_id, focus_call=focus_call,
    )


@bp.route("/search")
@permission_required("calls.view")
def calls_search():
    page = request.args.get("page", 1, type=int) or 1
    q = (request.args.get("q") or "").strip()
    field = request.args.get("field") or "name"
    view = request.args.get("view") or "all"
    if field not in SEARCH_FIELDS:
        field = "name"

    all_calls = _all_calls()
    if field == "phone":
        patients = _patients_for(all_calls)
        for c in all_calls:
            c["patient_phone"] = (patients.get(str(c.get("patient_id") or "")) or {}).get("phone", "")
    my_active_raw = _my_active(all_calls)
    page_calls, page, total_pages = _prepare(all_calls, q, field, view, page)
    q_display = phone_mask_display("".join(ch for ch in q if ch.isdigit())) if field == "phone" and q else q
    page_calls = [enrich_call(c) for c in page_calls]

    return render_template(
        "fe/_calls_results.html",
        calls=page_calls, page=page, total_pages=total_pages, total=len(all_calls),
        q=q, q_display=q_display, field=field, view=view,
        active_call_id=(my_active_raw or {}).get("id"),
    )


@bp.route("/api/map_data")
@permission_required("calls.view")
def api_map_data():
    view = request.args.get("view") or "all"
    is_admin = fe_role() in ("admin",)
    all_calls = []
    try:
        all_calls = api.get_calls()
    except ApiError:
        return jsonify({"calls": [], "doctors": [], "error": "api"})

    items = [c for c in all_calls if not c.get("is_completed")]
    if view == "nearest":
        items = sorted(
            items,
            key=lambda c: (c.get("lat") is None, haversine_km(BASE_LAT, BASE_LNG, c.get("lat") or 0, c.get("lon") or 0)),
        )[:1]

    calls_data = [
        {
            "id": c["id"], "lat": c.get("lat"), "lng": c.get("lon"),
            "patient_id": c.get("patient_id"), "patient_name": c.get("patient_name") or "—",
            "address": c.get("address"), "priority": c.get("priority"),
            "priority_label": PRIORITY_LABELS.get(c.get("priority"), c.get("priority") or ""),
            "reason": c.get("reason") or "",
            "is_completed": bool(c.get("is_completed")), "result": c.get("result"),
            "active_owner": c.get("active_owner"),
        }
        for c in items
    ]

    doctors = []
    if is_admin:
        conn = db.get_db()
        for user in db.list_users(conn):
            role = user["role_code"]
            if role not in ("doctor", "paramedic"):
                continue
            active_call = next(
                (c["id"] for c in all_calls if c.get("active_owner") == user["username"]), None
            )
            doctors.append({
                "login": user["username"],
                "name": user["full_name"],
                # GPS у машин нет: показываем базовую точку подстанции.
                "lat": BASE_LAT, "lng": BASE_LNG,
                "active_call_id": active_call,
            })
    return jsonify({"calls": calls_data, "doctors": doctors})


# ---------------------------------------------------------------------------
# Карточка вызова и действия бригады
# ---------------------------------------------------------------------------
def _load_call(call_id):
    try:
        return api.get_call(str(call_id))
    except NotFoundError:
        flash("Вызов #%s не найден" % call_id, "danger")
    except ApiError as exc:
        flash("Не удалось загрузить вызов. " + exc.user_message, "danger")
    return None


def _load_call_safe(call_id):
    """Вызов + ошибки чтения — при сбоях страницы не падают, а показывают пустые списки."""
    call, err = None, None
    try:
        call = api.get_call(str(call_id))
    except NotFoundError:
        err = ("Вызов #%s не найден" % call_id, "danger")
    except ApiError as exc:
        err = ("Не удалось загрузить вызов. " + exc.user_message, "danger")
    return call, err


def _require_my_call(call_id):
    """Вызов должен существовать и быть моим активным."""
    call, err = _load_call_safe(call_id)
    if err:
        flash(*err)
        return None, redirect(url_for("fe.calls_list"))
    if call.get("active_owner") != g.user["username"]:
        flash("Это действие доступно только для вашего активного вызова.", "danger")
        return None, redirect(url_for("fe.call_card", call_id=call_id))
    return call, None


def _call_records(call_id):
    """Дополнительные данные карточки вызова: info, problems, cases, diary."""
    info, problems, cases, diary = [], [], [], []
    try:
        info = api.get_call_info(str(call_id))
    except ApiError:
        pass
    try:
        problems = api.get_call_problems(str(call_id))
    except ApiError:
        pass
    try:
        cases = api.get_cases(str(call_id))
    except ApiError:
        pass
    try:
        diary = api.get_diaries(str(call_id))
    except ApiError:
        pass

    def fe_case(c):
        text = c.get("text")
        if not text:
            text = "; ".join(filter(None, [c.get("complaints"), c.get("diagnosis"), c.get("actions")]))
        return {"time": c.get("time") or c.get("created_at"), "type": c.get("type") or "Случай", "text": text}

    def fe_diary(d):
        return {"time": d.get("time") or d.get("created_at"), "type": d.get("type") or "Запись", "text": d.get("text")}

    return info, problems, [fe_case(c) for c in cases], [fe_diary(d) for d in diary]


@bp.route("/call/<int:call_id>")
@permission_required("calls.view")
def call_card(call_id):
    call, err = _load_call_safe(call_id)
    if err:
        flash(*err)
        return redirect(url_for("fe.calls_list"))
    info, problems, cases, diary = _call_records(call_id)
    try:
        patient = api.get_patient(str(call.get("patient_id") or ""))
    except ApiError:
        patient = None
    my_active_raw = _my_active(_all_calls()) if fe_role() == "doctor" else None
    return render_template(
        "fe/call_card.html",
        call=enrich_call(call, patient),
        patient_info=info, problems=problems, cases=cases, diary=diary,
        active_call_id=(my_active_raw or {}).get("id"),
    )


@bp.route("/call/<int:call_id>/accept", methods=["POST"])
@permission_required("calls.manage")
def call_accept(call_id):
    all_calls = _all_calls()
    call = next((c for c in all_calls if str(c["id"]) == str(call_id)), None)
    if not call:
        flash("Вызов #%s не найден" % call_id, "danger")
        return redirect(url_for("fe.calls_list"))
    if call.get("is_completed"):
        flash("Этот вызов уже завершён.", "warning")
        return redirect(url_for("fe.call_card", call_id=call_id))
    mine = _my_active(all_calls)
    if mine and str(mine["id"]) != str(call_id):
        flash("У вас уже активный вызов #%s. Завершите его сначала." % mine["id"], "danger")
        return redirect(url_for("fe.call_card", call_id=call_id))
    if call.get("active_owner") and call["active_owner"] != g.user["username"]:
        flash("Этот вызов уже взят другим сотрудником.", "danger")
        return redirect(url_for("fe.calls_list"))
    try:
        api.update_call(str(call_id), {"active_owner": g.user["username"], "status_progress": "accepted"})
    except ApiError as exc:
        flash("Не удалось взять вызов. " + exc.user_message, "danger")
        return redirect(url_for("fe.call_card", call_id=call_id))
    flash("Вызов #%s принят" % call_id, "success")
    return redirect(url_for("fe.call_card", call_id=call_id))


@bp.route("/call/<int:call_id>/status", methods=["POST"])
@permission_required("calls.manage")
def call_status(call_id):
    call, err = _load_call_safe(call_id)
    if err:
        flash(*err)
        return redirect(url_for("fe.calls_list"))
    if call.get("active_owner") != g.user["username"]:
        flash("Менять статус можно только у своего активного вызова.", "danger")
        return redirect(url_for("fe.call_card", call_id=call_id))
    new_status = request.form.get("status")
    if new_status not in ("en_route", "arrived"):
        abort(400, description="Некорректный статус")
    try:
        api.update_call(str(call_id), {"status_progress": new_status})
    except ApiError as exc:
        flash("Статус не обновлён. " + exc.user_message, "danger")
    else:
        flash("Статус обновлён: %s" % STATUS_LABELS.get(new_status, new_status), "success")
    return redirect(url_for("fe.call_card", call_id=call_id))


def _finish_call(call_id, result):
    call, err = _load_call_safe(call_id)
    if err:
        flash(*err)
        return redirect(url_for("fe.calls_list"))
    if call.get("active_owner") != g.user["username"]:
        flash("Завершить можно только свой активный вызов.", "danger")
        return redirect(url_for("fe.call_card", call_id=call_id))
    try:
        api.update_call(
            str(call_id),
            {"completed": True, "result": result, "active_owner": None, "status_progress": None},
        )
    except ApiError as exc:
        flash("Не удалось завершить вызов. " + exc.user_message, "danger")
        return redirect(url_for("fe.call_card", call_id=call_id))
    if result == "false":
        flash("Вызов #%s отмечен как ложный" % call_id, "warning")
    else:
        flash("Вызов #%s завершён" % call_id, "success")
    return redirect(url_for("fe.calls_list"))


@bp.route("/call/<int:call_id>/complete", methods=["POST"])
@permission_required("calls.manage")
def call_complete(call_id):
    return _finish_call(call_id, "normal")


@bp.route("/call/<int:call_id>/false", methods=["POST"])
@permission_required("calls.manage")
def call_false(call_id):
    return _finish_call(call_id, "false")


# ---------------------------------------------------------------------------
# Формы записей по вызову
# ---------------------------------------------------------------------------
@bp.route("/call/<int:call_id>/info/new", methods=["GET", "POST"])
@permission_required("calls.manage")
def info_new(call_id):
    call, redirect_ = _require_my_call(call_id)
    if redirect_:
        return redirect_
    if request.method == "POST":
        data = request.form.to_dict()
        try:
            api.create_call_info(str(call_id), {
                "author": g.user["username"], "type": data.get("type", ""), "text": data.get("text", ""),
            })
        except ApiError as exc:
            flash("Информация не сохранена. " + exc.user_message, "danger")
            return redirect(url_for("fe.info_new", call_id=call_id))
        flash("Информация сохранена", "success")
        return redirect(url_for("fe.call_card", call_id=call_id))
    return render_template(
        "fe/patient_info_form.html",
        form_title="Информация про пациента (вызов #%s)" % call_id,
        form_action=url_for("fe.info_new", call_id=call_id),
        info_types=INFO_TYPES, call_id=call_id,
    )


@bp.route("/call/<int:call_id>/problems/new", methods=["GET", "POST"])
@permission_required("calls.manage")
def problems_new(call_id):
    call, redirect_ = _require_my_call(call_id)
    if redirect_:
        return redirect_
    if request.method == "POST":
        data = request.form.to_dict()
        try:
            api.create_call_problem(str(call_id), {
                "author": g.user["username"], "type": data.get("type", ""), "text": data.get("text", ""),
            })
        except ApiError as exc:
            flash("Проблема не зафиксирована. " + exc.user_message, "danger")
            return redirect(url_for("fe.problems_new", call_id=call_id))
        flash("Проблема зафиксирована", "success")
        return redirect(url_for("fe.call_card", call_id=call_id))
    return render_template(
        "fe/problems_form.html",
        form_title="Проблемы на вызове #%s" % call_id,
        form_action=url_for("fe.problems_new", call_id=call_id),
        problem_types=PROBLEM_TYPES, call_id=call_id,
    )


@bp.route("/call/<int:call_id>/case/new", methods=["GET", "POST"])
@permission_required("cases.add")
def case_new(call_id):
    call, redirect_ = _require_my_call(call_id)
    if redirect_:
        return redirect_
    if request.method == "POST":
        data = request.form.to_dict()
        try:
            api.create_case(str(call_id), {
                "author": g.user["username"],
                "type": data.get("type", ""), "result": data.get("result", ""), "text": data.get("text", ""),
            })
        except ApiError as exc:
            flash("Случай не сохранён. " + exc.user_message, "danger")
            return redirect(url_for("fe.case_new", call_id=call_id))
        flash("Случай обслуживания сохранён", "success")
        return redirect(url_for("fe.call_card", call_id=call_id))
    return render_template(
        "fe/case_form.html",
        form_title="Случай обслуживания (вызов #%s)" % call_id,
        form_action=url_for("fe.case_new", call_id=call_id),
        case_types=CASE_TYPES, call_id=call_id,
    )


@bp.route("/call/<int:call_id>/diary/new", methods=["GET", "POST"])
@permission_required("diaries.add")
def diary_new(call_id):
    call, redirect_ = _require_my_call(call_id)
    if redirect_:
        return redirect_
    if request.method == "POST":
        data = request.form.to_dict()
        try:
            api.create_diary(str(call_id), {
                "author": g.user["full_name"],
                "type": data.get("type", ""), "text": data.get("text", ""),
            })
        except ApiError as exc:
            flash("Запись не сохранена. " + exc.user_message, "danger")
            return redirect(url_for("fe.diary_new", call_id=call_id))
        flash("Запись дневника сохранена", "success")
        return redirect(url_for("fe.call_card", call_id=call_id))
    return render_template(
        "fe/diary_form.html",
        form_title="Дневник (вызов #%s)" % call_id,
        form_action=url_for("fe.diary_new", call_id=call_id),
        diary_types=DIARY_TYPES, call_id=call_id,
    )


@bp.route("/call/<int:call_id>/info/<int:info_id>/mark_incorrect", methods=["POST"])
@permission_required("calls.manage")
def info_mark_incorrect(call_id, info_id):
    try:
        records = api.get_call_info(str(call_id))
    except ApiError as exc:
        flash("Запись не найдена. " + exc.user_message, "danger")
        return redirect(url_for("fe.call_card", call_id=call_id))
    rec = next((r for r in records if str(r["id"]) == str(info_id)), None)
    if not rec:
        flash("Запись не найдена", "danger")
        return redirect(url_for("fe.call_card", call_id=call_id))
    if rec.get("author") != g.user["username"]:
        abort(403, description="Отметить некорректной можно только свою запись.")
    try:
        api.mark_call_info_incorrect(str(call_id), info_id)
    except ApiError as exc:
        flash("Не удалось отметить запись. " + exc.user_message, "danger")
    else:
        flash("Запись отмечена как некорректная", "warning")
    return redirect(url_for("fe.call_card", call_id=call_id))


@bp.route("/call/<int:call_id>/problems/<int:problem_id>/mark_incorrect", methods=["POST"])
@permission_required("calls.manage")
def problem_mark_incorrect(call_id, problem_id):
    try:
        records = api.get_call_problems(str(call_id))
    except ApiError as exc:
        flash("Запись не найдена. " + exc.user_message, "danger")
        return redirect(url_for("fe.call_card", call_id=call_id))
    rec = next((r for r in records if str(r["id"]) == str(problem_id)), None)
    if not rec:
        flash("Запись не найдена", "danger")
        return redirect(url_for("fe.call_card", call_id=call_id))
    if rec.get("author") != g.user["username"]:
        abort(403, description="Отметить некорректной можно только свою запись.")
    try:
        api.mark_call_problem_incorrect(str(call_id), problem_id)
    except ApiError as exc:
        flash("Не удалось отметить проблему. " + exc.user_message, "danger")
    else:
        flash("Проблема отмечена как некорректная", "warning")
    return redirect(url_for("fe.call_card", call_id=call_id))


# ---------------------------------------------------------------------------
# Пациент и запись на приём
# ---------------------------------------------------------------------------
def _fe_patient(patient):
    return {
        "id": patient.get("id"),
        "name": patient.get("full_name"),
        "birth_date": patient.get("birth_date"),
        "sex": patient.get("gender"),
        "oms": patient.get("oms_policy"),
        "phone": patient.get("phone"),
        "allergies": patient.get("allergies") or "Не указаны",
    }


@bp.route("/patient/<int:patient_id>")
@permission_required("patients.view")
def patient_card(patient_id):
    try:
        patient = api.get_patient(str(patient_id))
    except NotFoundError:
        flash("Пациент #%s не найден" % patient_id, "danger")
        return render_template("fe/patient_card.html", patient=None, appointments=[])
    except ApiError as exc:
        flash("Не удалось загрузить пациента. " + exc.user_message, "danger")
        return render_template("fe/patient_card.html", patient=None, appointments=[])
    try:
        appointments = api.get_appointments(str(patient_id))
    except ApiError:
        flash("Не удалось загрузить записи на приём.", "warning")
        appointments = []
    fe_appointments = [
        {"date": a.get("date"), "time": a.get("time"), "doctor": a.get("specialty"), "note": a.get("comment")}
        for a in appointments
    ]
    return render_template(
        "fe/patient_card.html",
        patient=_fe_patient(patient),
        appointments=fe_appointments,
        call_id=request.args.get("call_id", type=int),
    )


@bp.route("/patient/<int:patient_id>/appointment/new", methods=["GET", "POST"])
@permission_required("appointments.add")
def appointment_new(patient_id):
    try:
        patient = api.get_patient(str(patient_id))
    except ApiError:
        flash("Пациент #%s не найден" % patient_id, "danger")
        return redirect(url_for("fe.calls_list"))

    now = datetime.now()
    if request.method == "POST":
        data = request.form.to_dict()
        date = (data.get("date") or "").strip()
        time = (data.get("time") or "").strip()
        doctor = (data.get("doctor") or "").strip()
        note = (data.get("note") or "").strip()

        try:
            appointment_datetime = datetime.strptime("%s %s" % (date, time), "%Y-%m-%d %H:%M")
        except ValueError:
            appointment_datetime = None

        error = None
        if appointment_datetime is None:
            error = "Укажите корректную дату и время приёма"
        elif appointment_datetime < now:
            error = "Нельзя записаться на прошедшую дату или время"
        elif not (
            datetime.strptime("08:00", "%H:%M").time()
            <= appointment_datetime.time()
            <= datetime.strptime("17:00", "%H:%M").time()
        ):
            error = "Запись доступна только с 08:00 до 17:00"
        elif not doctor:
            error = "Укажите врача или специальность"

        if error:
            session["appointment_form_data"] = {"date": date, "time": time, "doctor": doctor, "note": note}
            flash(error, "danger")
            return redirect(url_for("fe.appointment_new", patient_id=patient_id), code=303)

        try:
            api.create_appointment(str(patient_id), {
                "specialty": doctor, "date": date, "time": time, "comment": note,
                "created_by": g.user["username"],
            })
        except ApiError as exc:
            flash("Запись не сохранена. " + exc.user_message, "danger")
            return redirect(url_for("fe.appointment_new", patient_id=patient_id))
        flash("Запись на приём сохранена", "success")
        return redirect(url_for("fe.patient_card", patient_id=patient_id), code=303)

    form_data = session.pop("appointment_form_data", {})
    return render_template(
        "fe/appointment_form.html",
        form_title="Запись на приём (пациент #%s)" % patient_id,
        form_action=url_for("fe.appointment_new", patient_id=patient_id),
        patient=_fe_patient(patient),
        patient_id=patient_id,
        today=now.strftime("%Y-%m-%d"),
        default_time=now.strftime("%H:%M"),
        form_date=form_data.get("date", ""),
        form_time=form_data.get("time", ""),
        form_doctor=form_data.get("doctor", ""),
        form_note=form_data.get("note", ""),
    )


# ---------------------------------------------------------------------------
# Админ-панель (пользователи — из SQL-базы, вызовы — из API)
# ---------------------------------------------------------------------------
@bp.route("/admin")
@permission_required("users.manage")
def admin_panel():
    all_calls = _all_calls()
    conn = db.get_db()
    doctors = []
    for user in db.list_users(conn):
        active_call_id = next(
            (c["id"] for c in all_calls if c.get("active_owner") == user["username"]), None
        )
        doctors.append({
            "login": user["username"], "name": user["full_name"],
            "role": user["role_code"], "active_call_id": active_call_id,
        })
    stats = {
        "completed": sum(1 for c in all_calls if c.get("is_completed") and c.get("result") != "false"),
        "false": sum(1 for c in all_calls if c.get("is_completed") and c.get("result") == "false"),
        "in_progress": sum(1 for c in all_calls if c.get("active_owner")),
        "total": len(all_calls),
    }
    history = [enrich_call(c) for c in all_calls if c.get("is_completed")]
    return render_template("fe/admin.html", doctors=doctors, stats=stats, history=history)


@bp.route("/admin/reset/<login>", methods=["POST"])
@permission_required("users.manage")
def admin_reset(login):
    all_calls = _all_calls()
    owned = [c for c in all_calls if c.get("active_owner") == login]
    if not owned:
        flash("У %s нет активного вызова" % login, "info")
        return redirect(url_for("fe.admin_panel"))
    try:
        for c in owned:
            api.update_call(str(c["id"]), {"active_owner": None, "status_progress": None})
    except ApiError as exc:
        flash("Не удалось сбросить вызов. " + exc.user_message, "danger")
    else:
        flash("Активный вызов у %s сброшен" % login, "success")
    return redirect(url_for("fe.admin_panel"))


@bp.route("/admin/create_user", methods=["POST"])
@permission_required("users.manage")
def admin_create_user():
    login_ = (request.form.get("login") or "").strip().lower()
    password = request.form.get("password") or ""
    role = request.form.get("role") or "doctor"
    name = (request.form.get("name") or "").strip()

    if not login_ or not password or not name:
        flash("Заполните все поля", "danger")
        return redirect(url_for("fe.admin_panel"))
    # В БД фельдшеру соответствует роль paramedic.
    role_map = {"doctor": "paramedic", "admin": "admin"}
    if role not in role_map:
        abort(400, description="Недопустимая роль")
    try:
        conn = db.get_db()
        db.create_user(conn, login_, name, password, role_map[role])
    except ValueError as exc:
        # db.create_user сам превращает дубль логина, короткий пароль и
        # неизвестную роль в ValueError — ловим его, а не sqlite3.IntegrityError.
        flash(str(exc), "danger")
        return redirect(url_for("fe.admin_panel"))
    flash("Пользователь %s создан" % login_, "success")
    return redirect(url_for("fe.admin_panel"))


@bp.route("/admin/map/call/<int:call_id>")
@permission_required("users.manage")
def admin_map_call(call_id):
    call, err = _load_call_safe(call_id)
    if err:
        flash(*err)
        return redirect(url_for("fe.calls_list"))
    owner_login = call.get("active_owner")
    owner_name = None
    if owner_login:
        conn = db.get_db()
        user = db.get_user_by_username(conn, owner_login)
        owner_name = user["full_name"] if user else None
    return render_template(
        "fe/admin_map_call.html",
        call=enrich_call(call),
        owner_login=owner_login,
        owner_name=owner_name,
        # GPS-трекинга нет: машина показывается в точке подстанции.
        owner_lat=BASE_LAT,
        owner_lng=BASE_LNG,
    )


@bp.route("/map/route/<int:call_id>")
@permission_required("calls.view")
def map_route(call_id):
    call, err = _load_call_safe(call_id)
    if err:
        flash(*err)
        return redirect(url_for("fe.calls_list"))
    if fe_role() in ("admin",):
        return redirect(url_for("fe.admin_map_call", call_id=call_id))
    return render_template("fe/map_route.html", call=enrich_call(call))
