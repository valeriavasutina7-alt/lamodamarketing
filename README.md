# lamodamarketing

Скрипты и данные Ламоды (FBS, цены, каталог, авто-прайсер).

## Структура

| Путь | Назначение |
|---|---|
| `scripts/` | fbs.py, auto_pricer.py, set_price.py, photos.py |
| `scripts/lib/paths.py` | пути, ключи API, ссылки на wb-ad-agents |
| `data/` | CSV/HTML/JSON отчёты (не в git) |

## Зависимости из wb-ad-agents

- Python: `portal/.venv` (переменная `LAMODA_PYTHON` или `WB_AGENTS_ROOT`)
- COGS: `scripts/datalake/`
- Telegram: `scripts/notify_telegram.ps1`

## Планировщик

`\WB\lamoda_auto_pricer` → `scripts/_sched_auto_pricer.cmd` (12:00 ежедневно).

## Портал AdPrice Multi

Портал читает `LAMODA_ROOT/data` и запускает скрипты отсюда
(см. `wb-ad-agents/portal/adprice_multi/app/config.py`).
