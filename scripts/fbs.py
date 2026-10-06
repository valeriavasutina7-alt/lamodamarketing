# -*- coding: utf-8 -*-
"""fbs.py — срез FBS-кабинета Ламоды (LARETTO / ИП Бобровская В.Н.).

Зачем: у нас на Ламоде один кабинет — FBS (b2b_crossdocking), бренд LARETTO.
Смотрим каталог/остатки/заказы/отгрузки/цены. Только чтение — в кабинет ничего
не пишем (ценовые/акционные ручки есть в scope, но трогаем их отдельно и по «да»).

Источник: Lamoda B2B API https://api-b2b.lamoda.ru/api/v1 (OAuth2 client_credentials).
Ключи: Desktop\\creds\\Ламода\\lamoda_api.txt (client_id/client_secret/token_url/api_base).
Данные пишем ТОЛЬКО в output/lamoda/ (правило marketplace-separation).

USAGE:
  python scripts/lamoda/fbs.py                 # сводка: каталог + остатки + заказы + отгрузки
  python scripts/lamoda/fbs.py --catalog       # номенклатуры (SKU, остаток, статус, модерация)
  python scripts/lamoda/fbs.py --orders        # заказы со статусами
  python scripts/lamoda/fbs.py --shipments     # отгрузки
  python scripts/lamoda/fbs.py --minprices     # минимальные цены по категориям (RU/BY/KZ)
  python scripts/lamoda/fbs.py --goods         # товары «в продаже» с ценами (когда пройдут модерацию)
  python scripts/lamoda/fbs.py --all           # всё сразу
  python scripts/lamoda/fbs.py --html          # собрать HTML-отчёт в output/lamoda/ (для Telegram)
  [--save]                                     # выгрузить CSV в output/lamoda/

Грабли Ламоды:
  - Токен OAuth2 client_credentials, живёт 15 мин (expires_in=900). Берём свежий каждый запуск.
  - Ответы в стиле HAL: тело в _embedded.<коллекция>, пагинация page/limit + _links.next.
  - Цена продажи (sell_value) отдаётся в /goods только для товаров, прошедших модерацию;
    у свежего кабинета /goods пустой. Остаток (quantity) лежит прямо в /nomenclatures.
  - /minimal_prices — это ПОЛ цены по категории (не наша цена), поля values.{RU,BY,KZ}.
  - supplier_sku = наш LRTT-код, sku = ламодовский артикул (напр. XD001XG00C8VCM098).
"""
import os, sys, io, csv, json, datetime, urllib.request, urllib.parse, urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from paths import DATA_DIR, load_cfg  # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
OUTDIR = str(DATA_DIR)

A = sys.argv[1:]

CFG = load_cfg()
BASE = CFG.get("api_base", "https://api-b2b.lamoda.ru/api/v1")


def get_token():
    q = urllib.parse.urlencode({
        "client_id": CFG["client_id"],
        "client_secret": CFG["client_secret"],
        "grant_type": CFG.get("grant_type", "client_credentials"),
    })
    url = CFG.get("token_url", "https://api-b2b.lamoda.ru/auth/token") + "?" + q
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))["access_token"]
    except urllib.error.HTTPError as e:
        sys.exit(f"токен Ламоды не получен: HTTP {e.code} {e.read().decode('utf-8','replace')[:300]}")


TOKEN = get_token()
H = {"Authorization": "Bearer " + TOKEN, "Accept": "application/json"}


def call(path, query=None, method="GET", body=None):
    url = BASE + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=H, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} на {method} {path}: {e.read().decode('utf-8','replace')[:400]}")


def fetch_all(path, collection, query=None, limit=100, cap_pages=200):
    """Собрать все элементы HAL-коллекции по страницам (page/limit + _links.next)."""
    rows = []
    page = 1
    while page <= cap_pages:
        q = dict(query or {})
        q.update({"page": page, "limit": limit})
        r = call(path, query=q)
        rows += (r.get("_embedded", {}) or {}).get(collection, [])
        if not (r.get("_links", {}) or {}).get("next"):
            break
        page += 1
    return rows


def save_csv(name, rows, cols):
    if "--save" not in A:
        return
    os.makedirs(OUTDIR, exist_ok=True)
    day = datetime.date.today().strftime("%Y%m%d")
    path = os.path.join(OUTDIR, f"{name}_{day}.csv")
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)
    print(f"  -> {path}")


