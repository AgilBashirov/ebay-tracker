"""
Google Sheets ilə işləmə: oxuma, yazma, formatlama.
Sətir sayı dinamikdir — 54 da olsa, 500 də olsa avtomatik tutur.
"""
import json
import os
import random
import re
import time
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Xananın içindən URL çıxarmaq üçün (xam link və ya =HYPERLINK düsturu)
_URL_RE = re.compile(r'https?://[^"\'\s,;]+')

# Google-un müvəqqəti xətaları. Bunlar bizim kodun problemi deyil —
# Google tərəfdə qısamüddətli nasazlıqdır və təkrar cəhdlə keçib gedir.
RETRYABLE_CODES = (429, 500, 502, 503, 504)
MAX_ATTEMPTS = int(os.environ.get("SHEETS_MAX_ATTEMPTS", "5"))


def _is_retryable(exc) -> bool:
    """Xəta müvəqqətidirmi (yenidən cəhd etməyə dəyərmi)?"""
    code = getattr(getattr(exc, "response", None), "status_code", None)
    if code in RETRYABLE_CODES:
        return True
    text = str(exc)
    return any(f"[{c}]" in text for c in RETRYABLE_CODES) or \
        "currently unavailable" in text.lower() or \
        "internal error" in text.lower()


def with_retry(func, *args, what="Sheets əməliyyatı", **kwargs):
    """
    Google Sheets çağırışını müvəqqəti xətalarda təkrar edir.
    Gözləmə müddəti hər dəfə iki dəfə artır (1s, 2s, 4s, 8s).
    """
    delay = 1.0
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last = e
            if not _is_retryable(e) or attempt == MAX_ATTEMPTS:
                raise
            wait = delay + random.uniform(0, 0.5)
            print(f"[sheets] {what}: müvəqqəti xəta ({e.__class__.__name__}), "
                  f"{wait:.1f}s sonra təkrar ({attempt}/{MAX_ATTEMPTS - 1})")
            time.sleep(wait)
            delay *= 2
    raise last


def _client():
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON tapılmadı. "
            "GitHub Secrets-ə service account JSON-unu əlavə edin."
        )
    info = json.loads(raw)
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def open_sheet():
    def _open():
        gc = _client()
        sh = gc.open_by_key(config.SHEET_ID)
        return sh.worksheet(config.SHEET_NAME)

    return with_retry(_open, what="Sheet açılışı")


# ---------------------------------------------------------------------------
# Struktur qurulması
# ---------------------------------------------------------------------------

def ensure_structure(ws):
    """
    Cədvəli səliqəyə salır — hər işləmənin əvvəlində, bir dəfə.

      1. Başlıqları qoyur
      2. Uzun URL-ləri qısa, klikləyə bilən yazıya çevirir
      3. (istənilsə) sətirləri statusa görə sıralayır
      4. Formatı tətbiq edir: rəqəm formatları, zolaqlı sətirlər, filtr
      5. Məhsullardan sonrakı boş sahəni kəsir

    Bütün addımlar TƏKRAR TƏHLÜKƏSİZDİR: ikinci dəfə işləyəndə heç nə
    dəyişmir, artıq düzgün olan sahəyə toxunulmur.
    """
    values = read_grid(ws)
    header = values[0] if values else []
    if header[: len(config.HEADERS)] != config.HEADERS:
        ws.update(
            values=[config.HEADERS],
            range_name=f"A1:{_col_letter(len(config.HEADERS))}1",
        )

    last_row = _last_data_row(values)
    meta = _sheet_meta(ws)

    # Struktur dəyişəndə (məsələn "Avto" sütunları silinəndə) sağda qalan
    # köhnə məlumatı təmizləyirik — əks halda sheet-də mənasız sütunlar qalır.
    _clear_extra_columns(ws, len(header))

    if config.SHEET_SHORT_LINKS:
        _shorten_links(ws, values)

    # Sıralama MÜTLƏQ read_rows-dan əvvəl olmalıdır: nəticələr sətir nömrəsi
    # ilə yazılır, sıra sonradan dəyişsə yazı yanlış sətrə düşərdi.
    if config.SHEET_AUTO_SORT:
        _sort_by_status(ws, last_row)

    apply_layout(ws, last_row=last_row, meta=meta)

    if config.SHEET_TRIM_GRID:
        _trim_grid(ws, last_row, meta)
    return True


