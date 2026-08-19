# -*- coding: utf-8 -*-
"""
Генератор шаблонов Zabbix для Vinchin Backup & Recovery v9.
Создаёт две языковые версии одного шаблона (имена элементов/триггеров — английские,
описания — на русском или английском). UUID одинаковы для обеих версий,
поэтому импорт одной версии поверх другой просто обновляет описания.

Запуск:  python3 gen_template.py
Результат: zbx_template_vinchin.xml (ru) и zbx_template_vinchin_en.xml (en)
"""
import hashlib
import xml.etree.ElementTree as ET

TPL = "Vinchin Backup and Recovery by API"

# Параметры подключения приходят из макросов хоста и подставляются в ключи master-элементов
ARGS = "{$VINCHIN.URL},{$VINCHIN.USERNAME},{$VINCHIN.PASSWORD}"


def k(base):
    """Полный ключ master-элемента: base[{$VINCHIN.URL},{$VINCHIN.USERNAME},{$VINCHIN.PASSWORD}]."""
    return base + "[" + ARGS + "]"

# ---------- тексты (описания) по языкам ----------
STRINGS = {
    "ru": {
        "template_desc":
            "Мониторинг Vinchin Backup & Recovery v9 (состояние системы, хранилищ и заданий) "
            "через REST API. Требуется Zabbix Agent 2 с ключами vinchin.* и скриптом "
            "/etc/zabbix/scripts/vinchin_collect.py.",
        "tr_auth": "Авторизация/лицензия Vinchin не активна.",
        "tr_failed24h": "За последние 24 часа были задания, завершившиеся с ошибкой.",
        "tr_nodata": "Данные не поступают 5 минут — проверьте агент, конфиг и доступность API.",
        "jp_failed": "Текущее состояние задания — Failed (4) или Abnormal (5).",
        "jp_last_failed": "Последний запуск задания завершился ошибкой.",
        "sp_offline": "Хранилище офлайн (не смонтировано/недоступно).",
        "sp_high": "Занято >= {$VINCHIN.STORAGE.USED.HIGH}% объёма хранилища.",
        "sp_warn": "Занято >= {$VINCHIN.STORAGE.USED.WARN}% объёма хранилища.",
        "np_offline": "Узел Vinchin недоступен.",
        "np_modules": "Часть сервисных модулей узла не в сети.",
    },
    "en": {
        "template_desc":
            "Monitors Vinchin Backup & Recovery v9 (system state, storages and jobs) via the REST API. "
            "Requires Zabbix Agent 2 with the vinchin.* keys and the "
            "/etc/zabbix/scripts/vinchin_collect.py script.",
        "tr_auth": "Vinchin authorization/license is not active.",
        "tr_failed24h": "Some jobs finished with an error in the last 24 hours.",
        "tr_nodata": "No data received for 5 minutes — check the agent, config and API availability.",
        "jp_failed": "The job is currently in the Failed (4) or Abnormal (5) state.",
        "jp_last_failed": "The last job run finished with an error.",
        "sp_offline": "The storage is offline (unmounted/unavailable).",
        "sp_high": "Storage usage is >= {$VINCHIN.STORAGE.USED.HIGH}% of capacity.",
        "sp_warn": "Storage usage is >= {$VINCHIN.STORAGE.USED.WARN}% of capacity.",
        "np_offline": "The Vinchin node is unreachable.",
        "np_modules": "Some service modules of the node are offline.",
    },
}


def U(seed):
    """Детерминированный UUIDv4 из seed (md5): стабилен между импортами.
    Формат: 32 hex-символа БЕЗ дефисов (как требует Zabbix validateUuid:
    32 символа, xdigit, версия=4 в символе 12, вариант в символе 16)."""
    h = list(hashlib.md5(seed.encode('utf-8')).hexdigest())  # 32 hex-символа
    h[12] = '4'                              # version = 4
    variant = (int(h[16], 16) & 0x3) | 0x8    # variant = 10xx (8,9,a,b)
    h[16] = format(variant, 'x')
    return ''.join(h)                         # 32 символа, без дефисов


def el(tag, text=None):
    e = ET.Element(tag)
    if text is not None:
        e.text = str(text)
    return e


def sub(parent, tag, text=None):
    e = el(tag, text)
    parent.append(e)
    return e


