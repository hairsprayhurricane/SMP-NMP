"""Имитация API СМП/НМП для разработки и демонстрации.

Запуск:  python mock_api.py   (по умолчанию порт 5001)
Данные берутся из mock_data.json и живут в памяти: новые записи пропадают
при перезапуске, сам файл не меняется.
"""
import json
import os
from datetime import datetime

from flask import Flask, jsonify, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
app.json.ensure_ascii = False

with open(os.path.join(BASE_DIR, "mock_data.json"), encoding="utf-8") as f:
    DATA = json.load(f)

# Служебные поля состояния вызова (для интерфейса /fe: кто взял вызов, этап
# бригады, завершён/ложный). Реальное API должно возвращать их само.
for _c in DATA["calls"]:
    _c.setdefault("active_owner", None)
    _c.setdefault("status_progress", None)
    _c.setdefault("completed", False)
    _c.setdefault("result", None)

for _key in ("call_info", "problems"):
    DATA.setdefault(_key, [])


def _find(collection, item_id):
    for item in DATA[collection]:
        if str(item.get("id")) == str(item_id):
            return item
    return None


def _next_id(collection):
    ids = [int(i["id"]) for i in DATA[collection] if str(i.get("id", "")).isdigit()]
    return str(max(ids, default=0) + 1)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _error(message, code):
    return jsonify({"error": message}), code


def _body_with_required(*fields):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, _error("Ожидается JSON-объект", 400)
    missing = [f for f in fields if not str(body.get(f, "")).strip()]
    if missing:
        return None, _error("Не заполнены поля: " + ", ".join(missing), 400)
    return body, None


@app.get("/api/calls")
def calls():
    return jsonify({"calls": DATA["calls"]})


@app.get("/api/calls/<call_id>")
def call(call_id):
    item = _find("calls", call_id)
    return jsonify(item) if item else _error("Вызов не найден", 404)


