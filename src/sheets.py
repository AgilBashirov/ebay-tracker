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
    """Başlıqları yoxlayır/qoyur və sütun formatını tənzimləyir. Bir dəfə işləyir."""
    current = ws.row_values(1)
    if current[: len(config.HEADERS)] != config.HEADERS:
        ws.update(
            values=[config.HEADERS],
            range_name=f"A1:{_col_letter(len(config.HEADERS))}1",
        )
        _format_header(ws)
        _set_column_widths(ws)
    return True


def _col_letter(idx: int) -> str:
    letters = ""
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _format_header(ws):
    ws.format(
        f"A1:{_col_letter(len(config.HEADERS))}1",
        {
            "backgroundColor": {"red": 0.15, "green": 0.24, "blue": 0.36},
            "textFormat": {
                "bold": True,
                "fontSize": 10,
                "foregroundColor": {"red": 1, "green": 1, "blue": 1},
            },
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
        },
    )
    try:
        ws.freeze(rows=1)
    except Exception:
        pass


def _set_column_widths(ws):
    """Sütun enləri — linklər dar, məlumat sütunları oxunaqlı."""
    widths = {
        1: 170,   # eBay Link
        2: 170,   # Amazon Link
        3: 320,   # Məhsul Adı
        4: 100,   # eBay Qiymətim
        5: 110,   # Amazon əvvəlki
        6: 110,   # Amazon indiki
        7: 150,   # Stok
        8: 85,    # Marja $
        9: 85,    # Marja %
        10: 110,  # Tövsiyə eBay
        11: 110,  # Son Yoxlama
        12: 130,  # Status
    }
    sheet_id = ws.id
    requests = [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": col - 1,
                    "endIndex": col,
                },
                "properties": {"pixelSize": px},
                "fields": "pixelSize",
            }
        }
        for col, px in widths.items()
    ]
    try:
        ws.spreadsheet.batch_update({"requests": requests})
    except Exception:
        pass


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
                "amazon_old": _to_float(padded[config.COL["amazon_new"] - 1]),
                "stock_old": padded[config.COL["stock"] - 1].strip(),
                "last_check": padded[config.COL["last_check"] - 1].strip(),
            }
        )
    return rows


def _to_float(text):
    if not text:
        return None
    cleaned = str(text).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def pick_batch(rows, batch_size):
    """
    Ən köhnə yoxlanmış sətirləri seçir — beləliklə yük saatlara yayılır
    və 500 məhsul da növbə ilə tam əhatə olunur.
    """
    def sort_key(r):
        if not r["last_check"]:
            return datetime.min
        try:
            return datetime.strptime(r["last_check"][:16], "%Y-%m-%d %H:%M")
        except ValueError:
            try:
                return datetime.strptime(r["last_check"][:10], "%Y-%m-%d")
            except ValueError:
                return datetime.min

    return sorted(rows, key=sort_key)[:batch_size]


def needs_ebay_refresh(row):
    """eBay qiyməti köhnəlibsə (və ya heç yoxdursa) yenidən oxunmalıdır."""
    if row["ebay_price"] is None:
        return True
    if not row["last_check"]:
        return True
    try:
        last = datetime.strptime(row["last_check"][:10], "%Y-%m-%d")
    except ValueError:
        return True
    return datetime.utcnow() - last > timedelta(days=config.EBAY_REFRESH_DAYS)


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
        updates.append(
            {
                "range": f"C{row}:L{row}",
                "values": [
                    [
                        r.get("product_name", ""),
                        _fmt_money(r.get("ebay_price")),
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
        "OK":        {"red": 0.85, "green": 0.94, "blue": 0.83},  # yaşıl
        "QIYMET+":   {"red": 1.00, "green": 0.90, "blue": 0.80},  # narıncı
        "AZ MARJA":  {"red": 1.00, "green": 0.95, "blue": 0.75},  # sarı
        "STOK YOX":  {"red": 0.99, "green": 0.80, "blue": 0.80},  # qırmızı
        "XETA":      {"red": 0.90, "green": 0.90, "blue": 0.90},  # boz
        "BLOKLANDI": {"red": 0.85, "green": 0.82, "blue": 0.95},  # bənövşəyi
    }
    requests = []
    for r in results:
        key = r.get("status", "OK").split()[0] if r.get("status") else "OK"
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
