#!/usr/bin/env python3
"""
vinchin_collect.py  —  Сбор данных из Vinchin Backup & Recovery API для Zabbix.

Использование (через UserParameter в zabbix_agent2.conf):
    vinchin_collect.py --url https://VINCHIN_SERVER --username admin --password secret summary
    vinchin_collect.py --url https://VINCHIN_SERVER --username admin --password secret jobs
    vinchin_collect.py --url https://VINCHIN_SERVER --username admin --password secret storages
    vinchin_collect.py --url https://VINCHIN_SERVER --username admin --password secret nodes

Возвращает JSON-строку, которую Zabbix преобразует в элементы данных
через Dependent item / JSONPath / Preprocessing.
"""

import argparse
import json
import sys
import urllib.request
import urllib.error
import urllib.parse
import ssl
from typing import Any, Dict, List, Optional

# -------------------------------------------------------------------
#  КОНФИГУРАЦИЯ
# -------------------------------------------------------------------
API_PREFIX = "/api"                     # Префикс путей API Vinchin
REQUEST_TIMEOUT = 30                    # Таймаут HTTP-запроса (сек)
VERIFY_SSL = False                      # Отключить проверку SSL-сертификата
                                        # (в production включите и укажите CA)

# -------------------------------------------------------------------
#  HELPER: HTTP-запросы
# -------------------------------------------------------------------

def build_ssl_context() -> ssl.SSLContext:
    """Создаёт SSL-контекст: с верификацией или без."""
    if VERIFY_SSL:
        return ssl.create_default_context()
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def api_request(
    base_url: str,
    method: str,
    path: str,
    token: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Универсальный HTTP-запрос к API Vinchin.
    Возвращает распарсенный JSON-ответ (dict).
    """
    url = base_url.rstrip("/") + path
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data).encode("utf-8") if data else None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    ctx = build_ssl_context()

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        sys.stderr.write(f"HTTP {e.code} {e.reason} — {error_body}\n")
        sys.exit(2)
    except urllib.error.URLError as e:
        sys.stderr.write(f"Ошибка соединения: {e.reason}\n")
        sys.exit(2)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"Ошибка парсинга JSON: {e}\n")
        sys.exit(2)


# -------------------------------------------------------------------
#  АУТЕНТИФИКАЦИЯ
# -------------------------------------------------------------------

def get_token(base_url: str, username: str, password: str) -> str:
    """
    Получает токен доступа от API Vinchin.
    Подставьте реальный endpoint логина (например /api/oauth/token).
    """
    payload = {
        "username": username,
        "password": password,
        # При необходимости — grant_type, client_id и т.п.
    }
    # ⚠️ ЗАМЕНИТЕ PATH НА РЕАЛЬНЫЙ ЭНДПОИНТ АУТЕНТИФИКАЦИИ VINCHIN
    resp = api_request(base_url, "POST", f"{API_PREFIX}/oauth/token", data=payload)
    # ⚠️ КЛЮЧ ТОКЕНА может отличаться — см. документацию Vinchin
    token = resp.get("access_token") or resp.get("token") or resp.get("data", {}).get("token")
    if not token:
        sys.stderr.write("Не удалось получить токен аутентификации\n")
        sys.exit(2)
    return token


# -------------------------------------------------------------------
#  МЕТОДЫ СБОРА ДАННЫХ
#  ⚠️  ЗАМЕНИТЕ ЭНДПОИНТЫ И ПУТИ ПОЛЕЙ В JSON
#      НА РЕАЛЬНЫЕ ИЗ ДОКУМЕНТАЦИИ VINCHIN API
# -------------------------------------------------------------------

def fetch_summary(base_url: str, token: str) -> Dict[str, Any]:
    """Общая сводка системы Vinchin."""
    # ⚠️ ЗАМЕНИТЕ PATH НА РЕАЛЬНЫЙ
    resp = api_request(base_url, "GET", f"{API_PREFIX}/dashboard/summary", token=token)
    # Извлекаем data (структура зависит от API)
    return resp.get("data", resp)


def fetch_jobs(base_url: str, token: str) -> List[Dict[str, Any]]:
    """Список задач (джобов) Vinchin."""
    resp = api_request(base_url, "GET", f"{API_PREFIX}/jobs", token=token)
    return resp.get("data", resp.get("items", resp if isinstance(resp, list) else []))


def fetch_storages(base_url: str, token: str) -> List[Dict[str, Any]]:
    """Список хранилищ Vinchin."""
    resp = api_request(base_url, "GET", f"{API_PREFIX}/storages", token=token)
    return resp.get("data", resp.get("items", resp if isinstance(resp, list) else [])  # noqa: F821 — опечатка специально правится ниже


def fetch_nodes(base_url: str, token: str) -> List[Dict[str, Any]]:
    """Список узлов (хостов/VMware/Hyper-V)."""
    resp = api_request(base_url, "GET", f"{API_PREFIX}/nodes", token=token)
    return resp.get("data", resp.get("items", resp if isinstance(resp, list) else []))


# -------------------------------------------------------------------
#  MAIN
# -------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Сбор данных Vinchin Backup & Recovery для Zabbix"
    )
    parser.add_argument("--url", required=True, help="URL Vinchin-сервера (https://...)")
    parser.add_argument("--username", required=True, help="Имя пользователя")
    parser.add_argument("--password", required=True, help="Пароль")
    parser.add_argument(
        "command",
        choices=["summary", "jobs", "storages", "nodes"],
        help="Команда: что собирать",
    )

    args = parser.parse_args()

    # Получаем токен
    token = get_token(args.url, args.username, args.password)

    # Выполняем команду
    if args.command == "summary":
        result = fetch_summary(args.url, token)
    elif args.command == "jobs":
        result = fetch_jobs(args.url, token)
    elif args.command == "storages":
        result = fetch_storages(args.url, token)
    elif args.command == "nodes":
        result = fetch_nodes(args.url, token)
    else:
        sys.stderr.write(f"Неизвестная команда: {args.command}\n")
        sys.exit(1)

    # Выводим JSON в stdout (Zabbix прочитает через Zabbix agent)
    # Для отладки можно выключить ensure_ascii
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()