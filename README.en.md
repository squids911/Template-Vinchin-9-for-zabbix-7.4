# Monitoring Vinchin Backup & Recovery 9 with Zabbix 7.4 (Agent 2)

A ready-made solution: the Zabbix agent polls the **Vinchin v9 REST API** (`/api/v1/*`)
and feeds Zabbix with data about the **system state, storages and backup jobs**.

Connection settings are **not stored in files** — they are set via **host macros** in Zabbix
(`{$VINCHIN.URL}`, `{$VINCHIN.USERNAME}`, `{$VINCHIN.PASSWORD}`) and substituted into item keys.

Works with Vinchin Backup & Recovery 9.x (tested on 9.0.0.92348, appliance OS — Rocky 9).

## Contents

| File | Purpose |
|---|---|
| `vinchin_collect.py` | Collector script (Python 3 + openssl, **no pip dependencies**) |
| `zabbix_agent2.d/userparameter_vinchin.conf` | UserParameter keys for the agent |
| `zbx_template_vinchin.xml` | Zabbix template, Russian descriptions (import into 7.4) |
| `zbx_template_vinchin_en.xml` | Zabbix template, English descriptions (import into 7.4) |
| `README.md` / `README.en.md` | Instructions (RU / EN) |

> Both templates are the same template in two languages — identical structure and UUIDs,
> only the descriptions differ. Import one of them.

## What is monitored

**System state:**
- Vinchin nodes: online/offline, version, number of offline service modules;
- uptime, current/historical tasks, authorization/license status;
- *(optional)* OS CPU/RAM/disk — with the standard `Linux by Zabbix agent` template, if the agent runs on the Vinchin appliance itself.

**Storages:**
- each storage: status (online/offline), used % and bytes, total/free;
- triggers: offline, usage > 85% (warning), > 95% (high).

**Jobs (backups):**
- counters: running / waiting / failed / abnormal, failures in the last 24 h;
- per job (LLD): current status, last run result, last run start time and duration;
- triggers: job Failed/Abnormal, last run finished with an error.

## How it works

1. The agent (UserParameter `vinchin.*`) runs `vinchin_collect.py`, passing it the URL, username and password (from host macros, as key parameters).
2. The script logs in to Vinchin (`POST /api/v1/login`: RSA-encrypted username/password + AES request signature); the token is cached in `/var/tmp/vinchin_zabbix_token.json` (10 min) and the script re-logs in automatically when it expires.
3. The script returns JSON; Zabbix parses it with **dependent items** via JSONPath, and LLD automatically creates items and triggers for each job/storage/node.

## Installation

### 1. Install Zabbix Agent 2 on Vinchin (Rocky 9)

```bash
rpm -Uvh https://repo.zabbix.com/zabbix/7.4/release/rhel/9/noarch/zabbix-release-latest.el9.noarch.rpm
dnf install -y zabbix-agent2
```

*(If you cannot touch the appliance — install the agent on any Linux host that can reach Vinchin over HTTPS.)*

### 2. Deploy the files

```bash
mkdir -p /etc/zabbix/scripts /etc/zabbix/zabbix_agent2.d

# script
cp vinchin_collect.py /etc/zabbix/scripts/
chmod 755 /etc/zabbix/scripts/vinchin_collect.py

# agent keys
cp zabbix_agent2.d/userparameter_vinchin.conf /etc/zabbix/zabbix_agent2.d/
```

### 3. Configure the agent

In `/etc/zabbix/zabbix_agent2.conf`:

```
Server=<Zabbix_server_IP>
ServerActive=<Zabbix_server_IP>
Hostname=<unique_host_name>
Timeout=15
```

Restart it:

```bash
systemctl enable --now zabbix-agent2
```

### 4. Verify a key (for debugging)

```bash
zabbix_agent2 -t 'vinchin.summary[https://VINCHIN_IP:54445,admin,b64:<base64_password>]'
```

