# Vinchin Backup & Recovery monitoring via Zabbix 7.4 (Agent 2)

A ready-to-use solution for monitoring **Vinchin Backup & Recovery v9** (Rocky Linux 9)
with **Zabbix 7.4** and **Zabbix Agent 2**.

---

## Repository contents

| File | Purpose |
|---|---|
| `install_zabbix_agent2.sh` | **Auto-installer** — Zabbix Agent 2 + monitoring scripts |
| `vinchin/vinchin_collect.py` | Collector script (Python 3, no pip dependencies) |
| `vinchin/zabbix_agent2.d/userparameter_vinchin.conf` | UserParameter keys for the agent |
| `vinchin/zbx_template_vinchin.xml` | Zabbix template (RU) |
| `vinchin/zbx_template_vinchin_en.xml` | Zabbix template (EN) |
| `vinchin/README.md` / `README.en.md` | Manuals |

---

## Quick start — automatic installation

Run this **directly on your Vinchin appliance** (Rocky Linux 9):

```bash
# Download
curl -fsSL -o install_zabbix_agent2.sh \
  https://raw.githubusercontent.com/squids911/Template-Vinchin-9-for-zabbix-7.4/main/install_zabbix_agent2.sh

# Execute
bash install_zabbix_agent2.sh
```

The script will automatically:

1. ✋ Ask for the **hostname** in Zabbix (custom or press Enter for default)
2. 📦 Add the Zabbix 7.4 repository and install `zabbix-agent2` with plugins
3. 📥 Download from this repo:
   - `vinchin_collect.py` → `/etc/zabbix/scripts/`
   - `userparameter_vinchin.conf` → `/etc/zabbix/zabbix_agent2.d/`
4. 🔧 Generate `/etc/zabbix/zabbix_agent2.conf`
5. 🔒 Configure SELinux contexts
6. 🔥 Open port `10050/tcp` in firewalld
7. ▶️ Start and enable the agent

### After installation

1. Import `zbx_template_vinchin_en.xml` into Zabbix (7.4+)
2. Assign the template `Vinchin Backup and Recovery by API` to your host
3. Set macros on the host level:

| Macro | Description | Example |
|---|---|---|
| `{$VINCHIN.URL}` | Vinchin API URL | `https://127.0.0.1:443` |
| `{$VINCHIN.USERNAME}` | Username | `admin` |
| `{$VINCHIN.PASSWORD}` | Password (Secret text type) | `your_password` |

> For passwords with special characters, use base64 encoding:
> ```
> b64:$(echo -n 'Pa$$w0rd!' | base64 -w0)
> ```

---

## Manual installation

If you only need the collector script without reinstalling the agent:

```bash
# Create directories
mkdir -p /etc/zabbix/scripts /etc/zabbix/zabbix_agent2.d

# Download script
curl -fsSL -o /etc/zabbix/scripts/vinchin_collect.py \
  https://raw.githubusercontent.com/squids911/Template-Vinchin-9-for-zabbix-7.4/main/vinchin/vinchin_collect.py
chmod 755 /etc/zabbix/scripts/vinchin_collect.py

# Download UserParameter configuration
curl -fsSL -o /etc/zabbix/zabbix_agent2.d/userparameter_vinchin.conf \
  https://raw.githubusercontent.com/squids911/Template-Vinchin-9-for-zabbix-7.4/main/vinchin/zabbix_agent2.d/userparameter_vinchin.conf

# Restart the agent
systemctl restart zabbix-agent2
```

---

## Testing

### Command line

```bash
/etc/zabbix/scripts/vinchin_collect.py \
  --url https://127.0.0.1:443 \
  --username admin \
  --password "your_password" \
  summary
```

### Via Zabbix

1. Go to **Monitoring → Latest data**
2. Find the host created during installation
3. Filter: `vinchin` — you should see:
   - `Vinchin: Summary JSON`
   - `Vinchin: Jobs JSON`
   - `Vinchin: Storages JSON`
   - `Vinchin: Nodes JSON`

---

## Monitored data

| Category | Items |
|---|---|
| **Summary** | Running/waiting/failed/abnormal jobs, storage status, uptime |
| **Jobs** | UUID, name, type, status, progress, schedule, last result |
| **Storages** | UUID, name, type, node, capacity (total/used/free), status |
| **Nodes** | UUID, name, IP, status, version, modules (offline count) |

---

## Requirements

- **Vinchin Backup & Recovery** 9.x (tested on 9.0.0.92348)
- **OS**: Rocky Linux 9 (appliance)
- **Zabbix** 7.0 / 7.4
- **Python** 3.9+ (stdlib only)
- **OpenSSL** 1.1+ / 3.x

---

## License

MIT