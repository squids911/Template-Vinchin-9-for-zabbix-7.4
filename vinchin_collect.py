#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vinchin Backup & Recovery v9 -> Zabbix Agent 2 collector.

Получает данные из REST API Vinchin (/api/v1/*) и выдаёт их в формате,
пригодном для Zabbix (JSON для LLD, JSON для master-элементов, числа).

Работает без внешних Python-зависимостей: только stdlib + openssl.

Параметры подключения задаются макросами хоста в Zabbix и передаются скрипту
как аргументы командной строки (через UserParameter):

  vinchin_collect.py --url <url> --username <user> --password <pass> summary

Также поддерживаются (fallback, для отладки вне Zabbix):
  --config /path.json  (JSON с ключами url/username/password)
  env: VINCHIN_URL / VINCHIN_USERNAME / VINCHIN_PASSWORD

Команды:
  summary | jobs | storages | nodes
"""

import argparse
import base64
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

# ----------------------------------------------------------------------------
# Константы из фронтенда Vinchin v9
# ----------------------------------------------------------------------------
PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCq/O2gNw8H3RNTCfJlXYWTPX3J"
    "mTeKoPr6lCaHpEBgBg9FTt7Ftu+zYVaPtBLtPVYpxXzHdnjrkFThCuI30TZnh23R"
    "bU92Ap67IV6V0DqL3gQRPVsEgRCeH7Uwsvt5/YFZTgUT/V+hW5+Hq6fjMf8ghaAF"
    "Dro/vHElH2FAevLy0wIDAQAB\n"
    "-----END PUBLIC KEY-----"
)
AES_KEY = b"7ebec7acd38b0643c34b09c84ea54393"   # 32 байта -> AES-256
AES_IV = b"sNONwyJtvi2ch2in"                    # 16 байт
API_VERSION = "1.0-rev0"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) zabbix-agent"

DEFAULT_CONFIG = "/etc/zabbix/vinchin.json"
CACHE_FILE = "/var/tmp/vinchin_zabbix_token.json"
CACHE_MAX_AGE = 600          # сек: переиспользуем токен не дольше 10 минут
HTTP_TIMEOUT = 20

# ----------------------------------------------------------------------------
# Криптография через openssl (RSA PKCS#1 v1.5 и AES-256-CBC PKCS7)
# ----------------------------------------------------------------------------
def rsa_encrypt(plain: str) -> str:
    """JSEncrypt-совместимое RSA-шифрование строки (base64 на выходе)."""
    pem = os.environ.get("VINCHIN_PUBKEY_FILE")
    pub = PUBLIC_KEY
    if pem and os.path.exists(pem):
        pub = open(pem).read()
    # openssl pkeyutl требует файл с ключом
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(pub)
        keyfile = f.name
    try:
        p = subprocess.run(
            ["openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", keyfile,
             "-pkeyopt", "rsa_padding_mode:pkcs1"],
            input=plain.encode(), capture_output=True)
        if p.returncode != 0:
            raise RuntimeError("openssl rsa failed: %s" % p.stderr.decode())
        return base64.b64encode(p.stdout).decode("ascii")
    finally:
        os.unlink(keyfile)


def aes_sign(plain: str) -> str:
    """AES-256-CBC/PKCS7(hex) — то же, что signEncrypt() во фронтенде."""
    p = subprocess.run(
        ["openssl", "enc", "-aes-256-cbc",
         "-K", AES_KEY.hex(), "-iv", AES_IV.hex(), "-nosalt"],
        input=plain.encode(), capture_output=True)
    if p.returncode != 0:
        raise RuntimeError("openssl aes failed: %s" % p.stderr.decode())
    return p.stdout.hex()


def _deep_clone(obj):
    """Повторяет deepCloneObjects() фронтенда: строки-числа -> int, null -> ''."""
    if isinstance(obj, dict):
        return {k: _deep_clone(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_clone(v) for v in obj]
    if obj is None:
        return ""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, str):
        s = obj.strip()
        if s == "":
            return obj
        try:
            if str(int(s)) == s:
                return int(s)
        except ValueError:
            pass
        return obj
    return obj


def make_sign(params: dict, timestamp: int) -> str:
    a = _deep_clone(dict(params))
    a.pop("sign", None)          # защита от повторного использования
    a["timestamp"] = timestamp
    ordered = {k: a[k] for k in sorted(a.keys())}
    return aes_sign(json.dumps(ordered, separators=(",", ":"), ensure_ascii=False))

# ----------------------------------------------------------------------------
# HTTP-клиент (stdlib)
# ----------------------------------------------------------------------------
_CTX = ssl._create_unverified_context()


def _extract_cookie(headers):
    """Достаёт значение BackupSystem из заголовков Set-Cookie ответа."""
    for hdr in headers.get_all("Set-Cookie") or []:
        for part in hdr.split(";"):
            if part.strip().startswith("BackupSystem="):
                return part.strip().split("=", 1)[1]
    return None


def http_json(method, url, headers, params=None, body=None, session=None):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in headers.items():
        req.add_header(k, v)
    resp = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_CTX)
    raw = resp.read().decode("utf-8", "replace")
    new_token = resp.headers.get("__token__")
    new_cookie = _extract_cookie(resp.headers)
    if session is not None and new_cookie:
        session.cookie = new_cookie
    try:
        return json.loads(raw), new_token
    except ValueError:
        return {"_raw": raw}, new_token


class VinchinClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.access_token = ""
        self.csrf_token = ""
        self.cookie = ""
        self._load_cache()
        if not self._session_ok():
            self.login()

    # --- кэш токена (между запусками Zabbix) ---
    def _load_cache(self):
        try:
            with open(CACHE_FILE) as f:
                c = json.load(f)
            if time.time() - float(c.get("ts", 0)) < CACHE_MAX_AGE:
                if c.get("url") == self.base_url:
                    self.access_token = c.get("access_token", "")
                    self.csrf_token = c.get("csrf_token", "")
                    self.cookie = c.get("cookie", "")
        except Exception:
            pass

    def _save_cache(self):
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            import tempfile
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CACHE_FILE))
            with os.fdopen(fd, "w") as f:
                json.dump({
                    "url": self.base_url,
                    "access_token": self.access_token,
                    "csrf_token": self.csrf_token,
                    "cookie": self.cookie,
                    "ts": time.time(),
                }, f)
            os.replace(tmp, CACHE_FILE)   # атомарная замена
        except Exception:
            pass

    def _base_headers(self, with_auth=True):
        h = {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "x-api-version": API_VERSION,
        }
        if with_auth:
            h["Authorization"] = self.access_token
            h["X-Csrf-Token"] = self.csrf_token
        if self.cookie:
            h["Cookie"] = "BackupSystem=" + self.cookie
        return h

    def login(self):
        # 0) сбрасываем старую сессию, чтобы получить свежую анонимную
        self.cookie = ""
        self.access_token = ""
        self.csrf_token = ""
        # 1) анонимная сессия -> cookie BackupSystem
        req = urllib.request.Request(self.base_url + "/login.php", method="GET")
        for k, v in self._base_headers(with_auth=False).items():
            req.add_header(k, v)
        resp = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_CTX)
        ck = _extract_cookie(resp.headers)
        if ck:
            self.cookie = ck
        resp.read()

        # 2) логин (ответ может сменить cookie сессии!)
        params = {
            "username": rsa_encrypt(self.username),
            "password": rsa_encrypt(self.password),
            "very_code": "",
            "remember": False,
            "loginFlag": False,
        }
        ts = int(time.time() * 1000)
        params["timestamp"] = ts
        params["sign"] = make_sign(params, ts)
        data, new_token = http_json(
            "POST", self.base_url + "/api/v1/login",
            self._base_headers(with_auth=False), body=params, session=self)
        if new_token:
            self.csrf_token = new_token
        if data.get("message") == 1 and data.get("data", {}).get("result") == 1:
            self.access_token = data["data"].get("access_token", "")
            self._save_cache()
            return True
        # повтор с полными учётными данными при 910086 (relogin)
        raise RuntimeError("Vinchin login failed: %s" %
                           json.dumps(data, ensure_ascii=False)[:400])

    def _session_ok(self):
        return bool(self.access_token and self.csrf_token)

    def api(self, method, path, params=None):
        """Вызов API; при протухшей сессии — автоматический re-login."""
        params = dict(params or {})
        ts = int(time.time() * 1000)
        params["timestamp"] = ts
        params["sign"] = make_sign(params, ts)
        try:
            data, new_token = http_json(
                method, self.base_url + path,
                self._base_headers(with_auth=True), params=params, session=self)
        except urllib.error.HTTPError as e:
            raise RuntimeError("HTTP %s on %s" % (e.code, path))
        if new_token:
            self.csrf_token = new_token
            self._save_cache()
        code = data.get("code")
        # 910086 / 910087 = сессия истекла -> один раз перелогиниться
        if isinstance(data, dict) and code in (910086, 910087) and \
                data.get("success") is False:
            self.login()
            ts = int(time.time() * 1000)
            params["timestamp"] = ts
            params["sign"] = make_sign(params, ts)
            data, new_token = http_json(
                method, self.base_url + path,
                self._base_headers(with_auth=True), params=params, session=self)
            if new_token:
                self.csrf_token = new_token
                self._save_cache()
        return data

    def get(self, path, params=None):
        d = self.api("GET", path, params)
        if isinstance(d, dict) and d.get("success"):
            return d.get("data", {})
        raise RuntimeError("API %s: %s" % (path,
                           json.dumps(d, ensure_ascii=False)[:300]))

# ----------------------------------------------------------------------------
# Бизнес-логика: маппинг статусов
# ----------------------------------------------------------------------------
def status_num(text):
    t = (text or "").strip().lower()
    if t in ("completed", "successed", "finished", "success"):
        return 0
    if t in ("failed", "error"):
        return 4
    if t == "running":
        return 1
    if t in ("pending", "queued", "waiting", "preparing", "creating", "starting"):
        return 2
    if t in ("paused", "stopped", "suspended", "stopping", "pausing"):
        return 3
    if t in ("abnormal", "network_fault"):
        return 5
    return 99


def last_result(text):
    t = (text or "").strip().lower()
    if t in ("completed", "successed", "finished", "success"):
        return 0
    if t in ("failed", "error", "abnormal"):
        return 1
    return 2


def _parse_days(s):
    if not s:
        return 0
    import re
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    try:
        return int(float(m.group(1))) if m else 0
    except ValueError:
        return 0

# ----------------------------------------------------------------------------
# Команды
# ----------------------------------------------------------------------------
def cmd_summary(c: VinchinClient):
    j = c.get("/api/v1/homepage/job_status_view")
    s = c.get("/api/v1/homepage/storage_info")
    d = c.get("/api/v1/homepage/datacenter_view")
    auth = c.get("/api/v1/homepage/auth_status")
    total = (s.get("total_capacity") or {}).get("size", 0)
    used = (s.get("used_capacity") or {}).get("size", 0)
    free = (s.get("remaining_capacity") or {}).get("size", 0)
    used_pct = round(used * 100.0 / total, 2) if total else 0
    # неудачные задания: за 24 ч и по последнему запуску
    failed_24h = 0
    jobs_failed_last = 0
    try:
        h = c.get("/api/v1/jobs/history", {"limit": 1000, "offset": 0})
        cutoff = time.time() - 86400
        for r in h.get("rows", []):
            st = r.get("start_time", "")
            try:
                tt = time.mktime(time.strptime(st, "%Y-%m-%d %H:%M:%S"))
            except Exception:
                tt = 0
            if tt and tt >= cutoff and (r.get("job_status") or "").strip().lower() in \
                    ("failed", "error", "abnormal"):
                failed_24h += 1
        # история идёт от новых к старым -> первый попавшийся = последний запуск задания
        hist = {}
        for r in h.get("rows", []):
            nm = r.get("job_name")
            if nm and nm not in hist:
                hist[nm] = r
        jobs = c.get("/api/v1/jobs", {"limit": 500, "offset": 0})
        for r in jobs.get("rows", []):
            last = hist.get(r.get("job_name")) or {}
            if (last.get("job_status") or "").strip().lower() in ("failed", "error", "abnormal"):
                jobs_failed_last += 1
    except Exception:
        pass
    out = {
        "running_num": j.get("running_num", 0),
        "waiting_num": j.get("waiting_num", 0),
        "stop_num": j.get("stop_num", 0),
        "abnormal_num": j.get("abnormal_num", 0),
        "fail_num": j.get("fail_num", 0),
        "failed_24h": failed_24h,
        "jobs_failed_last": jobs_failed_last,
        "storage_num": s.get("storage_num", 0),
        "total_capacity_bytes": total,
        "used_capacity_bytes": used,
        "remaining_capacity_bytes": free,
        "used_pct": used_pct,
        "auth_status": 1 if auth == 1 else 0,
        "current_task_num": d.get("current_task_num", 0),
        "history_task_num": d.get("history_task_num", 0),
        "uptime_days": _parse_days((d.get("system_running_time_info") or {}).get("running_day")),
        "uptime": (d.get("system_running_time_info") or {}).get("running_time", ""),
    }
    print(json.dumps(out, ensure_ascii=False))


def cmd_jobs(c: VinchinClient):
    data = c.get("/api/v1/jobs", {"limit": 500, "offset": 0})
    hist = {}
    try:
        h = c.get("/api/v1/jobs/history", {"limit": 1000, "offset": 0})
        for r in h.get("rows", []):
            nm = r.get("job_name")
            if nm and nm not in hist:
                hist[nm] = r      # в выдаче история отсортирована от новых к старым
    except Exception:
        pass
    rows = []
    for r in data.get("rows", []):
        name = r.get("job_name", "")
        last = hist.get(name) or {}
        rows.append({
            "job_uuid": r.get("job_uuid"),
            "job_name": name,
            "module_type": r.get("module_type"),
            "job_type": (r.get("job_type") or "").strip(),
            "status": status_num(r.get("job_status")),
            "status_text": r.get("job_status"),
            "progress": r.get("progress"),
            "next_time": r.get("next_time"),
            "last_result": last_result(last.get("job_status")),
            "last_status_text": last.get("job_status"),
            "last_start_time": last.get("start_time"),
            "last_finish_time": last.get("finish_time"),
            "last_duration": last.get("execution_duration"),
        })
    print(json.dumps({"total": data.get("total", 0), "rows": rows}, ensure_ascii=False))


def cmd_storages(c: VinchinClient):
    data = c.get("/api/v1/storages", {"limit": 500, "offset": 0})
    rows = []
    for r in data.get("rows", []):
        total = r.get("total_size_value") or 0
        free = r.get("free_size_value") or 0
        used = max(total - free, 0)
        rows.append({
            "storage_uuid": r.get("storage_uuid"),
            "storage_name": r.get("storage_nickname"),
            "storage_type": r.get("storage_type"),
            "node": r.get("node"),
            "status": 1 if r.get("status") else 0,
            "mount_flag": 1 if r.get("mount_flag") else 0,
            "desc": r.get("desc"),
            "total_bytes": total,
            "free_bytes": free,
            "used_bytes": used,
            "used_pct": round(used * 100.0 / total, 2) if total else 0,
            "warning": 1 if (r.get("warning") or {}).get("flag") else 0,
            "use_mode": r.get("use_mode"),
        })
    print(json.dumps({"total": data.get("total", 0), "rows": rows}, ensure_ascii=False))


def cmd_nodes(c: VinchinClient):
    data = c.get("/api/v1/nodes", {"limit": 500, "offset": 0})
    rows = []
    for r in data.get("rows", []):
        mods = r.get("module_info") or []
        offline = sum(1 for m in mods if not m.get("online_flag"))
        rows.append({
            "node_uuid": r.get("node_uuid"),
            "node_name": r.get("host_name") or r.get("node_nickname"),
            "ip": r.get("ip"),
            "status": r.get("status"),
            "online": 1 if r.get("online_flag") else 0,
            "version": r.get("version"),
            "modules_total": len(mods),
            "modules_offline": offline,
            "offline_modules": r.get("offline_module_des") or "",
        })
    print(json.dumps({"total": data.get("total", 0), "rows": rows}, ensure_ascii=False))


def _lld(rows, extra):
    out = []
    for r in rows:
        item = {}
        for macro, src in extra.items():
            item[macro] = str(r.get(src) or "")
        out.append(item)
    print(json.dumps({"data": out}, ensure_ascii=False))


def cmd_discover(c: VinchinClient, what):
    if what == "jobs":
        data = c.get("/api/v1/jobs", {"limit": 500, "offset": 0})
        _lld(data.get("rows", []), {"{#JOB_UUID}": "job_uuid", "{#JOB_NAME}": "job_name"})
    elif what == "storages":
        data = c.get("/api/v1/storages", {"limit": 500, "offset": 0})
        _lld(data.get("rows", []), {"{#STORAGE_UUID}": "storage_uuid", "{#STORAGE_NAME}": "storage_nickname"})
    elif what == "nodes":
        data = c.get("/api/v1/nodes", {"limit": 500, "offset": 0})
        _lld(data.get("rows", []), {"{#NODE_UUID}": "node_uuid", "{#NODE_NAME}": "host_name",
                                    "{#NODE_IP}": "ip"})
    else:
        raise SystemExit("unknown discovery target: %s" % what)

# ----------------------------------------------------------------------------
def _maybe_b64(v):
    """Если значение имеет префикс 'b64:', декодировать остаток из base64.

    Позволяет задавать в макросах Zabbix пароли/логины с символами,
    запрещёнными в item key (! # @ и т.п.): макрос = 'b64:' + base64(значение).
    Поддерживает стандартный и url-safe алфавит, с padding и без."""
    if isinstance(v, str) and v.startswith("b64:"):
        s = v[4:]
        s = s.replace("-", "+").replace("_", "/")
        s += "=" * (-len(s) % 4)
        return base64.b64decode(s).decode("utf-8")
    return v


def load_config(args):
    cfg = {"url": None, "username": None, "password": None}
    path = args.config or os.environ.get("VINCHIN_CONF") or DEFAULT_CONFIG
    if os.path.exists(path):
        with open(path) as f:
            cfg.update(json.load(f))
    if args.url:
        cfg["url"] = args.url
    if args.username:
        cfg["username"] = args.username
    if args.password:
        cfg["password"] = args.password
    cfg["url"] = cfg["url"] or os.environ.get("VINCHIN_URL")
    cfg["username"] = cfg["username"] or os.environ.get("VINCHIN_USERNAME")
    cfg["password"] = cfg["password"] or os.environ.get("VINCHIN_PASSWORD")
    # b64:-декодирование (для значений с запрещёнными в ключе символами)
    cfg["url"] = _maybe_b64(cfg["url"])
    cfg["username"] = _maybe_b64(cfg["username"])
    cfg["password"] = _maybe_b64(cfg["password"])
    if not cfg["url"] or not cfg["username"] or not cfg["password"]:
        raise SystemExit(
            "Vinchin: url/username/password не заданы. Передайте их через макросы хоста "
            "Zabbix {$VINCHIN.URL} / {$VINCHIN.USERNAME} / {$VINCHIN.PASSWORD} (аргументы "
            "--url/--username/--password), либо через --config/переменные окружения.")
    return cfg


def main():
    ap = argparse.ArgumentParser(description="Vinchin -> Zabbix collector")
    ap.add_argument("command", help="summary|jobs|storages|nodes|discover.jobs|discover.storages|discover.nodes")
    ap.add_argument("--config", help="путь к JSON-конфигу")
    ap.add_argument("--url", help="https://host:54445")
    ap.add_argument("--username", help="логин")
    ap.add_argument("--password", help="пароль")
    args = ap.parse_args()

    cfg = load_config(args)
    c = VinchinClient(cfg["url"], cfg["username"], cfg["password"])
    cmd = args.command
    if cmd == "summary":
        cmd_summary(c)
    elif cmd == "jobs":
        cmd_jobs(c)
    elif cmd == "storages":
        cmd_storages(c)
    elif cmd == "nodes":
        cmd_nodes(c)
    elif cmd == "discover.jobs":
        cmd_discover(c, "jobs")
    elif cmd == "discover.storages":
        cmd_discover(c, "storages")
    elif cmd == "discover.nodes":
        cmd_discover(c, "nodes")
    else:
        raise SystemExit("unknown command: %s" % cmd)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        sys.stderr.write("VINCHIN_COLLECT_ERROR: %s\n" % e)
        sys.exit(1)