def preprocessing(path):
    p = el("preprocessing")
    step = sub(p, "step")
    sub(step, "type", "JSONPATH")
    params = sub(step, "parameters")
    sub(params, "parameter", path)
    sub(step, "error_handler", "DISCARD_VALUE")
    return p


def master_item(key):
    m = el("master_item")
    sub(m, "key", key)
    return m


def make_item(key, name, value_type, delay="1m", history="7d", trends="365d",
              units=None, valuemap=None, ppath=None, master=None):
    it = el("item")
    sub(it, "uuid", U("item:" + key))
    sub(it, "name", name)
    sub(it, "type", "DEPENDENT" if master else "ZABBIX_PASSIVE")
    sub(it, "key", key)
    sub(it, "delay", "0" if master else delay)
    sub(it, "history", history)
    sub(it, "trends", trends)
    sub(it, "value_type", value_type)
    if units:
        sub(it, "units", units)
    if valuemap:
        vm = sub(it, "valuemap")
        sub(vm, "name", valuemap)
    if ppath:
        it.append(preprocessing(ppath))
    if master:
        it.append(master_item(k(master)))
    return it


def make_trigger(uuid_seed, expression, name, priority, description):
    tr = el("trigger")
    sub(tr, "uuid", U(uuid_seed))
    sub(tr, "expression", expression)
    sub(tr, "name", name)
    sub(tr, "priority", priority)
    sub(tr, "description", description)
    return tr


def make_proto(key, name, vt, ppath, master, valuemap=None, units=None, history="30d", trends="0"):
    ip = el("item_prototype")
    sub(ip, "uuid", U("itemproto:" + key))
    sub(ip, "name", name)
    sub(ip, "type", "DEPENDENT")
    sub(ip, "key", key)
    sub(ip, "delay", "0")
    sub(ip, "history", history)
    sub(ip, "trends", trends)
    sub(ip, "value_type", vt)
    if units:
        sub(ip, "units", units)
    if valuemap:
        vm = sub(ip, "valuemap")
        sub(vm, "name", valuemap)
    ip.append(preprocessing(ppath))
    ip.append(master_item(k(master)))
    return ip


def make_trigger_proto(uuid_seed, expression, name, priority, description):
    tp = el("trigger_prototype")
    sub(tp, "uuid", U(uuid_seed))
    sub(tp, "expression", expression)
    sub(tp, "name", name)
    sub(tp, "priority", priority)
    sub(tp, "description", description)
    return tp


def make_value_map(name, mappings):
    vm = el("valuemap")
    sub(vm, "uuid", U("valuemap:" + name))
    sub(vm, "name", name)
    maps = sub(vm, "mappings")
    for value, newvalue in mappings:
        mp = sub(maps, "mapping")
        sub(mp, "value", value)
        sub(mp, "newvalue", newvalue)
    return vm