def _safe_batch(ws, requests, what: str) -> bool:
    """
    Formatlama sorğuları — biri alınmasa işləmə dayanmamalıdır.

    Ayrı-ayrı çağırışlara bölünür, çünki batch_update ATOMİKDİR: bir sorğu
    xəta versə (məs. zolaqlı sahə üst-üstə düşsə) həmin paketdəki BÜTÜN
    formatlar tətbiq olunmur.
    """
    if not requests:
        return False
    try:
        ws.spreadsheet.batch_update({"requests": requests})
        return True
    except Exception as e:
        print(f"[sheets] {what} tətbiq edilə bilmədi: {e}")
        return False


def _sheet_meta(ws) -> dict:
    """Bu vərəqin cari metaməlumatı: ölçüsü və mövcud zolaqlı sahələri."""
    try:
        meta = with_retry(ws.spreadsheet.fetch_sheet_metadata,
                          what="Cədvəl metaməlumatı")
    except Exception as e:
        print(f"[sheets] Metaməlumat oxuna bilmədi: {e}")
        return {}
    for sh in meta.get("sheets", []):
        if sh.get("properties", {}).get("sheetId") == ws.id:
            return sh
    return {}


def _grid_size(meta: dict, ws) -> tuple[int, int]:
    """(sətir sayı, sütun sayı) — metaməlumat yoxdursa gspread-in dəyəri."""
    grid = (meta.get("properties") or {}).get("gridProperties") or {}
    return (int(grid.get("rowCount") or ws.row_count),
            int(grid.get("columnCount") or ws.col_count))


def _last_data_row(values) -> int:
    """
    Məlumatı olan sonuncu sətrin nömrəsi.

    Yalnız linkə deyil, İSTƏNİLƏN dolu xanaya baxırıq — yarımçıq doldurulmuş
    sətri "boş" sayıb silmək olmaz.
    """
    need = len(config.HEADERS)
    last = 1
    for i, raw in enumerate(values, start=1):
        if any(str(c).strip() for c in raw[:need]):
            last = i
    return last


def _shorten_links(ws, values) -> None:
    """
    A/B sütunlarındaki uzun URL-ləri "eBay" / "Amazon" yazısına çevirir.

    URL İTMİR — =HYPERLINK("...","eBay") düsturunun içində qalır və
    read_grid onu FORMULA rejimində geri oxuyur. Artıq çevrilmiş xanalara
    toxunulmur, ona görə hər işləmədə təkrar sorğu getmir.
    """
    updates = []
    for i, raw in enumerate(values[config.FIRST_DATA_ROW - 1:],
                            start=config.FIRST_DATA_ROW):
        for key, label in LINK_COLUMNS:
            col = config.COL[key]
            cell = _text(raw[col - 1] if len(raw) >= col else "")
            if not cell or cell.startswith("="):
                continue                      # boşdur və ya onsuz da qısadır
            url = _fix_link(cell)
            if not url.lower().startswith("http"):
                continue                      # link deyil — toxunmuruq
            updates.append({"range": f"{_col_letter(col)}{i}",
                            "values": [[_hyperlink_formula(url, label)]]})
    if not updates:
        return
    try:
        with_retry(ws.batch_update, updates, value_input_option="USER_ENTERED",
                   what="Linklərin qısaldılması")
        print(f"[sheets] {len(updates)} link qısaldıldı")
    except Exception as e:
        print(f"[sheets] Linklər qısaldıla bilmədi: {e}")


