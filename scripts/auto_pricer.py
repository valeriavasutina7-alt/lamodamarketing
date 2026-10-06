# -*- coding: utf-8 -*-
"""auto_pricer.py — авто-простановка цен Ламоды на НОВЫЕ готовые модели.

Логика (идемпотентно, безопасно): находит модели, у которых уже залито фото,
но ещё НЕТ продажной цены (salePrice) — это «готовые, но незаценённые». Считает
цену по нашему Х (одежда 2,6Х) от себестоимости 1С, ставит биг + продажную.
Уже проценённые модели НЕ трогает (биг повторно не двигает — правило price-only-discount).

Х: sale = (X·COGS + 303) / 0,6011 (комиссия 29% + эквайринг 1,8% + логистика 303 ₽,
НДС 10%, см. lamoda-fbs-commission). Биг ≈ sale/0,55 (скидка ~45%). Округление до 10 ₽.

COGS: из data-lake (приходные 1С, unit_price_rub), по коду 1С из supplierParentSku
(`LRTT-xxx/00-00xxxxx`). Нет COGS / COGS<50 ₽ (валютная) — модель ПРОПУСКАЕМ и пишем в отчёт.

USAGE:
  python scripts/lamoda/auto_pricer.py            # dry-run: кандидаты + расчёт, без записи
  python scripts/lamoda/auto_pricer.py --apply    # записать цены + собрать HTML-отчёт
Данные/отчёт — только output/lamoda/. Запись цен — POST /nomenclature/country/RU/prices.
"""
import os, sys, io, csv, json, time, subprocess, datetime, urllib.request, urllib.parse, urllib.error

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
from paths import DATA_DIR, DATALAKE_DIR, NOTIFY_PS1, PYTHON, load_cfg  # noqa: E402

OUTDIR = str(DATA_DIR)
PY = str(PYTHON)
A = sys.argv[1:]
APPLY = "--apply" in A
NOTIFY = "--notify" in A
PARTNER_ID = 210992937
TARGET_X = 2.6
K = 1 - 10/110 - 0.29 - 0.018      # доля цены после НДС+комиссии+эквайринга = 0.6011
LOG = 303                          # приём 15 + доставка одежда 288, ₽/шт
MIN_COGS = 50                      # ниже — подозрение на валютную цену, пропускаем

CFG = load_cfg()
BASE = CFG.get("api_base", "https://api-b2b.lamoda.ru/api/v1")

def token():
    q = urllib.parse.urlencode({"client_id": CFG["client_id"], "client_secret": CFG["client_secret"],
                                "grant_type": CFG.get("grant_type", "client_credentials")})
    return json.loads(urllib.request.urlopen(CFG.get("token_url", "https://api-b2b.lamoda.ru/auth/token") + "?" + q,
                                             timeout=60).read())["access_token"]
TOK = token()