def build(lang):
    S = STRINGS[lang]

    root = el("zabbix_export")
    sub(root, "version", "7.0")

    # ---------- template groups ----------
    tgs = sub(root, "template_groups")
    tg = sub(tgs, "template_group")
    sub(tg, "uuid", U("tgroup:Templates/Applications"))
    sub(tg, "name", "Templates/Applications")

    # ---------- template ----------
    templates = sub(root, "templates")
    tpl = sub(templates, "template")
    sub(tpl, "uuid", U("template:" + TPL))
    sub(tpl, "template", TPL)
    sub(tpl, "name", TPL)
    sub(tpl, "description", S["template_desc"])

    grp = sub(tpl, "groups")
    g = sub(grp, "group")
    sub(g, "name", "Templates/Applications")

    items = sub(tpl, "items")

    # --- master (JSON) items: ключи содержат макросы хоста [URL,USER,PASSWORD] ---
    items.append(make_item(k("vinchin.summary"), "Vinchin: Summary JSON", "TEXT", "1m", "7d", "0"))
    items.append(make_item(k("vinchin.jobs"), "Vinchin: Jobs JSON", "TEXT", "5m", "7d", "0"))
    items.append(make_item(k("vinchin.storages"), "Vinchin: Storages JSON", "TEXT", "5m", "7d", "0"))
    items.append(make_item(k("vinchin.nodes"), "Vinchin: Nodes JSON", "TEXT", "5m", "7d", "0"))

    # --- dependent numeric items (master = vinchin.summary) ---
    sum_items = [
        ("vinchin.jobs.running",     "Vinchin: Jobs running",            "UNSIGNED", "$.running_num",             None, None),
        ("vinchin.jobs.waiting",     "Vinchin: Jobs waiting",            "UNSIGNED", "$.waiting_num",             None, None),
        ("vinchin.jobs.failed_total","Vinchin: Jobs failed (total)",     "UNSIGNED", "$.fail_num",                None, None),
        ("vinchin.jobs.abnormal",    "Vinchin: Jobs abnormal",           "UNSIGNED", "$.abnormal_num",            None, None),
        ("vinchin.jobs.failed_24h",  "Vinchin: Jobs failed (24h)",       "UNSIGNED", "$.failed_24h",              None, None),
        ("vinchin.tasks.current",    "Vinchin: Current tasks",           "UNSIGNED", "$.current_task_num",        None, None),
        ("vinchin.tasks.history",    "Vinchin: History tasks",           "UNSIGNED", "$.history_task_num",        None, None),
        ("vinchin.uptime_days",      "Vinchin: Uptime (days)",           "UNSIGNED", "$.uptime_days",             None, None),
        ("vinchin.storage.count",    "Vinchin: Storage count",           "UNSIGNED", "$.storage_num",             None, None),
        ("vinchin.storage.total",    "Vinchin: Storage total",           "UNSIGNED", "$.total_capacity_bytes",    "B", None),
        ("vinchin.storage.used",     "Vinchin: Storage used",            "UNSIGNED", "$.used_capacity_bytes",     "B", None),
        ("vinchin.storage.free",     "Vinchin: Storage free",            "UNSIGNED", "$.remaining_capacity_bytes","B", None),
        ("vinchin.storage.used_pct", "Vinchin: Storage used, %",         "FLOAT",    "$.used_pct",                "%", None),
        ("vinchin.auth",             "Vinchin: Authorization",           "UNSIGNED", "$.auth_status",             None, "Vinchin online"),
    ]
    for key, name, vt, ppath, units, valuemap in sum_items:
        items.append(make_item(key, name, vt, master="vinchin.summary",
                               units=units, valuemap=valuemap, ppath=ppath))

    # --- nested triggers inside their items ---
    def attach_trigger(item_elem, uuid_seed, expression, name, priority, description):
        trg = item_elem.find("triggers")
        if trg is None:
            trg = el("triggers")
            item_elem.append(trg)
        trg.append(make_trigger(uuid_seed, expression, name, priority, description))

    for it in items:
        if it.findtext("key") == "vinchin.auth":
            attach_trigger(it, "trigger:auth",
                "last(/" + TPL + "/vinchin.auth)=0",
                "Vinchin: authorization problem", "HIGH", S["tr_auth"])
        if it.findtext("key") == "vinchin.jobs.failed_24h":
            attach_trigger(it, "trigger:failed24h",
                "last(/" + TPL + "/vinchin.jobs.failed_24h)>0",
                "Vinchin: backup jobs failed in last 24h", "AVERAGE", S["tr_failed24h"])
        if it.findtext("key") == k("vinchin.summary"):
            attach_trigger(it, "trigger:nodata",
                "nodata(/" + TPL + "/" + k("vinchin.summary") + ",5m)=1",
                "Vinchin: no data collected", "WARNING", S["tr_nodata"])

    # ---------- discovery rules ----------
    drs = sub(tpl, "discovery_rules")

    def add_macro_paths(rule, pairs):
        lmp = sub(rule, "lld_macro_paths")
        for macro, path in pairs:
            p = sub(lmp, "lld_macro_path")
            sub(p, "lld_macro", macro)
            sub(p, "path", path)

    # --- jobs LLD ---
    dr = sub(drs, "discovery_rule")
    sub(dr, "uuid", U("lld:vinchin.jobs.discovery"))
    sub(dr, "name", "Vinchin jobs discovery")
    sub(dr, "type", "DEPENDENT")
    sub(dr, "key", "vinchin.jobs.discovery")
    sub(dr, "delay", "0")
    dr.append(preprocessing("$.rows"))
    dr.append(master_item(k("vinchin.jobs")))
    add_macro_paths(dr, [("{#JOB_UUID}", "$.job_uuid"), ("{#JOB_NAME}", "$.job_name")])
    ipr = sub(dr, "item_prototypes")
    ipr.append(make_proto("vinchin.job.status[{#JOB_UUID}]",
        "Job {#JOB_NAME}: Status", "UNSIGNED",
        '$.rows[?(@.job_uuid == "{#JOB_UUID}")].status.first()',
        "vinchin.jobs", valuemap="Vinchin job status"))
    ipr.append(make_proto("vinchin.job.last_result[{#JOB_UUID}]",
        "Job {#JOB_NAME}: Last result", "UNSIGNED",
        '$.rows[?(@.job_uuid == "{#JOB_UUID}")].last_result.first()',
        "vinchin.jobs", valuemap="Vinchin last result"))
    ipr.append(make_proto("vinchin.job.last_start[{#JOB_UUID}]",
        "Job {#JOB_NAME}: Last run start", "TEXT",
        '$.rows[?(@.job_uuid == "{#JOB_UUID}")].last_start_time.first()',
        "vinchin.jobs"))
    tpr = sub(dr, "trigger_prototypes")
    tpr.append(make_trigger_proto("trigproto:job failed",
        "last(/" + TPL + "/vinchin.job.status[{#JOB_UUID}])>=4",
        "Vinchin: Job {#JOB_NAME} failed", "HIGH", S["jp_failed"]))
    tpr.append(make_trigger_proto("trigproto:job last failed",
        "last(/" + TPL + "/vinchin.job.last_result[{#JOB_UUID}])=1",
        "Vinchin: Job {#JOB_NAME} last run failed", "HIGH", S["jp_last_failed"]))

    # --- storages LLD ---
    dr = sub(drs, "discovery_rule")
    sub(dr, "uuid", U("lld:vinchin.storages.discovery"))
    sub(dr, "name", "Vinchin storages discovery")
    sub(dr, "type", "DEPENDENT")
    sub(dr, "key", "vinchin.storages.discovery")
    sub(dr, "delay", "0")
    dr.append(preprocessing("$.rows"))
    dr.append(master_item(k("vinchin.storages")))
    add_macro_paths(dr, [("{#STORAGE_UUID}", "$.storage_uuid"), ("{#STORAGE_NAME}", "$.storage_name")])
    ipr = sub(dr, "item_prototypes")
    ipr.append(make_proto("vinchin.storage.status[{#STORAGE_UUID}]",
        "Storage {#STORAGE_NAME}: Status", "UNSIGNED",
        '$.rows[?(@.storage_uuid == "{#STORAGE_UUID}")].status.first()',
        "vinchin.storages", valuemap="Vinchin online"))
    ipr.append(make_proto("vinchin.storage.used_pct[{#STORAGE_UUID}]",
        "Storage {#STORAGE_NAME}: Used, %", "FLOAT",
        '$.rows[?(@.storage_uuid == "{#STORAGE_UUID}")].used_pct.first()',
        "vinchin.storages", units="%", trends="365d"))
    ipr.append(make_proto("vinchin.storage.total[{#STORAGE_UUID}]",
        "Storage {#STORAGE_NAME}: Total", "UNSIGNED",
        '$.rows[?(@.storage_uuid == "{#STORAGE_UUID}")].total_bytes.first()',
        "vinchin.storages", units="B", trends="365d"))
    ipr.append(make_proto("vinchin.storage.free[{#STORAGE_UUID}]",
        "Storage {#STORAGE_NAME}: Free", "UNSIGNED",
        '$.rows[?(@.storage_uuid == "{#STORAGE_UUID}")].free_bytes.first()',
        "vinchin.storages", units="B", trends="365d"))
    tpr = sub(dr, "trigger_prototypes")
    tpr.append(make_trigger_proto("trigproto:storage offline",
        "last(/" + TPL + "/vinchin.storage.status[{#STORAGE_UUID}])=0",
        "Vinchin: Storage {#STORAGE_NAME} offline", "DISASTER", S["sp_offline"]))
    tpr.append(make_trigger_proto("trigproto:storage high",
        "last(/" + TPL + "/vinchin.storage.used_pct[{#STORAGE_UUID}])>={$VINCHIN.STORAGE.USED.HIGH}",
        "Vinchin: Storage {#STORAGE_NAME} usage critically high", "HIGH", S["sp_high"]))
    tpr.append(make_trigger_proto("trigproto:storage warn",
        "last(/" + TPL + "/vinchin.storage.used_pct[{#STORAGE_UUID}])>={$VINCHIN.STORAGE.USED.WARN}",
        "Vinchin: Storage {#STORAGE_NAME} usage high", "WARNING", S["sp_warn"]))

    # --- nodes LLD ---
    dr = sub(drs, "discovery_rule")
    sub(dr, "uuid", U("lld:vinchin.nodes.discovery"))
    sub(dr, "name", "Vinchin nodes discovery")
    sub(dr, "type", "DEPENDENT")
    sub(dr, "key", "vinchin.nodes.discovery")
    sub(dr, "delay", "0")
    dr.append(preprocessing("$.rows"))
    dr.append(master_item(k("vinchin.nodes")))
    add_macro_paths(dr, [("{#NODE_UUID}", "$.node_uuid"), ("{#NODE_NAME}", "$.node_name"), ("{#NODE_IP}", "$.ip")])
    ipr = sub(dr, "item_prototypes")
    ipr.append(make_proto("vinchin.node.online[{#NODE_UUID}]",
        "Node {#NODE_NAME}: Online", "UNSIGNED",
        '$.rows[?(@.node_uuid == "{#NODE_UUID}")].online.first()',
        "vinchin.nodes", valuemap="Vinchin online"))
    ipr.append(make_proto("vinchin.node.modules_offline[{#NODE_UUID}]",
        "Node {#NODE_NAME}: Modules offline", "UNSIGNED",
        '$.rows[?(@.node_uuid == "{#NODE_UUID}")].modules_offline.first()',
        "vinchin.nodes"))
    ipr.append(make_proto("vinchin.node.version[{#NODE_UUID}]",
        "Node {#NODE_NAME}: Version", "TEXT",
        '$.rows[?(@.node_uuid == "{#NODE_UUID}")].version.first()',
        "vinchin.nodes"))
    tpr = sub(dr, "trigger_prototypes")
    tpr.append(make_trigger_proto("trigproto:node offline",
        "last(/" + TPL + "/vinchin.node.online[{#NODE_UUID}])=0",
        "Vinchin: Node {#NODE_NAME} offline", "HIGH", S["np_offline"]))
    tpr.append(make_trigger_proto("trigproto:node modules",
        "last(/" + TPL + "/vinchin.node.modules_offline[{#NODE_UUID}])>0",
        "Vinchin: Node {#NODE_NAME} has offline modules", "WARNING", S["np_modules"]))

    # ---------- macros ----------
    macros = sub(tpl, "macros")
    # параметры подключения — задаются на уровне хоста
    m = sub(macros, "macro")
    sub(m, "macro", "{$VINCHIN.URL}")
    sub(m, "value", "https://127.0.0.1:54445")
    m = sub(macros, "macro")
    sub(m, "macro", "{$VINCHIN.USERNAME}")
    sub(m, "value", "admin")
    m = sub(macros, "macro")
    sub(m, "macro", "{$VINCHIN.PASSWORD}")
    sub(m, "value", "")
    sub(m, "type", "SECRET_TEXT")
    # пороги использования хранилища
    m = sub(macros, "macro")
    sub(m, "macro", "{$VINCHIN.STORAGE.USED.WARN}")
    sub(m, "value", "85")
    m = sub(macros, "macro")
    sub(m, "macro", "{$VINCHIN.STORAGE.USED.HIGH}")
    sub(m, "value", "95")

    # ---------- value maps ----------
    vms = sub(tpl, "valuemaps")
    vms.append(make_value_map("Vinchin job status", [
        ("0", "Completed"), ("1", "Running"), ("2", "Pending"),
        ("3", "Stopped/Paused"), ("4", "Failed"), ("5", "Abnormal"), ("99", "Unknown"),
    ]))
    vms.append(make_value_map("Vinchin last result", [
        ("0", "Success"), ("1", "Failed"), ("2", "No data"),
    ]))
    vms.append(make_value_map("Vinchin online", [
        ("0", "Offline"), ("1", "Online"),
    ]))

    ET.indent(root, space="    ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    for lang, fname in [("ru", "zbx_template_vinchin.xml"),
                        ("en", "zbx_template_vinchin_en.xml")]:
        data = build(lang)
        path = os.path.join(here, fname)
        with open(path, "wb") as f:
            f.write(data)
        print("written", fname, len(data), "bytes")