def _sort_by_status(ws, last_row: int) -> None:
    """Sətirləri Status sütununa görə sıralayır (eyni problemlər yan-yana)."""
    if last_row <= config.FIRST_DATA_ROW:
        return
    _safe_batch(ws, [{
        "sortRange": {
            "range": {"sheetId": ws.id,
                      "startRowIndex": config.FIRST_DATA_ROW - 1,
                      "endRowIndex": last_row,
                      "startColumnIndex": 0,
                      "endColumnIndex": len(config.HEADERS)},
            "sortSpecs": [{"dimensionIndex": config.COL["status"] - 1,
                           "sortOrder": "ASCENDING"}],
        }
    }], "Sıralama")


def _trim_grid(ws, last_row: int, meta: dict) -> None:
    """
    Məhsullardan sonrakı boş sətirləri və O-dan sonrakı sütunları SİLİR.

    Məlumatı olan heç bir sətir silinmir — sərhəd _last_data_row ilə
    hesablanır və üstünə SHEET_SPARE_ROWS qədər ehtiyat əlavə olunur ki,
    yeni məhsul yazmaq üçün yer qalsın.
    """
    need_cols = len(config.HEADERS)
    rows_now, cols_now = _grid_size(meta, ws)
    keep_rows = max(last_row + max(config.SHEET_SPARE_ROWS, 0),
                    config.FIRST_DATA_ROW)

    reqs = []
    if cols_now > need_cols:
        reqs.append({"deleteDimension": {"range": {
            "sheetId": ws.id, "dimension": "COLUMNS",
            "startIndex": need_cols, "endIndex": cols_now}}})
    if rows_now > keep_rows:
        reqs.append({"deleteDimension": {"range": {
            "sheetId": ws.id, "dimension": "ROWS",
            "startIndex": keep_rows, "endIndex": rows_now}}})
    if reqs and _safe_batch(ws, reqs, "Artıq sahənin kəsilməsi"):
        print(f"[sheets] Cədvəl {keep_rows} sətir × {need_cols} sütuna salındı "
              f"(əvvəl {rows_now} × {cols_now})")


def _clear_extra_columns(ws, current_width: int) -> None:
    need = len(config.HEADERS)
    if current_width <= need:
        return
    first = _col_letter(need + 1)
    last = _col_letter(current_width)
    try:
        with_retry(ws.batch_clear, [f"{first}:{last}"],
                   what="Artıq sütunların təmizlənməsi")
        print(f"[sheets] Artıq sütunlar təmizləndi: {first}:{last}")
    except Exception as e:
        print(f"[sheets] Artıq sütunlar təmizlənə bilmədi: {e}")


