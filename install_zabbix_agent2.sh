#!/bin/bash
set -euo pipefail

# ================================================================
# Установка Zabbix Agent 2 + мониторинг Vinchin Backup & Recovery
# Rocky Linux 9 + Vinchin API v9
# ================================================================

# ---- Настройки (переопределяются переменными окружения) ----
ZABBIX_SERVER="${ZABBIX_SERVER:-37.17.55.196}"
ZABBIX_SERVER_ACTIVE="${ZABBIX_SERVER_ACTIVE:-37.17.55.196:10051}"
HOST_METADATA="${HOST_METADATA:-Vinchin5611}"
DEBUG_LEVEL="${DEBUG_LEVEL:-2}"
REFRESH_CHECKS="${REFRESH_CHECKS:-60}"
# --- автообновление бинарника агента (раз в неделю) ---
UPDATE_DAY="${UPDATE_DAY:-Mon}"    # день недели: Mon..Sun
AUTO_UPDATE="${AUTO_UPDATE:-1}"    # 1 — включить, 0 — отключить
REPO_BASE="https://raw.githubusercontent.com/squids911/Template-Vinchin-9-for-zabbix-7.4/main"
# ----------------------------------------------------------------

# 1. Ручной ввод имени хоста
DEFAULT_HOSTNAME=$(hostname -f 2>/dev/null || hostname)
if [[ -z "$DEFAULT_HOSTNAME" || "$DEFAULT_HOSTNAME" == "localhost" || "$DEFAULT_HOSTNAME" == "localhost.localdomain" ]]; then
    DEFAULT_HOSTNAME=$(hostname -s)
fi
read -r -p "Введите имя хоста для Zabbix [${DEFAULT_HOSTNAME}]: " SYSTEM_HOSTNAME
SYSTEM_HOSTNAME="${SYSTEM_HOSTNAME:-$DEFAULT_HOSTNAME}"
echo "Имя хоста в Zabbix: $SYSTEM_HOSTNAME"

# 2. Удаляем старый репозиторий Zabbix
dnf remove -y zabbix-release 2>/dev/null || true

# 3. Добавляем репозиторий Zabbix 7.4
echo "Добавляем репозиторий Zabbix 7.4..."
rpm -Uvh https://repo.zabbix.com/zabbix/7.4/release/rocky/9/noarch/zabbix-release-7.4-1.el9.noarch.rpm

# 4. Очищаем кэш
dnf clean all

# 5. Устанавливаем пакеты
echo "Устанавливаем zabbix-agent2 и плагины..."
dnf install -y zabbix-agent2 zabbix-agent2-plugin-*

# 6. Директории
mkdir -p /var/log/zabbix
chown zabbix:zabbix /var/log/zabbix
mkdir -p /etc/zabbix/scripts
mkdir -p /etc/zabbix/zabbix_agent2.d

# 7. logrotate
cat > /etc/logrotate.d/zabbix-agent2 <<'EOF'
/var/log/zabbix/zabbix_agent2.log {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    create 0640 zabbix zabbix
}
EOF

# 8. Скачиваем скрипты мониторинга Vinchin из GitHub-репозитория
echo "Скачиваем скрипты из репозитория..."
curl -fsSL "${REPO_BASE}/vinchin_collect.py" -o /etc/zabbix/scripts/vinchin_collect.py
chmod 755 /etc/zabbix/scripts/vinchin_collect.py
chown zabbix:zabbix /etc/zabbix/scripts/vinchin_collect.py

curl -fsSL "${REPO_BASE}/zabbix_agent2.d/userparameter_vinchin.conf" \
    -o /etc/zabbix/zabbix_agent2.d/userparameter_vinchin.conf
chown zabbix:zabbix /etc/zabbix/zabbix_agent2.d/userparameter_vinchin.conf

echo "Скрипты установлены:"
echo "  /etc/zabbix/scripts/vinchin_collect.py"
echo "  /etc/zabbix/zabbix_agent2.d/userparameter_vinchin.conf"

# 9. Генерируем основной конфиг (Include подключает файлы из .d/)
echo "Генерируем /etc/zabbix/zabbix_agent2.conf..."
cat > /etc/zabbix/zabbix_agent2.conf <<EOF
Server=${ZABBIX_SERVER}
ServerActive=${ZABBIX_SERVER_ACTIVE}
Hostname=${SYSTEM_HOSTNAME}
LogFile=/var/log/zabbix/zabbix_agent2.log
LogFileSize=1
DebugLevel=${DEBUG_LEVEL}
Timeout=30
UnsafeUserParameters=1
AllowKey=system.run[*]
RefreshActiveChecks=${REFRESH_CHECKS}
HostMetadata=${HOST_METADATA}

