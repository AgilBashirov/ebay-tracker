"""
eBay listinqinə YAZMA əməliyyatları (Trading API).

HAZIRDA YALNIZ BİR ƏMƏLİYYAT: Amazon-da stok bitəndə eBay sayını 0 etmək.

TƏHLÜKƏSİZLİK QATLARI (səhv bahalı olduğu üçün):
  1. Quru rejim (AUTO_DRY_RUN=1) — defolt. Nə edəcəyini yazır, dəyişmir.
  2. Sətir üzrə icazə — sheet-dəki "Avto" sütununda icazə verilməyibsə toxunmur.
  3. "Out of Stock Control" yoxlaması — eBay-də bu ayar aktiv deyilsə sayı
     sıfırlamaq listinqi BAĞLAYIR və tarixçə itir. Ayar aktiv deyilsə
     əməliyyat icra olunmur.
  4. Yalnız birmənalı siqnal — Amazon-un `outOfStock` bloku təsdiqlənəndə.
  5. Say onsuz da 0-dırsa sorğu göndərilmir.

Sənəd: developer.ebay.com/Devzone/XML/docs/Reference/eBay/ReviseInventoryStatus.html
"""
import re
import urllib.error
import urllib.request

import config

TRADING_URL = "https://api.ebay.com/ws/api.dll"
COMPAT_LEVEL = "1193"
SITE_ID = "0"  # 0 = eBay US

_oos_pref_cache = {"checked": False, "enabled": None}


def is_configured() -> bool:
    return bool(config.EBAY_AUTH_TOKEN and config.EBAY_DEV_ID
                and config.EBAY_CLIENT_ID and config.EBAY_CLIENT_SECRET)


def _call(call_name: str, inner_xml: str) -> tuple[bool, str]:
    """Trading API çağırışı. (uğurlu?, cavab mətni) qaytarır."""
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<{call_name}Request xmlns="urn:ebay:apis:eBLBaseComponents">'
        f'<RequesterCredentials><eBayAuthToken>{config.EBAY_AUTH_TOKEN}'
        '</eBayAuthToken></RequesterCredentials>'
        f'{inner_xml}'
        f'</{call_name}Request>'
    ).encode()

    req = urllib.request.Request(
        TRADING_URL,
        data=body,
        headers={
            "X-EBAY-API-CALL-NAME": call_name,
            "X-EBAY-API-SITEID": SITE_ID,
            "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT_LEVEL,
            "X-EBAY-API-DEV-NAME": config.EBAY_DEV_ID,
            "X-EBAY-API-APP-NAME": config.EBAY_CLIENT_ID,
            "X-EBAY-API-CERT-NAME": config.EBAY_CLIENT_SECRET,
            "Content-Type": "text/xml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=40) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode(errors='ignore')[:200]}"
    except Exception as e:
        return False, str(e)

    ack = (re.search(r"<Ack>(\w+)</Ack>", text) or [None, ""])[1]
    if ack in ("Success", "Warning"):
        return True, text
    err = re.search(r"<LongMessage>(.*?)</LongMessage>", text, re.S)
    return False, (err.group(1).strip() if err else text[:200])


def out_of_stock_control_enabled() -> bool | None:
    """
    eBay-də "Out of Stock Control" ayarının vəziyyəti.

    True  -> sayı 0 etmək təhlükəsizdir (listinq sağ qalır, tarixçə qorunur)
    False -> sayı 0 etmək listinqi BAĞLAYIR — əməliyyat icra olunmamalıdır
    None  -> öyrənilə bilmədi (ehtiyatlı davranırıq, icra etmirik)
    """
    if _oos_pref_cache["checked"]:
        return _oos_pref_cache["enabled"]

    _oos_pref_cache["checked"] = True
    ok, text = _call(
        "GetUserPreferences",
        "<ShowOutOfStockControlPreference>true</ShowOutOfStockControlPreference>",
    )
    if not ok:
        print(f"[ebay_write] Ayar oxuna bilmədi: {text}")
        _oos_pref_cache["enabled"] = None
        return None

    m = re.search(r"<OutOfStockControlPreference>(\w+)</OutOfStockControlPreference>",
                  text)
    enabled = (m.group(1).lower() == "true") if m else None
    _oos_pref_cache["enabled"] = enabled
    return enabled


def set_quantity(item_id: str, quantity: int) -> tuple[bool, str]:
    """Listinqin sayını dəyişir (ReviseInventoryStatus)."""
    inner = (
        "<InventoryStatus>"
        f"<ItemID>{item_id}</ItemID>"
        f"<Quantity>{int(quantity)}</Quantity>"
        "</InventoryStatus>"
    )
    return _call("ReviseInventoryStatus", inner)


def zero_out(item_id: str, current_qty: int | None, dry_run: bool) -> dict:
    """
    Listinqin sayını 0 edir. Bütün qoruyucular burada yoxlanılır.

    Qaytarır: {"done": bool, "skipped": str|None, "message": str}
    """
    if not item_id:
        return {"done": False, "skipped": "listinq nömrəsi tapılmadı", "message": ""}

    if current_qty is not None and current_qty <= 0:
        return {"done": False, "skipped": "say onsuz da 0-dır", "message": ""}

    pref = out_of_stock_control_enabled()
    if pref is not True:
        reason = ("'Out of Stock Control' ayarı eBay-də AKTİV DEYİL"
                  if pref is False else "ayarın vəziyyəti öyrənilə bilmədi")
        return {"done": False, "skipped": reason, "message": ""}

    if dry_run:
        return {"done": False, "skipped": None,
                "message": f"[QURU REJİM] {item_id} → say 0 ediləcəkdi"}

    ok, msg = set_quantity(item_id, 0)
    if ok:
        return {"done": True, "skipped": None, "message": f"{item_id} → say 0"}
    return {"done": False, "skipped": f"eBay xətası: {msg}", "message": ""}
