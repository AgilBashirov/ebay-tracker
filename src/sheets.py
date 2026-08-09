"""
Google Sheets ilə işləmə: oxuma, yazma, formatlama.
Sətir sayı dinamikdir — 54 da olsa, 500 də olsa avtomatik tutur.
"""
import json
import os
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

import config

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


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
    gc = _client()
    sh = gc.open_by_key(config.SHEET_ID)
    return sh.worksheet(config.SHEET_NAME)


# ---------------------------------------------------------------------------
# Struktur qurulması
# ---------------------------------------------------------------------------

def ensure_structure(ws):
    """Başlıqları qoyur və bütün cədvəl görünüşünü tənzimləyir."""
    current = ws.row_values(1)
    if current[: len(config.HEADERS)] != config.HEADERS:
        ws.update(
            values=[config.HEADERS],
            range_name=f"A1:{_col_letter(len(config.HEADERS))}1",
        )
    apply_layout(ws)
    return True


def apply_layout(ws):
    """
    Cədvəlin bütün görünüşünü qurur:
      - başlıq sətri (tünd fon, ağ qalın mətn, dondurulmuş)
      - sütun enləri
      - mətn daşmasının qarşısı (CLIP) — uzun URL-lər yan xanalara girmir
      - rəqəm sütunları sağa, status/tarix mərkəzə düzülür
    """
    last_col = len(config.HEADERS)
    sheet_id = ws.id
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

    # ---- Başlığı dondur ----
    reqs.append({
        "updateSheetProperties": {
            "properties": {"sheetId": sheet_id,
                           "gridProperties": {"frozenRowCount": 1}},
            "fields": "gridProperties.frozenRowCount",
        }
    })

    # ---- Sütun enləri ----
    widths = {
        1: 150,   # A eBay Link
        2: 150,   # B Amazon Link
        3: 290,   # C Məhsul Adı
        4: 95,    # D eBay Qiymətim
        5: 70,    # E eBay Say
        6: 100,   # F Amazon (əvvəlki)
        7: 100,   # G Amazon (indiki)
        8: 145,   # H Stok
        9: 85,    # I Marja $
        10: 80,   # J Marja %
        11: 105,  # K Tövsiyə eBay
        12: 120,  # L Son Yoxlama
        13: 150,  # M Status
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
    align(9, 11, "RIGHT")    # I-K marja + təklif
    align(12, 13, "CENTER")  # L-M tarix + status

    # ---- Status sütunu qalın ----
    reqs.append({
        "repeatCell": {
            "range": {"sheetId": sheet_id, "startRowIndex": 1,
                      "startColumnIndex": 12, "endColumnIndex": 13},
            "cell": {"userEnteredFormat": {
                "textFormat": {"fontSize": 10, "bold": True}}},
            "fields": "userEnteredFormat.textFormat",
        }
    })

    try:
        ws.spreadsheet.batch_update({"requests": reqs})
    except Exception as e:
        print(f"[sheets] Format tətbiq edilə bilmədi: {e}")


def _col_letter(idx: int) -> str:
    letters = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


# ---------------------------------------------------------------------------
# Oxuma
# ---------------------------------------------------------------------------

def read_rows(ws):
    """Bütün məhsul sətirlərini oxuyur. Boş sətirlər atlanır."""
    values = ws.get_all_values()
    rows = []
    for i, raw in enumerate(values[config.FIRST_DATA_ROW - 1:], start=config.FIRST_DATA_ROW):
        padded = raw + [""] * (len(config.HEADERS) - len(raw))
        amazon = padded[config.COL["amazon_link"] - 1].strip()
        ebay = padded[config.COL["ebay_link"] - 1].strip()
        if not amazon and not ebay:
            continue
        rows.append(
            {
                "row": i,
                "ebay_link": ebay,
                "amazon_link": amazon,
                "product_name": padded[config.COL["product_name"] - 1].strip(),
                "ebay_price": _to_float(padded[config.COL["ebay_price"] - 1]),
                "ebay_qty": _to_int(padded[config.COL["ebay_qty"] - 1]),
                # Keçən dəfənin "indiki" qiyməti bu dəfənin "əvvəlki"sidir
                "amazon_old": _to_float(padded[config.COL["amazon_new"] - 1]),
                "stock_old": padded[config.COL["stock"] - 1].strip(),
                "last_check": padded[config.COL["last_check"] - 1].strip(),
            }
        )
    return rows


def _to_int(text):
    if text is None or str(text).strip() == "":
        return None
    digits = "".join(ch for ch in str(text) if ch.isdigit())
    return int(digits) if digits else None


def _to_float(text):
    if not text:
        return None
    cleaned = str(text).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_last_check(row):
    raw = row.get("last_check") or ""
    for fmt, length in (("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(raw[:length], fmt)
        except ValueError:
            continue
    return None


def pick_batch(rows, limit, interval_days=None):
    """
    Yalnız YOXLAMA VAXTI ÇATMIŞ məhsulları seçir (ən köhnədən başlayaraq).

    Niyə belə: GitHub cron "ən yaxşı cəhd" prinsipi ilə işləyir — bəzən saatda
    bir dəfə, bəzən 3 saatda bir işə düşür. Sabit batch ölçüsü ilə işləməlar
    ötürüləndə məhsullar geri qalırdı. Vaxtı çatanları seçmək bunu özü
    kompensasiya edir: işləmələr seyrək olsa növbə böyüyür, tez-tez olsa kiçilir.
    Nəticədə gündəlik yoxlama sayı işləmə tezliyindən asılı olmur.
    """
    if interval_days is None:
        interval_days = config.CHECK_INTERVAL_DAYS

    now = datetime.utcnow()
    threshold = timedelta(days=interval_days)

    due = []
    for r in rows:
        last = _parse_last_check(r)
        if last is None or (now - last) >= threshold:
            due.append((last or datetime.min, r))

    due.sort(key=lambda pair: pair[0])
    return [r for _, r in due[:limit]]


def count_due(rows, interval_days=None) -> int:
    if interval_days is None:
        interval_days = config.CHECK_INTERVAL_DAYS
    now = datetime.utcnow()
    threshold = timedelta(days=interval_days)
    return sum(
        1 for r in rows
        if (_parse_last_check(r) is None)
        or (now - _parse_last_check(r)) >= threshold
    )


def needs_ebay_refresh(row):
    """eBay məlumatı köhnəlibsə (və ya heç yoxdursa) yenidən oxunmalıdır."""
    if row["ebay_price"] is None or row.get("ebay_qty") is None:
        return True
    if not row["last_check"]:
        return True
    try:
        last = datetime.strptime(row["last_check"][:10], "%Y-%m-%d")
    except ValueError:
        return True
    return datetime.utcnow() - last > timedelta(days=config.EBAY_REFRESH_DAYS)


def should_fetch_ebay(row, amazon_in_stock: bool) -> bool:
    """
    eBay səhifəsini bu dəfə oxumağa dəyərmi?

    API kreditini qorumaq üçün eBay-i HƏR işləmədə oxumuruq. Yalnız qərar
    həqiqətən ondan asılı olanda oxuyuruq:
      • məlumat heç yoxdur / köhnədir (həftəlik yenilənmə)
      • listing bağlı görünür (say 0) — açılıb-açılmadığını bilmək lazımdır
      • Amazon-da stok yoxdur — bildiriş göndərib-göndərməmək sayıdan asılıdır

    Qalan hallarda (say > 0 və Amazon stokdadır) sheet-dəki dəyər kifayətdir.
    """
    if config.EBAY_PRICE_SOURCE != "scrape":
        return False
    if needs_ebay_refresh(row):
        return True
    qty = row.get("ebay_qty")
    # Say azdırsa və ya sıfırdırsa vəziyyət tez dəyişə bilər — hər dəfə yoxlayırıq.
    if qty is not None and qty <= config.EBAY_LOW_QTY:
        return True
    if not amazon_in_stock:
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
                "range": f"C{row}:M{row}",
                "values": [
                    [
                        r.get("product_name", ""),
                        _fmt_money(r.get("ebay_price")),
                        "" if qty is None else str(qty),
                        _fmt_money(r.get("amazon_old")),
                        _fmt_money(r.get("amazon_new")),
                        r.get("stock", ""),
                        _fmt_money(r.get("margin_usd")),
                        _fmt_pct(r.get("margin_pct")),
                        _fmt_money(r.get("suggested_ebay")),
                        now,
                        r.get("status", ""),
                    ]
                ],
            }
        )

    ws.batch_update(updates, value_input_option="USER_ENTERED")
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