def apply_layout(ws, last_row: int | None = None, meta: dict | None = None):
    """
    Cədvəlin bütün görünüşünü qurur:
      - başlıq sətri (tünd fon, ağ qalın mətn, dondurulmuş, altında xətt)
      - sütun enləri
      - mətn daşmasının qarşısı (CLIP) — uzun URL-lər yan xanalara girmir
      - rəqəm sütunları sağa, status/tarix mərkəzə düzülür
      - rəqəm formatları: dollar, faiz, tarix (mətn kimi yox, ƏSL rəqəm kimi)
      - zolaqlı sətirlər və başlıq sətrində avtomatik filtr
    """
    last_col = len(config.HEADERS)
    sheet_id = ws.id
    meta = meta or {}
    if last_row is None:
        last_row = _grid_size(meta, ws)[0]
    last_row = max(last_row, config.FIRST_DATA_ROW)
    reqs = []

    # ---- Başlıq ----
    reqs.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": last_col},
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 0.15, "green": 0.24, "blue": 0.36},
                "textFormat": {"bold": True, "fontSize": 10,
                               "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                "horizontalAlignment": "CENTER",
                "verticalAlignment": "MIDDLE",
                "wrapStrategy": "WRAP",
            }},
            "fields": ("userEnteredFormat(backgroundColor,textFormat,"
                       "horizontalAlignment,verticalAlignment,wrapStrategy)"),
        }
    })

    # ---- Başlığı və ilk 3 sütunu dondur ----
    # Sağa sürüşdürəndə məhsul adı ekranda qalır — əks halda hansı sətrin
    # hansı məhsul olduğunu itirirdiniz.
    reqs.append({
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"frozenRowCount": 1,
                                              "frozenColumnCount": 3}},
            "fields": ("gridProperties.frozenRowCount,"
                       "gridProperties.frozenColumnCount"),
        }
    })

    # ---- Sütun enləri ----
    # Linklər qısa saxlanılır: uzun URL-lər cədvəlin yarısını yeyirdi və
    # oxunmurdu. Xanaya klikləyib açmaq üçün bu en kifayətdir, məhsul adı
    # və rəqəmlər isə ekranda görünür.
    widths = {
        1: 58,    # A eBay Link
        2: 58,    # B Amazon Link
        3: 300,   # C Məhsul Adı
        4: 90,    # D eBay Qiymətim
        5: 70,    # E eBay Say
        6: 95,    # F Amazon (əvvəlki)
        7: 95,    # G Amazon (indiki)
        8: 140,   # H Stok
        9: 90,    # I eBay Haqqı
        10: 85,   # J Marja $
        11: 80,   # K Marja %
        12: 100,  # L Tövsiyə eBay
        13: 115,  # M Son Yoxlama
        14: 115,  # N Növbəti Yoxlama
        15: 150,  # O Status
    }
    for col, px in widths.items():
        reqs.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                          "startIndex": col - 1, "endIndex": col},
                "properties": {"pixelSize": px},
                "fields": "pixelSize",
            }
        })

    # ---- Lazımsız sütunları gizlət ----
    # SİLMİRİK, gizlədirik: kod sütunlara nömrə ilə müraciət edir, silinsə
    # bütün nömrələr sürüşər və sistem sıradan çıxar. Gizli sütun isə
    # məlumatını saxlayır, sadəcə görünmür.
    #   I  eBay Haqqı       -> haqq modeli artıq Marja $ içindədir
    #   K  Marja %          -> qərarlar dollarla verilir, faiz çaşdırırdı
    #   N  Növbəti Yoxlama  -> sistemin öz daxili cədvəli
    for col in (9, 11, 14):
        reqs.append({
            "updateDimensionProperties": {
                "range": {"sheetId": sheet_id, "dimension": "COLUMNS",
                          "startIndex": col - 1, "endIndex": col},
                "properties": {"hiddenByUser": True},
                "fields": "hiddenByUser",
            }
        })

    # ---- Məlumat sahəsi: daşma yoxdur, kiçik şrift ----
    reqs.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": last_col},
            "cell": {"userEnteredFormat": {
                "wrapStrategy": "CLIP",
                "verticalAlignment": "MIDDLE",
                "textFormat": {"fontSize": 10},
            }},
            "fields": "userEnteredFormat(wrapStrategy,verticalAlignment,textFormat)",
        }
    })

    # ---- Sütun düzülüşü ----
    def align(start_col, end_col, how):
        reqs.append({
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 1,
                          "startColumnIndex": start_col - 1, "endColumnIndex": end_col},
                "cell": {"userEnteredFormat": {"horizontalAlignment": how}},
                "fields": "userEnteredFormat.horizontalAlignment",
            }
        })

    align(1, 3, "LEFT")      # A-C linklər + ad
    align(4, 4, "RIGHT")     # D eBay qiyməti
    align(5, 5, "CENTER")    # E eBay say
    align(6, 7, "RIGHT")     # F-G Amazon qiymətləri
    align(8, 8, "LEFT")      # H stok mətni
    align(9, 12, "RIGHT")    # I-L haqq, marja, təklif
    align(13, 15, "CENTER")  # M-O tarixlər, status

    # ---- Status sütunu qalın ----
    reqs.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1,
                      "startColumnIndex": 14, "endColumnIndex": 15},
            "cell": {"userEnteredFormat": {
                "textFormat": {"fontSize": 10, "bold": True}}},
            "fields": "userEnteredFormat.textFormat",
        }
    })

    # ---- Rəqəm formatları ----
    # Dəyər xanada MƏTN kimi deyil, əsl rəqəm/tarix kimi saxlanılır: cəm,
    # sıralama və filtr yalnız bu halda düzgün işləyir.
    def number_format(cols, kind, pattern):
        for col in cols:
            reqs.append({
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1,
                              "startColumnIndex": col - 1, "endColumnIndex": col},
                    "cell": {"userEnteredFormat": {
                        "numberFormat": {"type": kind, "pattern": pattern}}},
                    "fields": "userEnteredFormat.numberFormat",
                }
            })

    # D qiymət · F/G Amazon · I haqq · J marja · L tövsiyə
    number_format([4, 6, 7, 9, 10, 12], "CURRENCY", '"$"#,##0.00')
    number_format([11], "PERCENT", "0.0%")
    # M/N tarixləri: bu şablon read_grid-in gözlədiyi formatdır — dəyişməyin,
    # əks halda _parse_dt tarixi oxuya bilməz və hər məhsul "vaxtı çatıb"
    # sayılar (bütün kredit bir işləmədə yanar).
    number_format([13, 14], "DATE_TIME", "yyyy-mm-dd hh:mm")

    # ---- Başlığın altında xətt ----
    reqs.append({
        "updateBorders": {
            "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1,
                      "startColumnIndex": 0, "endColumnIndex": last_col},
            "bottom": {"style": "SOLID_MEDIUM",
                       "color": {"red": 0.10, "green": 0.16, "blue": 0.24}},
        }
    })

    _safe_batch(ws, reqs, "Format")
    _apply_banding(ws, last_row, meta)
    _safe_batch(ws, [{
        "setBasicFilter": {"filter": {"range": {
            "sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": last_row,
            "startColumnIndex": 0, "endColumnIndex": last_col}}}
    }], "Avtomatik filtr")