# Подключаем дополнительные UserParameter из файлов .d/
Include=/etc/zabbix/zabbix_agent2.d/*.conf
EOF

# 10. SELinux
if command -v getenforce &>/dev/null && [[ $(getenforce) == "Enforcing" ]]; then
    echo "Настраиваем SELinux..."
    setsebool -P zabbix_run_sudo on 2>/dev/null || true
    if [[ -d /var/log/vinchin ]]; then
        semanage fcontext -a -t zabbix_log_t "/var/log/vinchin(/.*)?" 2>/dev/null || true
        restorecon -Rv /var/log/vinchin 2>/dev/null || true
    fi
    semanage fcontext -a -t zabbix_exec_t "/etc/zabbix/scripts(/.*)?" 2>/dev/null || true
    restorecon -Rv /etc/zabbix/scripts 2>/dev/null || true
fi

# 11. Firewall
if systemctl is-active --quiet firewalld; then
    echo "Открываем порт 10050/tcp в firewalld..."
    firewall-cmd --permanent --add-port=10050/tcp
    firewall-cmd --reload
fi

# 12. Запускаем агент
systemctl enable zabbix-agent2
systemctl restart zabbix-agent2

# 13. Еженедельное автообновление БИНАРНИКА zabbix-agent2
#     (обновляется только пакет агента; конфиги и коллектор не трогаются)
case "$UPDATE_DAY" in
    Mon|Tue|Wed|Thu|Fri|Sat|Sun) ;;
    *) echo "WARN: UPDATE_DAY='${UPDATE_DAY}' некорректен — использую Mon"; UPDATE_DAY=Mon ;;
esac

if [[ "${AUTO_UPDATE}" == "1" ]]; then
    echo "Настраиваем еженедельное автообновление zabbix-agent2 (день: ${UPDATE_DAY})..."

    cat > /usr/local/sbin/vinchin-agent-update.sh <<'UPDATE_EOF'
#!/bin/bash
# Еженедельное обновление ТОЛЬКО бинарника zabbix-agent2 (пакет dnf).
# Конфиги НЕ трогаются: /etc/zabbix/zabbix_agent2.conf,
# /etc/zabbix/zabbix_agent2.d/* и /etc/zabbix/scripts/* — в RPM они объявлены
# %config(noreplace), dnf не перезаписывает локальные правки.
# Запускается таймером vinchin-agent-update.timer.

set -uo pipefail

PKG="zabbix-agent2"
LOG="/var/log/vinchin-agent-update.log"

log() { echo "[$(date '+%F %T')] $*"; echo "[$(date '+%F %T')] $*" >>"$LOG"; }

log "=== update check started ==="

if ! rpm -q "$PKG" >/dev/null 2>&1; then
    log "ERROR: package $PKG is not installed"
    exit 1
fi

before=$(rpm -q --qf '%{VERSION}-%{RELEASE}' "$PKG")

if ! out=$(dnf update -y "$PKG" 2>&1); then
    log "WARN: dnf update exited with an error"
    echo "$out" >>"$LOG"
    log "=== update check finished (with error) ==="
    exit 1
fi
echo "$out" >>"$LOG"

after=$(rpm -q --qf '%{VERSION}-%{RELEASE}' "$PKG")
log "version: before=$before after=$after"

if [ "$before" != "$after" ]; then
    log "new version installed -> restarting zabbix-agent2 (configs untouched)"
    systemctl restart zabbix-agent2 || { log "ERROR: failed to restart zabbix-agent2"; exit 1; }
    log "restart OK"
else
    log "no new version, nothing to do"
fi

if systemctl --quiet is-active zabbix-agent2; then
    log "zabbix-agent2: active"
else
    log "WARN: zabbix-agent2 is NOT active"
fi

log "=== update check finished ==="
UPDATE_EOF
    chmod 700 /usr/local/sbin/vinchin-agent-update.sh

    cat > /etc/systemd/system/vinchin-agent-update.service <<'SERVICE_EOF'
[Unit]
Description=Weekly zabbix-agent2 binary update
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/vinchin-agent-update.sh
SERVICE_EOF

    cat > /etc/systemd/system/vinchin-agent-update.timer <<TIMER_EOF
[Unit]
Description=Run zabbix-agent2 update weekly

[Timer]
OnCalendar=${UPDATE_DAY} *-*-* 04:00:00
RandomizedDelaySec=2h
Persistent=true

[Install]
WantedBy=timers.target
TIMER_EOF

    cat > /etc/logrotate.d/vinchin-agent-update <<'LOGROTATE_EOF'
/var/log/vinchin-agent-update.log {
    monthly
    rotate 3
    missingok
    notifempty
    compress
}
LOGROTATE_EOF

    systemctl daemon-reload
    systemctl enable --now vinchin-agent-update.timer
else
    echo "Автообновление отключено (AUTO_UPDATE=${AUTO_UPDATE})."
fi

# 14. Финальная проверка
echo ""
echo "═══════════════════════════════════════════════════"
systemctl status zabbix-agent2 --no-pager -l
echo "═══════════════════════════════════════════════════"
echo ""
echo "✅ Zabbix Agent 2 установлен и настроен."
echo "   Имя хоста в Zabbix:   ${SYSTEM_HOSTNAME}"
echo "   Сервер:               ${ZABBIX_SERVER}"
echo "   Метаданные:           ${HOST_METADATA}"
echo "   Лог-файл:             /var/log/zabbix/zabbix_agent2.log"
echo ""
echo "📋 Файлы Vinchin API:"
echo "   /etc/zabbix/scripts/vinchin_collect.py"
echo "   /etc/zabbix/zabbix_agent2.d/userparameter_vinchin.conf"
echo ""
if [[ "${AUTO_UPDATE}" == "1" ]]; then
    echo "🔄 Автообновление бинарника агента (только пакет, раз в неделю — ${UPDATE_DAY}):"
    echo "   Таймер:   systemctl list-timers vinchin-agent-update.timer"
    echo "   Вручную:  systemctl start vinchin-agent-update.service"
    echo "   Журнал:   /var/log/vinchin-agent-update.log"
    echo "   Отключить: systemctl disable --now vinchin-agent-update.timer"
    echo ""
fi
echo "⚠️  Не забудьте в Zabbix:"
echo "   1. Импортировать шаблон vinchin/zbx_template_vinchin.xml"
echo "   2. Назначить шаблон хосту '${SYSTEM_HOSTNAME}'"
echo "   3. Заполнить макросы:"
echo "      {$VINCHIN.URL}      = https://<vinchin-server>:54445"
echo "      {$VINCHIN.USERNAME} = admin"
echo "      {$VINCHIN.PASSWORD} = secret  (тип: Secret text)"
echo ""
