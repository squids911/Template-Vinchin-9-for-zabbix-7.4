# Мониторинг Vinchin Backup & Recovery через Zabbix 7.4 (Agent 2)

Готовое решение для мониторинга **Vinchin Backup & Recovery v9** (Rocky Linux 9)
через **Zabbix 7.4** и **Zabbix Agent 2**.

---

## Состав репозитория

| Файл | Назначение |
|---|---|
| `install_zabbix_agent2.sh` | **Автоустановщик** Zabbix Agent 2 + скриптов мониторинга |
| `vinchin/vinchin_collect.py` | Скрипт-коллектор (Python 3, без pip-зависимостей) |
| `vinchin/zabbix_agent2.d/userparameter_vinchin.conf` | UserParameter-ключи для агента |
| `vinchin/zbx_template_vinchin.xml` | Шаблон Zabbix (RU) |
| `vinchin/zbx_template_vinchin_en.xml` | Шаблон Zabbix (EN) |
| `vinchin/README.md` / `README.en.md` | Инструкции |

---

## Быстрый старт — автоматическая установка

Всё, что нужно — запустить скрипт **на самом Vinchin-апплайнсе** (Rocky Linux 9):

```bash
# Скачать
curl -fsSL -o install_zabbix_agent2.sh \
  https://raw.githubusercontent.com/squids911/Template-Vinchin-9-for-zabbix-7.4/main/install_zabbix_agent2.sh

# Запустить
bash install_zabbix_agent2.sh
```

Скрипт сделает всё сам:

1. ✋ Запросит **имя хоста** в Zabbix (можно ввести своё или нажать Enter)
2. 📦 Установит репозиторий Zabbix 7.4 и пакет `zabbix-agent2` с плагинами
3. 📥 Скачает из репозитория:
   - `vinchin_collect.py` → `/etc/zabbix/scripts/`
   - `userparameter_vinchin.conf` → `/etc/zabbix/zabbix_agent2.d/`
4. 🔧 Сгенерирует `/etc/zabbix/zabbix_agent2.conf`
5. 🔒 Настроит SELinux (контексты для скриптов)
6. 🔥 Откроет порт `10050/tcp` в firewalld
7. ▶️ Запустит и добавит агент в автозагрузку

### После установки

1. Импортировать шаблон `zbx_template_vinchin.xml` в Zabbix (7.4+)
2. Назначить шаблон хосту `Vinchin Backup and Recovery by API`
3. Заполнить макросы на уровне хоста:

| Макрос | Описание | Пример |
|---|---|---|
| `{$VINCHIN.URL}` | Адрес Vinchin API | `https://127.0.0.1:443` |
| `{$VINCHIN.USERNAME}` | Пользователь | `admin` |
| `{$VINCHIN.PASSWORD}` | Пароль (тип Secret text) | `ваш_пароль` |

> Пароль рекомендуется передавать как `b64:` + base64 от пароля,
> чтобы избежать проблем со спецсимволами в ключах элементов:
> ```
> b64:$(echo -n 'Pa$$w0rd!' | base64 -w0)
> ```

---

## Ручная установка

Если нужен только скрипт-коллектор без установки агента:

```bash
# Директории
mkdir -p /etc/zabbix/scripts /etc/zabbix/zabbix_agent2.d

# Скрипт
curl -fsSL -o /etc/zabbix/scripts/vinchin_collect.py \
  https://raw.githubusercontent.com/squids911/Template-Vinchin-9-for-zabbix-7.4/main/vinchin/vinchin_collect.py
chmod 755 /etc/zabbix/scripts/vinchin_collect.py

# Конфиг UserParameter
curl -fsSL -o /etc/zabbix/zabbix_agent2.d/userparameter_vinchin.conf \
  https://raw.githubusercontent.com/squids911/Template-Vinchin-9-for-zabbix-7.4/main/vinchin/zabbix_agent2.d/userparameter_vinchin.conf

# Перезапуск агента
systemctl restart zabbix-agent2
```

---

## Проверка работы

### Из командной строки

```bash
/etc/zabbix/scripts/vinchin_collect.py \
  --url https://127.0.0.1:443 \
  --username admin \
  --password "ваш_пароль" \
  summary
```

### Через Zabbix

1. Зайти в **Monitoring → Latest data**
2. Найти хост с именем, указанным при установке
3. Фильтр: `vinchin` — должны появиться элементы:
   - `Vinchin: Summary JSON`
   - `Vinchin: Jobs JSON`
   - `Vinchin: Storages JSON`
   - `Vinchin: Nodes JSON`

---

## Что мониторится

| Категория | Данные |
|---|---|
| **Сводка** | Running/waiting/failed/abnormal задачи, статус хранилищ, аптайм |
| **Задачи (джобы)** | UUID, имя, тип, статус, прогресс, расписание, последний результат |
| **Хранилища** | UUID, имя, тип, нода, емкость (total/used/free), статус |
| **Ноды (узлы)** | UUID, имя, IP, статус, версия, модули (в т.ч. офлайн) |

---

## Требования

- **Vinchin Backup & Recovery** 9.x (проверено на 9.0.0.92348)
- **ОС**: Rocky Linux 9 (апплайнс)
- **Zabbix** 7.0 / 7.4
- **Python** 3.9+ (только stdlib)
- **OpenSSL** 1.1+ / 3.x

---

## Лицензия

MIT