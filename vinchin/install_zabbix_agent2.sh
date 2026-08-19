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
REPO_BASE="https://raw.githubusercontent.com/squids911/Template-Vinchin-9-for-zabbix-7.4/main/vinchin"
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

# 13. Финальная проверка
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
echo "⚠️  Не забудьте в Zabbix:"
echo "   1. Импортировать шаблон vinchin/zbx_template_vinchin.xml"
echo "   2. Назначить шаблон хосту '${SYSTEM_HOSTNAME}'"
echo "   3. Заполнить макросы:"
echo "      {$VINCHIN.URL}      = https://<vinchin-server>:54445"
echo "      {$VINCHIN.USERNAME} = admin"
echo "      {$VINCHIN.PASSWORD} = secret  (тип: Secret text)"
echo ""