def call(path, method="GET", body=None):
    global TOK
    for a in range(5):
        try:
            H = {"Authorization": "Bearer " + TOK, "Accept": "application/json"}
            data = None
            if body is not None:
                data = json.dumps(body).encode(); H["Content-Type"] = "application/json"
            with urllib.request.urlopen(urllib.request.Request(BASE + path, data=data, headers=H, method=method), timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                TOK = token(); continue
            return {"__err__": "%s %s" % (e.code, e.read().decode("utf-8", "replace")[:200])}
        except Exception as e:
            if a == 4:
                return {"__err__": str(e)[:120]}
            time.sleep(3)


def scan_unpriced():
    """Модели БЕЗ продажной цены (RU). Возвращает ({lamodaParent: {code,name}}, set проценённых).
    Гейт — не фото, а отсутствие salePrice: ставим цену заранее на всё, что её принимает
    (решение оператора 30.09.2026). Код 1С берём из parentSku `LRTT-xxx/00-00xxxxx`."""
    cand = {}
    priced = set()
    page = 1
    while True:
        r = call(f"/nomenclature/sell-values?page={page}&limit=25")
        if "__err__" in r:
            sys.exit("sell-values: " + r["__err__"])
        for n in r.get("_embedded", {}).get("nomenclatures", []):
            lp = n.get("lamodaParentSku"); ps = n.get("parentSku") or ""
            has = any(sv.get("country") == "RU" and sv.get("salePrice") is not None
                      for sv in n.get("_embedded", {}).get("sellValues", []))
            if has:
                priced.add(lp); continue
            if lp and lp not in cand:
                cand[lp] = {"lamodaParent": lp, "name": n.get("name"),
                            "code": ps.split("/")[1] if len(ps.split("/")) > 1 else None}
        if not r.get("_links", {}).get("next"):
            break
        page += 1
    return cand, priced


def cogs_for(codes):
    """код 1С -> COGS из data-lake (последняя приходная). Нет туннеля -> {}."""
    if not codes:
        return {}
    lst = ",".join("'%s'" % c for c in codes)
    sql = ("select p.code, round(avg(r.unit_price_rub),2) as cogs "
           "from core.core_onec_receipts_priced r join core.core_onec_products p using (nomenclature_key) "
           "join (select p2.code c, max(r2.receipt_date) md from core.core_onec_receipts_priced r2 "
           "join core.core_onec_products p2 using(nomenclature_key) where p2.code in (%s) group by p2.code) "
           "last on last.c=p.code and last.md=r.receipt_date where p.code in (%s) group by p.code;" % (lst, lst))
    out = os.path.join(OUTDIR, "_autoprice_cogs.csv")
    subprocess.run([os.path.join(ROOT, "scripts", "datalake", "tunnel.cmd")], shell=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r = subprocess.run([PY, os.path.join(ROOT, "scripts", "datalake", "query.py"), sql, "--csv", out],
                       capture_output=True, text=True)
    res = {}
    if os.path.exists(out):
        for row in csv.DictReader(open(out, encoding="utf-8-sig"), delimiter=";"):
            try:
                res[row["code"]] = float(row["cogs"])
            except (ValueError, KeyError):
                pass
    return res


def price_of(cogs):
    sale = int(round(((TARGET_X * cogs + LOG) / K) / 10.0) * 10)
    big = int(round((sale / 0.55) / 10.0) * 10)
    return big, sale


def build_html(applied, skipped, total_priced, waiting):
    now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    def esc(s): return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    rows = "".join(
        f"<tr><td>{esc(a['lp'])}</td><td>{esc(a['name'])}</td><td class=r>{a['cogs']:.0f}</td>"
        f"<td class=r>{a['big']}</td><td class=r>{a['sale']}</td><td class=r>{a['x']:.2f}</td></tr>"
        for a in applied)
    skip = ""
    if skipped:
        skip = "<h3>Пропущены (нет/битая COGS)</h3><ul>" + "".join(
            f"<li>{esc(s['name'])} [{esc(s.get('code'))}] — {esc(s['why'])}</li>" for s in skipped) + "</ul>"
    html = f"""<!doctype html><html lang=ru><head><meta charset=utf-8><title>Ламода авто-цены {now}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f5f5f7;color:#1d1d1f}}
.wrap{{max-width:820px;margin:0 auto;padding:20px}}h1{{font-size:19px;margin:0 0 4px}}
.sub{{color:#6e6e73;font-size:13px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;font-size:13px}}
th,td{{padding:8px 10px;text-align:left;border-bottom:1px solid #eee}}th{{background:#fafafa}}td.r{{text-align:right}}</style>
</head><body><div class=wrap>
<h1>Ламода · авто-простановка цен (LARETTO)</h1>
<div class=sub>{now}. Проставлено сегодня: <b>{len(applied)}</b>. Всего проценено моделей: {total_priced}.</div>
<table><thead><tr><th>модель</th><th>наименование</th><th>COGS</th><th>биг</th><th>продажная</th><th>X</th></tr></thead>
<tbody>{rows or '<tr><td colspan=6>новых готовых моделей нет</td></tr>'}</tbody></table>
{skip}</div></body></html>"""
    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, "autoprice_%s.html" % datetime.date.today().strftime("%Y%m%d"))
    open(path, "w", encoding="utf-8").write(html)
    return path


def main():
    cand_map, priced = scan_unpriced()
    total_priced = len(priced)
    waiting = 0
    cand = list(cand_map.items())
    print(f"Уже проценено моделей: {total_priced}; без продажной цены: {len(cand)}")

    cogs = cogs_for([m["code"] for _, m in cand if m["code"]])
    applied, skipped, items = [], [], []
    for sp, m in cand:
        c = cogs.get(m["code"])
        if not c:
            skipped.append({"name": m["name"], "code": m["code"], "why": "нет COGS в data-lake"}); continue
        if c < MIN_COGS:
            skipped.append({"name": m["name"], "code": m["code"], "why": f"COGS {c:.0f} < {MIN_COGS} (валютная?)"}); continue
        big, sale = price_of(c)
        x = (K * sale - LOG) / c
        rec = {"lp": m["lamodaParent"], "name": m["name"], "cogs": c, "big": big, "sale": sale, "x": x}
        applied.append(rec)
        items.append({"parent_sku": m["lamodaParent"], "price": big, "sale_price": sale,
                      "sale_start_date": datetime.date.today().strftime("%Y-%m-%dT00:00:00+03:00"),
                      "sale_end_date": "2027-12-31T23:59:59+03:00", "need_auto_conversion": False})
    for a in applied:
        print(f"  {a['lp']:14} {str(a['name'])[:18]:18} COGS={a['cogs']:.0f} биг={a['big']} продажн={a['sale']} X={a['x']:.2f}")
    for s in skipped:
        print(f"  ПРОПУСК {s['name']} [{s['code']}]: {s['why']}")

    if APPLY and items:
        r = call("/nomenclature/country/RU/prices", "POST", {"partner_id": PARTNER_ID, "items": items})
        if "__err__" in r:
            print("ЗАПИСЬ ОШИБКА:", r["__err__"]); sys.exit(2)
        print(f"ЗАПИСЬ: успешно {r.get('successCount')}, ошибок {r.get('errorCount')}")
        for e in r.get("errors", []):
            print("  !", e.get("lamodaParentSku"), e.get("messages"))
    elif not APPLY:
        print("DRY-RUN (без --apply не пишу)")
    htmlpath = build_html(applied, skipped, total_priced + (len(applied) if APPLY else 0), waiting)
    print("HTML:", htmlpath)

    # отчёт в TG только когда была работа (проставили) или есть что показать оператору (пропуски)
    if NOTIFY and (applied or skipped):
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(NOTIFY_PS1),
                        "-Title", "lamoda-autoprice", "-Status", "0", "-ReportOnly",
                        "-AttachGlob", htmlpath, "-ChatId", "-1003797610374", "-ThreadId", "1826"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
