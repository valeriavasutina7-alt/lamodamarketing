# -*- coding: utf-8 -*-
"""photos.py — карта «SKU → ссылка на фото» для портала AdPrice Multi.

Зачем: в таблицах портала SKU без картинки читается плохо — по XD001XB0087TCM098
не понять, о какой вещи речь. У Ламоды фото лежат в /nomenclatures (imageUrls:
[{url, order, type}]), в наших выгрузках их нет, поэтому карту собираем отдельным
файлом и обновляем по кнопке «Обновить».

Пишет output/lamoda/photos.json:
  {"ts": "...", "skus": {ключ: url}}

Ключей у одной вещи четыре, и в разных таблицах встречаются разные, поэтому все
четыре ведут на одну картинку: sku Ламоды (XD001XB0087TCM098), модель Ламоды
(XD001XB0087T), наш supplier_sku (LRTT-1469/00-0059454/98) и наш родитель
(LRTT-1469/00-0059454).

Только чтение. USAGE:
  portal\\.venv\\Scripts\\python.exe scripts\\lamoda\\photos.py
"""
import datetime
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# Токен, пагинация HAL и разбор ответа — те же, что у срезa FBS.
import fbs  # noqa: E402

DEST = os.path.join(fbs.OUTDIR, "photos.json")


def first_url(nom: dict) -> str:
    """Первая картинка номенклатуры.

    Ссылки лежат НЕ в `imageUrls` (так описано в спеке для другой ручки), а в
    `_embedded.images` — словаре групп («default» и прочие), в каждой список
    объектов с url. Сортируем по order, а не берём как пришло.
    """
    groups = ((nom.get("_embedded") or {}).get("images") or {})
    imgs = []
    if isinstance(groups, dict):
        for lst in groups.values():
            imgs += [i for i in (lst or []) if isinstance(i, dict) and i.get("url")]
    imgs += [i for i in (nom.get("imageUrls") or []) if isinstance(i, dict) and i.get("url")]
    if not imgs:
        return ""
    imgs.sort(key=lambda i: int(i.get("order") or 0))
    return str(imgs[0]["url"]).strip()


def main():
    noms = fbs.fetch_all("/nomenclatures", "nomenclatures")
    print(f"Номенклатур получено: {len(noms)}")
    skus: dict[str, str] = {}
    with_photo = 0
    for n in noms:
        url = first_url(n)
        if not url:
            continue
        with_photo += 1
        sup = str(n.get("supplier_sku") or "").strip()
        keys = [str(n.get("sku") or "").strip(),
                str(n.get("parentSku") or "").strip(),
                sup,
                # Наш родитель = supplier_sku без размера: именно так записан
                # ключ в выгрузках каталога (колонка parent).
                sup.rsplit("/", 1)[0] if sup.count("/") >= 2 else ""]
        for k in keys:
            if k:
                skus.setdefault(k, url)

    data = {"ts": datetime.datetime.now().isoformat(timespec="seconds"), "skus": skus}
    os.makedirs(fbs.OUTDIR, exist_ok=True)
    io.open(DEST, "w", encoding="utf-8").write(json.dumps(data, ensure_ascii=False))
    print(f"Готово: {DEST}\n  SKU с фото: {with_photo} из {len(noms)} · ключей в карте: {len(skus)}")
    if not with_photo:
        print("  ВНИМАНИЕ: ни одного фото — у карточек их пока нет либо ручка перестала их отдавать")


if __name__ == "__main__":
    main()
