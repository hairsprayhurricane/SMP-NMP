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
    body, err = _body_with_required("complaints", "diagnosis", "actions", "outcome")
    if err:
        return err
    item = {
        "id": _next_id("cases"),
        "call_id": call_id,
        "created_at": _now(),
        "complaints": body["complaints"],
        "diagnosis": body["diagnosis"],
        "actions": body["actions"],
        "outcome": body["outcome"],
    }
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
    }
    DATA["diaries"].append(item)
    return jsonify({"status": "ok", "id": item["id"]}), 201


@app.get("/api/patients/<patient_id>/appointments")
def appointments(patient_id):
    return jsonify(
        {"appointments": [a for a in DATA["appointments"] if a["patient_id"] == patient_id]}
    )


@app.post("/api/patients/<patient_id>/appointments")
def add_appointment(patient_id):
    if not _find("patients", patient_id):
        return _error("Пациент не найден", 404)
    body, err = _body_with_required("specialty", "date", "time")
    if err:
        return err
    item = {
        "id": _next_id("appointments"),
        "patient_id": patient_id,
        "specialty": body["specialty"],
        "date": body["date"],
        "time": body["time"],
        "comment": body.get("comment", ""),
    }
    DATA["appointments"].append(item)
    return jsonify({"status": "ok", "id": item["id"]}), 201


if __name__ == "__main__":
    port = int(os.getenv("MOCK_PORT", "5001"))
    app.run(host="127.0.0.1", port=port)
