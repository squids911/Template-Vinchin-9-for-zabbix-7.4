# Monitoring Vinchin Backup & Recovery 9 with Zabbix 7.4 (Agent 2)

A ready-made solution: the Zabbix agent polls the **Vinchin v9 REST API** (`/api/v1/*`)
and feeds Zabbix with data about the **system state, storages and backup jobs**.

Connection settings are **not stored in files** — they are set via **host macros** in Zabbix
(`{$VINCHIN.URL}`, `{$VINCHIN.USERNAME}`, `{$VINCHIN.PASSWORD}`) and substituted into item keys.

Works with Vinchin Backup & Recovery 9.x (tested on 9.0.0.92348, appliance OS — Rocky 9).

## Contents

| File | Purpose |
|---|---|
| `install_zabbix_agent2.sh` | Installer: agent + collector + keys + weekly agent auto-update |
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
- counters: running / waiting / failed / abnormal, jobs that failed in their last run, failures in the last 24 h;
- per job (LLD): current status, last run result, last run start time and duration;
- triggers: **one alert** per job (Failed/Abnormal or last run failed) + a warning if the job is stopped/paused.

## How it works

1. The agent (UserParameter `vinchin.*`) runs `vinchin_collect.py`, passing it the URL, username and password (from host macros, as key parameters).
2. The script logs in to Vinchin (`POST /api/v1/login`: RSA-encrypted username/password + AES request signature); the token is cached in `/var/tmp/vinchin_zabbix_token.json` (10 min) and the script re-logs in automatically when it expires.
3. The script returns JSON; Zabbix parses it with **dependent items** via JSONPath, and LLD automatically creates items and triggers for each job/storage/node.

## Installation

### 0. Quick install with one command (install_zabbix_agent2.sh)

```bash
# settings are overridden via environment variables
ZABBIX_SERVER=10.0.0.10 ZABBIX_SERVER_ACTIVE=10.0.0.10:10051 bash install_zabbix_agent2.sh
```

The script asks for the host name (defaults to `hostname`), adds the Zabbix 7.4 repository,
installs `zabbix-agent2` (+ plugins), downloads the collector and keys from the GitHub repository,
configures config/SELinux/firewalld and **enables the weekly agent binary auto-update**
(see below). Disable auto-update: `AUTO_UPDATE=0 bash install_zabbix_agent2.sh`.

If you don't use the installer, follow steps 1–5 manually.

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

- **High:** job Failed/Abnormal or its last run finished with an error (one alert per job); node offline; storage offline; storage usage ≥ 95%; authorization problem.
- **Average:** one or more jobs finished with an error in their last run (closes automatically once those jobs complete successfully again).
- **Warning:** job stopped/paused; storage usage ≥ 85%; a node has offline modules; no data for 5 minutes.

Thresholds are configurable via the `{$VINCHIN.STORAGE.USED.WARN}` / `{$VINCHIN.STORAGE.USED.HIGH}` macros.

## About trigger recovery

All triggers use **expression-based recovery** (the default mode): a problem closes automatically
as soon as the problem expression becomes false again. No separate recovery expression is needed:

- `authorization problem` — closes when authorization/license is active again (`auth=1`);
- `backup jobs failed` — closes when the affected jobs complete successfully again (the count of jobs that failed their last run drops to 0), instead of waiting for a 24-hour window to elapse;
- `no data collected` (`nodata()`) — closes as soon as data starts flowing again;
- prototype `Job {#JOB_NAME} failed` — closes when the job is healthy again (not Failed/Abnormal and its last run succeeded);
- prototype `Job {#JOB_NAME} is stopped or paused` — closes when the job is active again;
- storage/node prototypes — close when the storage/node is healthy again.

## Updating the template (re-import)

If the template was imported before, on re-import:
1. Enable **Delete missing** for **Trigger prototypes** — otherwise the old duplicate trigger `Job {#JOB_NAME} last run failed` will remain and keep producing a second alert.
2. The other rules can be left as is (Create new / Update existing).

## Weekly zabbix-agent2 auto-update

`install_zabbix_agent2.sh` sets up a systemd timer `vinchin-agent-update.timer` that runs **once a week** (default: Monday, 04:00, with a ±2 h random delay) and executes `/usr/local/sbin/vinchin-agent-update.sh`.

The script updates **only the agent binary** (`dnf update -y zabbix-agent2`) — **configs are not touched**: `/etc/zabbix/zabbix_agent2.conf`, `/etc/zabbix/zabbix_agent2.d/*` and the collector stay as they are (they are shipped as `%config(noreplace)` in the RPM, so local changes are not overwritten by dnf). The service is restarted **only if the version changed**. Log: `/var/log/vinchin-agent-update.log` (rotated via logrotate).

Management:

```bash
systemctl list-timers vinchin-agent-update.timer   # schedule and last run
systemctl start vinchin-agent-update.service       # run the update manually
systemctl disable --now vinchin-agent-update.timer # disable auto-update
```

- The weekday is configurable via the `UPDATE_DAY` variable (e.g. `UPDATE_DAY=Sun bash install_zabbix_agent2.sh`).
- The `vinchin_collect.py` collector is **not** affected by auto-update — deploy it from GitHub as needed.
- If a new agent version requires dependency updates, `dnf` updates those too (unavoidable and safe — a full `dnf upgrade` is not performed).

## Notes

- Vinchin uses a **self-signed HTTPS certificate** — the script uses TLS without certificate verification (just like the web UI itself).
- The Vinchin token lives for ~15 minutes of inactivity; the script re-logs in automatically (error codes 910086/910087).
- The API requires the `Accept: application/json` header and a browser `User-Agent` — the script handles this.
- If you have more than 500 jobs/storages, increase `limit` inside the `jobs`/`storages`/`nodes` commands in the script.
- The token cache (`/var/tmp/vinchin_zabbix_token.json`) stores only a temporary session token, never the password.
- It is recommended to create a dedicated observer user in Vinchin (global observer in v9) for monitoring.