(In a production install the agent runs as the `zabbix` user; if you test `-t` as root on Debian/Ubuntu — run `sudo -u zabbix zabbix_agent2 -t ...`.)

### 5. On the Zabbix side

1. **Data collection → Templates → Import** → import `zbx_template_vinchin_en.xml` (or `zbx_template_vinchin.xml` for Russian descriptions).
2. **Data collection → Hosts → Create host**: host name = `Hostname` from the agent config, interface = Vinchin IP (port 10050).
3. Link the `Linux by Zabbix agent` template (for OS CPU/RAM/disk) if the agent runs on Vinchin.
4. Link the **“Vinchin Backup and Recovery by API”** template to the host.
5. **Set the host macros** (Host → Macros → Inherited and host macros):

   | Macro | Value |
   |---|---|
   | `{$VINCHIN.URL}` | `https://<Vinchin_IP_or_hostname>:54445` |
   | `{$VINCHIN.USERNAME}` | login, e.g. `admin` |
   | `{$VINCHIN.PASSWORD}` | `b64:<base64_password>` |

6. Data appears within 1–5 minutes; LLD creates items/triggers for jobs, storages and nodes.

## The `{$VINCHIN.PASSWORD}` macro and `b64:`

Zabbix does not allow some characters in item keys (`!`, `#`, `@`, etc.), so the password
is passed **base64-encoded** with a `b64:` prefix — the script decodes it back.

Encode the password:

```bash
echo -n 'YourPassword' | base64
```

and set the macro to `b64:<result>`, e.g. `b64:IVYzYjcjTHI=`. Do not add leading/trailing spaces.

- If the username also contains special characters (e.g. an e-mail), set it the same way: `b64:<base64>`.
- The `{$VINCHIN.PASSWORD}` macro is declared as **secret** (SECRET_TEXT) in the template — its value is hidden in the web UI and is not included in template exports.

## Key reference (UserParameter)

| Key | Returns |
|---|---|
| `vinchin.summary[url,user,pass]` | JSON summary (jobs, storage, uptime, authorization) |
| `vinchin.jobs[url,user,pass]` | JSON: current jobs + status/result of the last run |
| `vinchin.storages[url,user,pass]` | JSON: storages (status, total/free/used, %) |
| `vinchin.nodes[url,user,pass]` | JSON: nodes (online, version, offline modules) |

Discovery (`vinchin.discover.*`) is not needed: the discovery rules in the template are
**dependent** on the master items above and take data from their JSON.

## Script options (manual run / debugging)

```bash
python3 vinchin_collect.py summary --url https://host:54445 --username admin --password 'b64:IVYzYjcjTHI='
```

Commands: `summary` | `jobs` | `storages` | `nodes`.
Fallback alternatives: `--config /path.json` or the `VINCHIN_URL` / `VINCHIN_USERNAME` / `VINCHIN_PASSWORD` environment variables.

## Template triggers

- **High:** job Failed/Abnormal; last job run failed; node offline; storage offline; storage usage ≥ 95%; authorization problem.
- **Average:** a backup failed within the last 24 h.
- **Warning:** storage usage ≥ 85%; a node has offline modules; no data for 5 minutes.

Thresholds are configurable via the `{$VINCHIN.STORAGE.USED.WARN}` / `{$VINCHIN.STORAGE.USED.HIGH}` macros.

## Notes

- Vinchin uses a **self-signed HTTPS certificate** — the script uses TLS without certificate verification (just like the web UI itself).
- The Vinchin token lives for ~15 minutes of inactivity; the script re-logs in automatically (error codes 910086/910087).
- The API requires the `Accept: application/json` header and a browser `User-Agent` — the script handles this.
- If you have more than 500 jobs/storages, increase `limit` inside the `jobs`/`storages`/`nodes` commands in the script.
- The token cache (`/var/tmp/vinchin_zabbix_token.json`) stores only a temporary session token, never the password.
- It is recommended to create a dedicated observer user in Vinchin (global observer in v9) for monitoring.