def _apply_banding(ws, last_row: int, meta: dict) -> None:
    """
    Zolaqlı sətirlər (bir açıq, bir ağ) — uzun cədvəldə sətri itirməmək üçün.

    QEYD: statusa görə sətir rəngi (bax _apply_row_colors) zolağın ÜSTÜNDƏ
    durur, çünki xanaya birbaşa verilən fon zolaqdan üstündür. Yəni zolaq
    hələ yoxlanmamış sətirlərdə görünür, yoxlanmışlarda isə status rəngi.

    Mövcud zolaq varsa yenisi ƏLAVƏ edilmir, köhnəsi YENİLƏNİR — əks halda
    "banded range overlaps" xətası alınır.
    """
    banded = {"range": {"sheetId": ws.id, "startRowIndex": 1,
                        "endRowIndex": max(last_row, 2),
                        "startColumnIndex": 0,
                        "endColumnIndex": len(config.HEADERS)},
              "rowProperties": {
                  "firstBandColor": {"red": 1, "green": 1, "blue": 1},
                  "secondBandColor": {"red": 0.97, "green": 0.97, "blue": 0.98}}}

    existing = (meta.get("bandedRanges") or [])
    if existing:
        banded["bandedRangeId"] = existing[0]["bandedRangeId"]
        _safe_batch(ws, [{"updateBanding": {
            "bandedRange": banded, "fields": "range,rowProperties"}}],
            "Zolaqlı sətirlər")
    else:
        _safe_batch(ws, [{"addBanding": {"bandedRange": banded}}],
                    "Zolaqlı sətirlər")


def _col_letter(idx: int) -> str:
    letters = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


# ---------------------------------------------------------------------------
# Oxuma
# ---------------------------------------------------------------------------

# A/B sütunlarındaki linklərin qısa adı
LINK_COLUMNS = (("ebay_link", "eBay"), ("amazon_link", "Amazon"))


def read_grid(ws):
    """
    Cədvəlin xam məzmunu — bütün oxumalar bu funksiyadan keçir.

    value_render_option="FORMULA":
        A/B sütunları =HYPERLINK(...) düsturudur; adi rejimdə xanadan
        yalnız "eBay" yazısı gələrdi və LİNK İTƏRDİ. FORMULA rejimində
        düsturun özü gəlir, URL onun içindədir.

    date_time_render_option="FORMATTED_STRING":
        FORMULA rejimi tarixləri seriya nömrəsi kimi qaytarır (46278.41) —
        bu seçim onları "2026-09-18 10:00" mətni kimi saxlayır ki,
        _parse_dt oxuya bilsin.
    """
    return with_retry(ws.get_all_values,
                      value_render_option="FORMULA",
                      date_time_render_option="FORMATTED_STRING",
                      what="Sətirlərin oxunması")


