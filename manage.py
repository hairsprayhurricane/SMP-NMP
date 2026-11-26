#!/usr/bin/env python3
"""Управление пользователями из командной строки (веб-интерфейса для этого нет).

  python manage.py init-db
  python manage.py list-roles
  python manage.py list-users
  python manage.py create-user ivanov --role doctor --name "Иванов И. И."
  python manage.py set-password ivanov
  python manage.py set-role ivanov paramedic
  python manage.py deactivate ivanov        # запретить вход
  python manage.py activate ivanov

Пароль спрашивается в терминале. Параметр --password можно использовать в
скриптах, но пароль тогда останется в истории команд оболочки.
"""
import argparse
import getpass
import sys

import db


def _ask_password(args):
    if getattr(args, "password", None):
        return args.password
    first = getpass.getpass("Пароль: ")
    if first != getpass.getpass("Повторите пароль: "):
        sys.exit("Пароли не совпадают.")
    return first


def main():
    parser = argparse.ArgumentParser(description="Управление пользователями СМП/НМП")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="создать таблицы и начальные роли/права")
    sub.add_parser("list-roles", help="показать роли")
    sub.add_parser("list-users", help="показать пользователей")

    p = sub.add_parser("create-user", help="создать пользователя")
    p.add_argument("username")
    p.add_argument("--role", required=True, help="код роли (см. list-roles)")
    p.add_argument("--name", default="", help="ФИО для отображения")
    p.add_argument("--password", help="пароль (иначе будет запрошен)")

    p = sub.add_parser("set-password", help="сменить пароль")
    p.add_argument("username")
    p.add_argument("--password")

    p = sub.add_parser("set-role", help="сменить роль")
    p.add_argument("username")
    p.add_argument("role")

    for name in ("activate", "deactivate"):
        p = sub.add_parser(name, help="разрешить / запретить вход")
        p.add_argument("username")

    args = parser.parse_args()
    conn = db.connect()
    db.init_db(conn)

    try:
        if args.command == "init-db":
            print("База готова:", db.config.DB_PATH)
        elif args.command == "list-roles":
            for r in db.list_roles(conn):
                print("%-12s %s" % (r["code"], r["title"]))
        elif args.command == "list-users":
            for u in db.list_users(conn):
                print("%-16s %-12s %-8s %s" % (
                    u["username"], u["role_code"],
                    "активен" if u["is_active"] else "отключён", u["full_name"]))
        elif args.command == "create-user":
            db.create_user(conn, args.username, args.name, _ask_password(args), args.role)
            print("Пользователь создан:", args.username.strip().lower())
        elif args.command == "set-password":
            db.set_password(conn, args.username, _ask_password(args))
            print("Пароль изменён.")
        elif args.command == "set-role":
            db.set_role(conn, args.username, args.role)
            print("Роль изменена.")
        elif args.command in ("activate", "deactivate"):
            db.set_active(conn, args.username, args.command == "activate")
            print("Готово.")
    except ValueError as exc:
        sys.exit(str(exc))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
