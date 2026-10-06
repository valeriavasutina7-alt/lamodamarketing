# -*- coding: utf-8 -*-
"""set_price.py — цены на Ламоде (RU): читать и ставить биг + продажную.

Модель цены Ламоды: у каждого товара есть `price` (БИГ / перечёркнутая) и
`salePrice` (ПРОДАЖНАЯ, что платит покупатель). По правилу price-only-discount
двигаем продажную (`sale_price`), а биг (`price`) меняем только по «да» оператора.
Цена задаётся НА МОДЕЛЬ (parent_sku, ≤12 символов = поле `parent_sku` карточки,
вида XD001XB0087T), а не на размер.

Ручки (Lamoda B2B, разобрано по OpenAPI 23.09.2026):
  GET  /nomenclature/sell-values                     — читать цены (price/salePrice)
  POST /nomenclature/country/RU/prices               — ставить RU-цену (массово)
  Тело: {partner_id, items:[{parent_sku, price, sale_price,
         sale_start_date, sale_end_date, need_auto_conversion}]}
  ⚠ при заданном sale_price ОБЯЗАТЕЛЬНЫ sale_start_date/sale_end_date (окно акции).
  BY/KZ — отдельная ручка PUT /nomenclature/{supplierSku}/country/{country}/price.

USAGE:
  python scripts/lamoda/set_price.py                       # показать модели БЕЗ продажной цены
  python scripts/lamoda/set_price.py --list-all            # все модели с их price/salePrice
  python scripts/lamoda/set_price.py --set PARENT:BIG:SALE[,PARENT:BIG:SALE...]        # dry-run
  python scripts/lamoda/set_price.py --set XD001XB0087T:5000:2790 --apply              # запись
  [--from 2026-09-23] [--until 2027-12-31]                 # окно акции (по умолч. сегодня..2027-12-31)

Грабли: токен 15 мин; parent_sku ровно поле карточки `parent_sku` (≤12); валидатор
рубит ВСЮ пачку, если хоть один parent_sku длиннее 12 — не слать sku/supplier_sku.
"""
import os, sys, io, json, datetime, urllib.request, urllib.parse, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from paths import load_cfg  # noqa: E402

A = sys.argv[1:]
def arg(f, d=None):
    return A[A.index(f) + 1] if f in A and A.index(f) + 1 < len(A) else d

PARTNER_ID = 210992937   # ИП Бобровская В.Н. FBS (LARETTO)

CFG = load_cfg()
BASE = CFG.get("api_base", "https://api-b2b.lamoda.ru/api/v1")

def token():
    q = urllib.parse.urlencode({"client_id": CFG["client_id"], "client_secret": CFG["client_secret"],
                                "grant_type": CFG.get("grant_type", "client_credentials")})
    url = CFG.get("token_url", "https://api-b2b.lamoda.ru/auth/token") + "?" + q
    return json.loads(urllib.request.urlopen(url, timeout=60).read())["access_token"]

TOKEN = token()

def call(path, method="GET", body=None):
    H = {"Authorization": "Bearer " + TOKEN, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode(); H["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=H, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.getcode(), json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {"__err__": e.read().decode("utf-8", "replace")[:400]}


def read_models():
    """parent -> {name, sizes, qty, big:set, sale:set} по всем sell-values."""
    models = {}
    page = 1
    while True:
        c, r = call(f"/nomenclature/sell-values?page={page}&limit=25")
        if "__err__" in r:
            sys.exit("чтение sell-values: " + r["__err__"])
        for n in r.get("_embedded", {}).get("nomenclatures", []):
            p = n.get("lamodaParentSku")
            m = models.setdefault(p, {"name": n.get("name"), "parentSku": n.get("parentSku"),
                                      "sizes": 0, "qty": 0, "big": set(), "sale": set()})
            m["sizes"] += 1; m["qty"] += int(n.get("quantity") or 0)
            for sv in n.get("_embedded", {}).get("sellValues", []):
                if sv.get("country") != "RU":
                    continue
                if sv.get("price") is not None: m["big"].add(sv["price"])
                if sv.get("salePrice") is not None: m["sale"].add(sv["salePrice"])
        if not r.get("_links", {}).get("next"):
            break
        page += 1
    return models


def cmd_list(all_models=False):
    models = read_models()
    rows = [(p, m) for p, m in models.items() if all_models or not m["sale"]]
    title = "ВСЕ модели" if all_models else "Модели БЕЗ продажной цены (salePrice)"
    print(f"{title}: {len(rows)} из {len(models)}")
    for p, m in sorted(rows, key=lambda x: (bool(x[1]["sale"]), -x[1]["sizes"])):
        big = sorted(m["big"]) or "—"; sale = sorted(m["sale"]) or "НЕТ"
        print(f"  {str(p):14} разм={m['sizes']:2} ост={m['qty']:3} биг={big} продажная={sale} | {str(m['name'])[:26]}")


def cmd_set(spec, apply):
    d_from = arg("--from", datetime.date.today().strftime("%Y-%m-%d"))
    d_until = arg("--until", "2027-12-31")
    start = f"{d_from}T00:00:00+03:00"; end = f"{d_until}T23:59:59+03:00"
    items = []
    for part in spec.split(","):
        parent, big, sale = part.split(":")
        if len(parent) > 12:
            sys.exit(f"parent_sku «{parent}» длиннее 12 символов — нужен код вида XD001XB0087T (поле parent_sku)")
        items.append({"parent_sku": parent, "price": float(big), "sale_price": float(sale),
                      "sale_start_date": start, "sale_end_date": end, "need_auto_conversion": False})
    print(f"Окно акции: {start} .. {end}")
    for it in items:
        print(f"  {it['parent_sku']:14} биг={it['price']:.0f} продажная={it['sale_price']:.0f}")
    if not apply:
        print("DRY-RUN (без --apply не пишу). Проверь и добавь --apply.")
        return
    c, r = call("/nomenclature/country/RU/prices", "POST", {"partner_id": PARTNER_ID, "items": items})
    if "__err__" in r:
        sys.exit("ЗАПИСЬ: HTTP %s %s" % (c, r["__err__"]))
    print(f"\nЗАПИСЬ: успешно {r.get('successCount')}, ошибок {r.get('errorCount')}")
    for e in r.get("errors", []):
        print("  ! ", e.get("lamodaParentSku"), e.get("messages"))
    for pr in r.get("prices", []):
        print(f"  OK {pr.get('lamodaSku')} биг={pr.get('price')} продажная={pr.get('salePrice')}")


def main():
    if "--set" in A:
        cmd_set(arg("--set"), "--apply" in A)
    else:
        cmd_list("--list-all" in A)


if __name__ == "__main__":
    main()