def _text(value) -> str:
    """Xananın mətni. FORMULA rejimində rəqəm xanası float qaytara bilər."""
    return "" if value is None else str(value).strip()


def _hyperlink_formula(url: str, label: str) -> str:
    """=HYPERLINK("...","eBay") — URL-dəki dırnaq faiz kodu ilə əvəzlənir."""
    return '=HYPERLINK("{}","{}")'.format(url.replace('"', "%22"), label)


def _cell_link(raw) -> str:
    """
    Xanadan URL çıxarır — iki formanı da başa düşür:

        https://www.ebay.com/itm/157...         -> olduğu kimi
        =HYPERLINK("https://...","eBay")        -> içindəki URL

    Düsturu parçalamırıq, URL-i birbaşa axtarırıq: arqument ayırıcısı
    (vergül, yoxsa nöqtəli vergül) cədvəlin dilindən asılıdır, həmçinin
    düstur mətn kimi qalsa belə link yenə tapılır.
    """
    text = _text(raw)
    if not text:
        return ""
    if text.startswith("="):
        found = _URL_RE.search(text)
        return found.group(0) if found else ""
    return _fix_link(text)


def read_rows(ws):
    """Bütün məhsul sətirlərini oxuyur. Boş sətirlər atlanır."""
    values = read_grid(ws)
    rows = []
    for i, raw in enumerate(values[config.FIRST_DATA_ROW - 1:], start=config.FIRST_DATA_ROW):
        padded = list(raw) + [""] * (len(config.HEADERS) - len(raw))
        amazon = _cell_link(padded[config.COL["amazon_link"] - 1])
        ebay = _cell_link(padded[config.COL["ebay_link"] - 1])
        if not amazon and not ebay:
            continue
        rows.append(
            {
                "row": i,
                "ebay_link": ebay,
                "amazon_link": amazon,
                "product_name": _text(padded[config.COL["product_name"] - 1]),
                "ebay_price": _to_float(padded[config.COL["ebay_price"] - 1]),
                "ebay_qty": _to_int(padded[config.COL["ebay_qty"] - 1]),
                # Keçən dəfənin "indiki" qiyməti bu dəfənin "əvvəlki"sidir
                "amazon_old": _to_float(padded[config.COL["amazon_new"] - 1]),
                "stock_old": _text(padded[config.COL["stock"] - 1]),
                "last_check": _text(padded[config.COL["last_check"] - 1]),
                "next_check": _text(padded[config.COL["next_check"] - 1]),
                "prev_status": _text(padded[config.COL["status"] - 1]),
            }
        )
    return rows


def _fix_link(raw: str) -> str:
    """
    Linki düzəldir: "amazon.com/Pack-Teflo" -> "https://www.amazon.com/Pack-Teflo"

    Sheet-ə əl ilə yapışdırılan linklərdə bəzən "https://" olmur. Əvvəllər belə
    sətirlər "XETA link yoxdur" alırdı, halbuki link əslində işləyirdi.
    """
    link = (raw or "").strip()
    if not link:
        return ""
    if link.startswith(("http://", "https://")):
        return link
    if link.startswith("//"):
        return "https:" + link
    # Domenlə başlayırsa protokol əlavə edirik
    if re.match(r"^(www\.)?(amazon|ebay)\.[a-z.]{2,8}/", link, re.I):
        if not link.lower().startswith("www."):
            link = "www." + link
        return "https://" + link
    return link


def _to_int(text):
    # Əvvəlcə rəqəm kimi oxumağa çalışırıq: FORMULA rejimində xana "3" yox,
    # 3.0 qaytara bilər — rəqəmləri bir-birinə yapışdırsaq 30 alınardı.
    value = _to_float(text)
    if value is not None:
        return int(value)
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    return int(digits) if digits else None