# ---------- команды ----------
def cmd_catalog():
    noms = fetch_all("/nomenclatures", "nomenclatures")
    total_qty = sum(int(n.get("quantity") or 0) for n in noms)
    sellable = sum(1 for n in noms if n.get("isSellable"))
    print(f"Каталог Ламоды (FBS/LARETTO): {len(noms)} SKU, остаток {total_qty} шт, "
          f"в продаже (isSellable) {sellable}")
    by_status = {}
    for n in noms:
        by_status[n.get("status")] = by_status.get(n.get("status"), 0) + 1
    print("  статусы:", ", ".join(f"{k}={v}" for k, v in sorted(by_status.items(), key=lambda x: -x[1])))
    for n in sorted(noms, key=lambda x: -(int(x.get("quantity") or 0))):
        print(f"  {str(n.get('sku')):20} {str(n.get('supplier_sku')):26} "
              f"р.{str(n.get('supplier_size')):4} ост {int(n.get('quantity') or 0):4} | "
              f"{n.get('status')} | mod={n.get('qcModerationStage')} | {str(n.get('name'))[:32]}")
    rows = [{
        "sku": n.get("sku"), "supplier_sku": n.get("supplier_sku"),
        "parentSku": n.get("parentSku"), "size": n.get("supplier_size"),
        "quantity": n.get("quantity"), "status": n.get("status"),
        "isSellable": n.get("isSellable"), "isExportable": n.get("isExportable"),
        "qcModerationStage": n.get("qcModerationStage"), "qcModerationStatus": n.get("qcModerationStatus"),
        "name": n.get("name"), "color": n.get("color"), "barcode": n.get("barcode"),
        "brand": n.get("brand"), "category": n.get("lamodaSubCategory"), "vat": n.get("vat"),
    } for n in noms]
    save_csv("catalog", rows, list(rows[0].keys()) if rows else ["sku"])
    return noms


def cmd_orders():
    orders = fetch_all("/orders", "orders")
    print(f"Заказы Ламоды: {len(orders)}")
    by_status = {}
    for o in orders:
        st = o.get("status") or o.get("state")
        by_status[st] = by_status.get(st, 0) + 1
    for st, n in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"  {st}: {n}")
    if not orders:
        print("  заказов пока нет")
    save_csv("orders", orders, list(orders[0].keys()) if orders else ["id"])
    return orders


def cmd_shipments():
    sh = fetch_all("/shipments", "shipments")
    print(f"Отгрузки Ламоды: {len(sh)}")
    if not sh:
        print("  отгрузок пока нет")
    save_csv("shipments", sh, list(sh[0].keys()) if sh else ["id"])
    return sh


def cmd_minprices():
    mp = fetch_all("/minimal_prices", "minimal_prices")
    print(f"Минимальные цены по категориям: {len(mp)} записей (values RU/BY/KZ — это ПОЛ, не наша цена)")
    for m in mp[:60]:
        v = m.get("values", {}) or {}
        print(f"  {str(m.get('axaptaCategory1')):14} / {str(m.get('axaptaCategory2')):16} "
              f"RU={v.get('RU')} BY={v.get('BY')} KZ={v.get('KZ')}")
    if len(mp) > 60:
        print(f"  ... ещё {len(mp) - 60}")
    rows = [{"axaptaCategory1": m.get("axaptaCategory1"), "axaptaCategory2": m.get("axaptaCategory2"),
             "RU": (m.get("values") or {}).get("RU"), "BY": (m.get("values") or {}).get("BY"),
             "KZ": (m.get("values") or {}).get("KZ")} for m in mp]
    save_csv("minimal_prices", rows, ["axaptaCategory1", "axaptaCategory2", "RU", "BY", "KZ"])
    return mp


def cmd_goods():
    goods = fetch_all("/goods", "goods")
    print(f"Товары «в продаже» (/goods): {len(goods)}")
    if not goods:
        print("  пусто — карточки ещё не прошли модерацию (цены появятся здесь после неё)")
    else:
        for g in goods[:60]:
            print("  " + json.dumps(g, ensure_ascii=False)[:200])
    save_csv("goods", goods, list(goods[0].keys()) if goods else ["sku"])
    return goods


