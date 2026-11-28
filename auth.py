"""Вход в систему, выход и проверка прав (роли → права из SQL-базы)."""
import logging
import sqlite3
from functools import wraps
from urllib.parse import urlparse

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

import db

log = logging.getLogger("smp.auth")
bp = Blueprint("auth", __name__)


@bp.before_app_request
def load_user():
    """Определяет текущего пользователя и его права для каждого запроса."""
    g.user = None
    g.perms = frozenset()
    if request.endpoint == "static":
        return
    uid = session.get("uid")
    if not uid:
        return
    try:
        conn = db.get_db()
        user = db.get_user(conn, uid)
        if user and user["is_active"]:
            g.user = user
            g.perms = frozenset(db.get_permissions(conn, user["role_id"]))
        else:
            session.pop("uid", None)  # пользователя отключили или удалили
    except sqlite3.Error:
        log.exception("Не удалось прочитать пользователя из базы")


def _safe_next(target):
    """Разрешаем возвращаться только на страницы этого же сайта."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return None
    parsed = urlparse(target)
    return None if parsed.scheme or parsed.netloc else target


def _current_path():
    return request.full_path.rstrip("?")


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("index"))
    next_url = _safe_next(request.values.get("next"))

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        conn = db.get_db()
        user = db.get_user_by_username(conn, username) if username else None

        if user and user["locked_until"] and user["locked_until"] > db.now_str():
            db.audit(conn, "login.blocked", username=username)
            flash("Слишком много неудачных попыток. Попробуйте позже.", "danger")
        else:
            ok = check_password_hash(user["password_hash"] if user else db.DUMMY_HASH, password)
            if user and user["is_active"] and ok:
                session.clear()  # новая сессия после входа
                session["uid"] = user["id"]
                session.permanent = True
                db.register_login_ok(conn, user["id"])
                db.audit(conn, "login.ok", user=user)
                return redirect(next_url or url_for("index"))
            if user and user["is_active"]:
                db.register_failed_login(conn, user["id"])
            db.audit(conn, "login.failed", username=username)
            flash("Неверный логин или пароль.", "danger")

    return render_template("fe/login.html", next_url=next_url or "")


@bp.route("/logout", methods=["POST"])
def logout():
    if g.user:
        db.audit(db.get_db(), "logout", user=g.user)
    session.clear()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("auth.login"))


def permission_required(code):
    """Доступ только пользователям, у чьей роли есть право `code`."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not g.user:
                return redirect(url_for("auth.login", next=_current_path()))
            if code not in g.perms:
                db.audit(
                    db.get_db(), "access.denied", user=g.user,
                    details="%s %s" % (code, request.path),
                )
                abort(403, description="Недостаточно прав для этого действия.")
            return view(*args, **kwargs)

        return wrapped

    return decorator