def _to_float(text):
    if text is None or str(text).strip() == "":
        return None
    cleaned = str(text).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_dt(raw):
    """Sheet-dəki tarix mətnini datetime-a çevirir."""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt, length in (("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(raw[:length], fmt)
        except ValueError:
            continue
    return None


def _parse_last_check(row):
    return _parse_dt(row.get("last_check"))


def pick_batch(rows, limit, force=False):
    """
    Yoxlama vaxtı çatmış məhsulları seçir (ən gecikmişdən başlayaraq).

    Hər sətirin öz "Növbəti Yoxlama" (N sütunu) vaxtı var. Sabit qalan məhsulun
    aralığı tədricən uzanır (1→2→3 gün), dəyişkəni isə hər gün yoxlanılır.
    Bu, API kreditinə əsas qənaət mexanizmidir.

    force=True olduqda vaxt nəzərə alınmır (əl ilə məcburi işləmə).
    """
    now = datetime.utcnow()

    due = []
    for r in rows:
        nxt = _parse_dt(r.get("next_check"))
        if force or nxt is None or nxt <= now:
            # Sıralama açarı: gecikmə nə qədər çoxdursa, o qədər öndə
            key = nxt or _parse_dt(r.get("last_check")) or datetime.min
            due.append((key, r))

    due.sort(key=lambda pair: pair[0])
    return [r for _, r in due[:limit]]


def count_due(rows) -> int:
    now = datetime.utcnow()
    return sum(
        1 for r in rows
        if (_parse_dt(r.get("next_check")) is None)
        or (_parse_dt(r.get("next_check")) <= now)
    )


def previous_interval_days(row) -> float:
    """
    Bu sətirdə əvvəlki yoxlama aralığı neçə gün idi?
    (Növbəti yoxlama − son yoxlama). Yoxdursa başlanğıc aralıq qaytarılır.
    """
    last = _parse_dt(row.get("last_check"))
    nxt = _parse_dt(row.get("next_check"))
    if last and nxt and nxt > last:
        return round((nxt - last).total_seconds() / 86400, 2)
    return config.CHECK_INTERVAL_DAYS


def needs_ebay_refresh(row):
    """
    eBay məlumatı köhnəlibsə (və ya qiymət yoxdursa) yenidən oxunmalıdır.

    Qeyd: say (E sütunu) boş olsa da təkrar oxumuruq — eBay onu çox vaxt
    ümumiyyətlə vermir, hər dəfə cəhd etmək krediti boş yerə xərcləyər.
    Say sizin üçün vacibdirsə, E sütununa əl ilə yazın — sistem onu saxlayır.
    """
    if row["ebay_price"] is None:
        return True
    if not row["last_check"]:
        return True
    last = _parse_dt(row["last_check"])
    if last is None:
        return True
    return datetime.utcnow() - last > timedelta(days=config.EBAY_REFRESH_DAYS)


def should_fetch_ebay(row, amazon_in_stock: bool,
                      amazon_price_changed: bool = False) -> bool:
    """
    eBay səhifəsini bu dəfə oxumağa dəyərmi?

    ƏSAS PRİNSİP: eBay qiymətiniz yalnız SİZ onu dəyişəndə dəyişir — Amazon
    kimi öz-özünə tərpənmir. Ona görə dövri oxumaq krediti boş yerə yandırır.
    Yalnız marja hesabının nəticəsi dəyişə biləcək hallarda oxuyuruq:

      1. Yeni məhsul     — sheet-də eBay qiyməti hələ yoxdur
      2. Qiymət fərqi    — Amazon qiyməti dəyişib, marja yenidən hesablanır
      3. Təklif vermişik — keçən dəfə "qiyməti dəyiş" dedik, tətbiq olunubmu?
      4. Stok yoxdur     — bildiriş qərarı üçün eBay sayı lazımdır
      5. Çox köhnədir    — təhlükəsizlik üçün 30 gündə bir

    Qalan hallarda sheet-dəki dəyər istifadə olunur (kredit sərf olunmur).
    """
    if config.EBAY_PRICE_SOURCE != "scrape":
        return False

    # 1) Yeni məhsul
    if row.get("ebay_price") is None:
        return True

    # 2) Amazon qiyməti dəyişib — marja dəyişir
    if amazon_price_changed:
        return True

    # 3) Keçən dəfə qiymət dəyişikliyi tövsiyə etmişdik — icra olunubmu?
    prev = (row.get("prev_status") or "").strip()
    if prev.startswith(("QIYMET", "AZ MARJA", "TEKRAR AC", "AZ STOK")):
        return True

    # 4) Amazon-da stok yoxdur — bildiriş qərarı eBay sayından asılıdır
    if not amazon_in_stock:
        return True

    # 5) Uzun müddət oxunmayıb
    if needs_ebay_refresh(row):
        return True

    return False


# ---------------------------------------------------------------------------
# Yazma
# ---------------------------------------------------------------------------

def write_results(ws, results):
    """
    results: [{row, product_name, ebay_price, amazon_old, amazon_new,
               stock, margin_usd, margin_pct, suggested_ebay, status}]
    Sətir-sətir deyil, toplu (batch) yazır — sürətli və kvota dostu.
    """
    if not results:
        return

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    updates = []
    for r in results:
        row = r["row"]
        qty = r.get("ebay_qty")
        updates.append(
            {
                "range": f"C{row}:O{row}",
                "values": [
                    [
                        r.get("product_name", ""),
                        _fmt_money(r.get("ebay_price")),
                        "" if qty is None else str(qty),
                        _fmt_money(r.get("amazon_old")),
                        _fmt_money(r.get("amazon_new")),
                        r.get("stock", ""),
                        _fmt_money(r.get("ebay_fee")),
                        _fmt_money(r.get("margin_usd")),
                        _fmt_pct(r.get("margin_pct")),
                        _fmt_money(r.get("suggested_ebay")),
                        now,
                        r.get("next_check", ""),
                        r.get("status", ""),
                    ]
                ],
            }
        )

    with_retry(ws.batch_update, updates, value_input_option="USER_ENTERED",
               what="Sətirlərin yazılması")
    _apply_row_colors(ws, results)


def _fmt_money(v):
    return "" if v is None else f"${v:,.2f}"


def _fmt_pct(v):
    return "" if v is None else f"{v:.1f}%"


def _apply_row_colors(ws, results):
    """Status sütununa görə sətiri rəngləyir — vizual olaraq dərhal görünsün."""
    palette = {
        "OK":        {"red": 0.91, "green": 0.96, "blue": 0.91},  # açıq yaşıl
        "QIYMET+":   {"red": 1.00, "green": 0.92, "blue": 0.83},  # narıncı
        "QIYMET-":   {"red": 0.89, "green": 0.95, "blue": 1.00},  # mavi
        "AZ":        {"red": 1.00, "green": 0.97, "blue": 0.80},  # sarı (AZ MARJA)
        "STOK":      {"red": 0.99, "green": 0.85, "blue": 0.85},  # qırmızı (STOK YOX)
        "STOK_PASSIV": {"red": 0.96, "green": 0.96, "blue": 0.96},  # solğun (eBay bağlı)
        "AZ_STOK":   {"red": 1.00, "green": 0.89, "blue": 0.78},  # tünd narıncı
        "TEKRAR":    {"red": 0.85, "green": 0.93, "blue": 0.99},  # mavi (yenidən aç)
        "XETA":      {"red": 0.93, "green": 0.93, "blue": 0.93},  # boz
        "BLOKLANDI": {"red": 0.91, "green": 0.89, "blue": 0.98},  # bənövşəyi
    }
    requests = []
    for r in results:
        status = r.get("status") or "OK"
        key = status.split()[0]
        if key == "STOK" and "bağlı" in status:
            key = "STOK_PASSIV"
        elif status.startswith("AZ STOK"):
            key = "AZ_STOK"
        color = palette.get(key, palette["OK"])
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": r["row"] - 1,
                        "endRowIndex": r["row"],
                        "startColumnIndex": 0,
                        "endColumnIndex": len(config.HEADERS),
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": color}},
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        )
    if requests:
        try:
            ws.spreadsheet.batch_update({"requests": requests})
        except Exception:
            pass
