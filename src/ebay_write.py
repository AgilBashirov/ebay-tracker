"""
eBay listinqinə YAZMA əməliyyatları (Trading API).

ƏMƏLİYYATLAR:
  • Sayın dəyişdirilməsi (0 = satışdan çıxarmaq, listinq sağ qalır)
  • Qiymətin dəyişdirilməsi
Hər ikisi bir sorğuda gedə bilir (ReviseInventoryStatus).

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


def revise(item_id: str, quantity: int | None = None,
           price: float | None = None) -> tuple[bool, str]:
    """
    Say və/və ya qiyməti bir sorğuda dəyişir (ReviseInventoryStatus).
    İkisini birlikdə göndərmək bir sorğuya qənaət edir (eBay Trading API-nin
    gündəlik çağırış limiti var — developer.ebay.com panelində görünür).
    """
    parts = [f"<ItemID>{item_id}</ItemID>"]
    if quantity is not None:
        parts.append(f"<Quantity>{int(quantity)}</Quantity>")
    if price is not None:
        parts.append(f"<StartPrice>{float(price):.2f}</StartPrice>")
    if len(parts) == 1:
        return False, "dəyişdiriləcək heç nə göstərilmədi"
    inner = "<InventoryStatus>" + "".join(parts) + "</InventoryStatus>"
    return _call("ReviseInventoryStatus", inner)


def set_quantity(item_id: str, quantity: int) -> tuple[bool, str]:
    """Yalnız sayı dəyişir (geriyə uyğunluq)."""
    return revise(item_id, quantity=quantity)


def set_price(item_id: str, price: float) -> tuple[bool, str]:
    """Yalnız qiyməti dəyişir."""
    return revise(item_id, price=price)


def apply_changes(item_id: str, current_qty: int | None, current_price: float | None,
                  new_qty: int | None, new_price: float | None,
                  dry_run: bool) -> dict:
    """
    Bir listinqdə say və/və ya qiyməti dəyişir. Bütün qoruyucular buradadır.

    Qaytarır:
      {"done": bool, "skipped": str|None, "message": str,
       "qty_before","qty_after","price_before","price_after"}
    """
    res = {"done": False, "skipped": None, "message": "",
           "qty_before": current_qty, "qty_after": None,
           "price_before": current_price, "price_after": None}

    if not item_id:
        res["skipped"] = "listinq nömrəsi tapılmadı"
        return res

    # --- Say: dəyişməyibsə göndərmirik ---
    if new_qty is not None and current_qty is not None and int(new_qty) == int(current_qty):
        new_qty = None

    # --- Qiymət: dəyişməyibsə göndərmirik ---
    if (new_price is not None and current_price is not None
            and abs(new_price - current_price) < 0.01):
        new_price = None

    if new_qty is None and new_price is None:
        res["skipped"] = "dəyişiklik lazım deyil"
        return res

    # --- Sayı 0 etmək yalnız "Out of Stock Control" aktivdirsə ---
    # Ayar bağlı olanda 0 qoymaq listinqi BAĞLAYIR və satış tarixçəsi itir.
    if new_qty is not None and int(new_qty) == 0:
        pref = out_of_stock_control_enabled()
        if pref is not True:
            reason = ("'Multi-quantity listings' ayarı eBay-də AKTİV DEYİL"
                      if pref is False else "ayarın vəziyyəti öyrənilə bilmədi")
            if new_price is None:
                res["skipped"] = reason
                return res
            # Qiyməti dəyişə bilərik, sayı yox
            new_qty = None
            res["skipped"] = f"say dəyişmədi ({reason})"

    if new_price is not None and float(new_price) <= 0:
        res["skipped"] = "qiymət sıfır və ya mənfi ola bilməz"
        return res

    parts = []
    if new_qty is not None:
        parts.append(f"say {current_qty} → {new_qty}")
    if new_price is not None:
        parts.append(f"qiymət ${current_price:.2f} → ${new_price:.2f}"
                     if current_price else f"qiymət ${new_price:.2f}")
    summary = ", ".join(parts)

    if dry_run:
        res["message"] = f"[QURU REJİM] {summary}"
        return res

    ok, msg = revise(item_id, quantity=new_qty, price=new_price)
    if not ok:
        res["skipped"] = f"eBay xətası: {msg}"
        return res

    res["done"] = True
    res["qty_after"] = new_qty
    res["price_after"] = new_price
    res["message"] = summary
    return res


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

    ok, msg = revise(item_id, quantity=0)
    if ok:
        return {"done": True, "skipped": None, "message": f"{item_id} → say 0"}
    return {"done": False, "skipped": f"eBay xətası: {msg}", "message": ""}