def cmd_html():
    """Собрать сводный HTML-отчёт по кабинету Ламоды в output/lamoda/ (для отправки в TG)."""
    noms = fetch_all("/nomenclatures", "nomenclatures")
    orders = fetch_all("/orders", "orders")
    shipments = fetch_all("/shipments", "shipments")
    total_qty = sum(int(n.get("quantity") or 0) for n in noms)
    sellable = sum(1 for n in noms if n.get("isSellable"))
    by_status = {}
    for n in noms:
        by_status[n.get("status")] = by_status.get(n.get("status"), 0) + 1
    now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

    def esc(s):
        return (str(s) if s is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    cards = [
        ("SKU в каталоге", len(noms)),
        ("Остаток, шт", total_qty),
        ("В продаже (isSellable)", sellable),
        ("Заказы", len(orders)),
        ("Отгрузки", len(shipments)),
    ]
    card_html = "".join(
        f'<div class="card"><div class="v">{v}</div><div class="k">{esc(k)}</div></div>' for k, v in cards)
    status_html = ", ".join(f"{esc(k)}={v}" for k, v in sorted(by_status.items(), key=lambda x: -x[1])) or "—"
    rows_html = "".join(
        f"<tr><td>{esc(n.get('sku'))}</td><td>{esc(n.get('supplier_sku'))}</td>"
        f"<td>{esc(n.get('supplier_size'))}</td><td class=r>{int(n.get('quantity') or 0)}</td>"
        f"<td>{esc(n.get('status'))}</td><td>{esc(n.get('qcModerationStage'))}</td>"
        f"<td>{esc(n.get('name'))}</td></tr>"
        for n in sorted(noms, key=lambda x: -(int(x.get('quantity') or 0))))

    html = f"""<!doctype html><html lang=ru><head><meta charset=utf-8>
<title>Ламода FBS — сводка {now}</title><style>
body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:#f5f5f7;color:#1d1d1f}}
.wrap{{max-width:900px;margin:0 auto;padding:20px}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#6e6e73;font-size:13px;margin-bottom:16px}}
.cards{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px}}
.card{{background:#fff;border-radius:12px;padding:14px 18px;min-width:120px;box-shadow:0 1px 3px rgba(0,0,0,.06)}}
.card .v{{font-size:24px;font-weight:700}} .card .k{{font-size:12px;color:#6e6e73;margin-top:2px}}
.status{{background:#fff;border-radius:12px;padding:12px 16px;margin-bottom:16px;font-size:13px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;font-size:13px}}
th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #eee}} th{{background:#fafafa;font-weight:600}}
td.r{{text-align:right}} tr:last-child td{{border-bottom:none}}
</style></head><body><div class=wrap>
<h1>Ламода FBS — LARETTO (ИП Бобровская В.Н.)</h1>
<div class=sub>Сводка на {now}. Только чтение, кабинет не меняли.</div>
<div class=cards>{card_html}</div>
<div class=status><b>Статусы карточек:</b> {status_html}</div>
<table><thead><tr><th>sku</th><th>supplier_sku</th><th>р-р</th><th>ост</th>
<th>статус</th><th>модерация</th><th>наименование</th></tr></thead><tbody>{rows_html}</tbody></table>
</div></body></html>"""
    os.makedirs(OUTDIR, exist_ok=True)
    day = datetime.date.today().strftime("%Y%m%d")
    path = os.path.join(OUTDIR, f"fbs_report_{day}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"HTML-отчёт: {path}")
    print(f"  каталог {len(noms)} SKU / остаток {total_qty} шт / в продаже {sellable} | "
          f"заказы {len(orders)} | отгрузки {len(shipments)}")
    return path


def main():
    if "--html" in A:
        cmd_html(); return
    do_cat = "--catalog" in A or "--all" in A
    do_ord = "--orders" in A or "--all" in A
    do_shp = "--shipments" in A or "--all" in A
    do_min = "--minprices" in A or "--all" in A
    do_goods = "--goods" in A or "--all" in A
    if not (do_cat or do_ord or do_shp or do_min or do_goods):   # сводка по умолчанию
        cmd_catalog(); print()
        cmd_orders(); print()
        cmd_shipments()
        return
    if do_cat:
        cmd_catalog(); print()
    if do_ord:
        cmd_orders(); print()
    if do_shp:
        cmd_shipments(); print()
    if do_min:
        cmd_minprices(); print()
    if do_goods:
        cmd_goods()


if __name__ == "__main__":
    main()