# Обновление состояния вызова: взятие/освобождение, этап бригады, завершение.
@app.patch("/api/calls/<call_id>")
def patch_call(call_id):
    item = _find("calls", call_id)
    if not item:
        return _error("Вызов не найден", 404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Ожидается JSON-объект", 400)
    for key in ("active_owner", "status_progress", "completed", "result"):
        if key in body:
            item[key] = body[key]
    return jsonify(item)


@app.get("/api/patients/<patient_id>")
def patient(patient_id):
    item = _find("patients", patient_id)
    return jsonify(item) if item else _error("Пациент не найден", 404)


@app.get("/api/calls/<call_id>/cases")
def cases(call_id):
    return jsonify({"cases": [c for c in DATA["cases"] if c["call_id"] == call_id]})


@app.post("/api/calls/<call_id>/cases")
def add_case(call_id):
    if not _find("calls", call_id):
        return _error("Вызов не найден", 404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Ожидается JSON-объект", 400)
    # Два формата одного и того же: корневые формы отправляют
    # complaints/diagnosis/actions/outcome, формы /fe — type/result/text.
    has_full = all(str(body.get(f, "")).strip() for f in ("complaints", "diagnosis", "actions", "outcome"))
    has_fe = all(str(body.get(f, "")).strip() for f in ("type", "text"))
    if not (has_full or has_fe):
        return _error("Не заполнены обязательные поля случая", 400)
    item = {
        "id": _next_id("cases"),
        "call_id": call_id,
        "created_at": _now(),
        "author": body.get("author", ""),
    }
    for f in ("complaints", "diagnosis", "actions", "outcome", "type", "result", "text"):
        if f in body:
            item[f] = body[f]
    DATA["cases"].append(item)
    return jsonify({"status": "ok", "id": item["id"]}), 201


@app.get("/api/calls/<call_id>/diaries")
def diaries(call_id):
    return jsonify({"diaries": [d for d in DATA["diaries"] if d["call_id"] == call_id]})


@app.post("/api/calls/<call_id>/diaries")
def add_diary(call_id):
    if not _find("calls", call_id):
        return _error("Вызов не найден", 404)
    body, err = _body_with_required("author", "text")
    if err:
        return err
    item = {
        "id": _next_id("diaries"),
        "call_id": call_id,
        "created_at": _now(),
        "author": body["author"],
        "text": body["text"],
        "type": body.get("type", ""),
    }
    DATA["diaries"].append(item)
    return jsonify({"status": "ok", "id": item["id"]}), 201


# --- Записи «информация про пациента» и «проблемы на вызове" (интерфейс /fe) ---
@app.get("/api/calls/<call_id>/info")
def call_info(call_id):
    return jsonify({"items": [i for i in DATA["call_info"] if i["call_id"] == call_id]})


@app.post("/api/calls/<call_id>/info")
def add_call_info(call_id):
    if not _find("calls", call_id):
        return _error("Вызов не найден", 404)
    body, err = _body_with_required("type", "text")
    if err:
        return err
    item = {
        "id": _next_id("call_info"),
        "call_id": call_id,
        "author": body.get("author", ""),
        "type": body["type"],
        "text": body["text"],
        "time": _now(),
        "incorrect": False,
    }
    DATA["call_info"].append(item)
    return jsonify({"status": "ok", "id": item["id"]}), 201


@app.post("/api/calls/<call_id>/info/<info_id>/mark_incorrect")
def mark_info_incorrect(call_id, info_id):
    item = _find("call_info", info_id)
    if not item or item["call_id"] != call_id:
        return _error("Запись не найдена", 404)
    item["incorrect"] = True
    return jsonify({"status": "ok"})


@app.get("/api/calls/<call_id>/problems")
def call_problems(call_id):
    return jsonify({"items": [p for p in DATA["problems"] if p["call_id"] == call_id]})


@app.post("/api/calls/<call_id>/problems")
def add_call_problem(call_id):
    if not _find("calls", call_id):
        return _error("Вызов не найден", 404)
    body, err = _body_with_required("type", "text")
    if err:
        return err
    item = {
        "id": _next_id("problems"),
        "call_id": call_id,
        "author": body.get("author", ""),
        "type": body["type"],
        "text": body["text"],
        "time": _now(),
        "incorrect": False,
    }
    DATA["problems"].append(item)
    return jsonify({"status": "ok", "id": item["id"]}), 201


@app.post("/api/calls/<call_id>/problems/<problem_id>/mark_incorrect")
def mark_problem_incorrect(call_id, problem_id):
    item = _find("problems", problem_id)
    if not item or item["call_id"] != call_id:
        return _error("Запись не найдена", 404)
    item["incorrect"] = True
    return jsonify({"status": "ok"})


@app.get("/api/patients/<patient_id>/appointments")
def appointments(patient_id):
    return jsonify(
        {"appointments": [a for a in DATA["appointments"] if a["patient_id"] == patient_id]}
    )


@app.post("/api/patients/<patient_id>/appointments")
def add_appointment(patient_id):
    if not _find("patients", patient_id):
        return _error("Пациент не найден", 404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _error("Ожидается JSON-объект", 400)
    # Корневые формы пишут specialty/comment, формы /fe — doctor/note.
    if not (str(body.get("specialty", "")).strip() or str(body.get("doctor", "")).strip()):
        return _error("Не указан врач (specialty/doctor)", 400)
    for f in ("date", "time"):
        if not str(body.get(f, "")).strip():
            return _error("Не заполнены поля: " + f, 400)
    item = {
        "id": _next_id("appointments"),
        "patient_id": patient_id,
        "specialty": body.get("specialty", body.get("doctor", "")),
        "date": body["date"],
        "time": body["time"],
        "comment": body.get("comment", body.get("note", "")),
        "created_by": body.get("author", ""),
    }
    DATA["appointments"].append(item)
    return jsonify({"status": "ok", "id": item["id"]}), 201


if __name__ == "__main__":
    port = int(os.getenv("MOCK_PORT", "5001"))
    app.run(host="127.0.0.1", port=port)
