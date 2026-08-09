#!/usr/bin/env python3
"""
Avtomatik say sıfırlamasının testi.
Real eBay-ə HEÇ BİR sorğu getmir — bütün cavablar saxtadır.

İşə salmaq:  PYTHONPATH=.:src python3 test_auto.py
"""
import importlib
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [ROOT, os.path.join(ROOT, "src")]

os.environ.update({
    "EBAY_CLIENT_ID": "FAKE", "EBAY_CLIENT_SECRET": "FAKE",
    "EBAY_DEV_ID": "FAKE", "EBAY_AUTH_TOKEN": "FAKE",
    "SCRAPERAPI_KEY": "FAKE", "GITHUB_ACTIONS": "true",
    "AUTO_ZERO_QTY": "1", "BATCH_SIZE": "10",
})

PASS, FAIL = [], []


def check(name, got, expected):
    ok = got == expected
    (PASS if ok else FAIL).append(name)
    print(f"  {'✅' if ok else '❌'} {name}"
          + ("" if ok else f"   (alındı: {got!r}, gözlənilən: {expected!r})"))


def section(t):
    print(f"\n{'=' * 72}\n{t}\n{'=' * 72}")


import config
import ebay_write

# ===========================================================================
section("1. QORUYUCULAR — heç bir sorğu getməməli olan hallar")
# ===========================================================================
SENT_CALLS = []


def fake_call(call_name, inner):
    SENT_CALLS.append(call_name)
    return True, "<Ack>Success</Ack>"


ebay_write._call = fake_call

cases = [
    ("Out of Stock Control AKTİV DEYİL", False, 5, False, False,
     "'Out of Stock Control' ayarı eBay-də AKTİV DEYİL"),
    ("ayar öyrənilə bilmədi", None, 5, False, False,
     "ayarın vəziyyəti öyrənilə bilmədi"),
    ("say onsuz da 0-dır", True, 0, False, False, "say onsuz da 0-dır"),
    ("listinq nömrəsi yoxdur", True, 5, False, False, "listinq nömrəsi tapılmadı"),
]
for name, pref, qty, dry, exp_done, exp_skip in cases:
    ebay_write._oos_pref_cache.update({"checked": True, "enabled": pref})
    SENT_CALLS.clear()
    item = "" if "nömrəsi yoxdur" in name else "157968828656"
    r = ebay_write.zero_out(item, qty, dry_run=dry)
    check(f"{name} → icra olunmur", r["done"], exp_done)
    check(f"{name} → səbəb yazılır", r["skipped"], exp_skip)
    check(f"{name} → eBay-ə sorğu getmir",
          "ReviseInventoryStatus" in SENT_CALLS, False)

# ===========================================================================
section("2. QURU REJİM — yazır, amma dəyişmir")
# ===========================================================================
ebay_write._oos_pref_cache.update({"checked": True, "enabled": True})
SENT_CALLS.clear()
r = ebay_write.zero_out("157968828656", 50, dry_run=True)
check("quru rejimdə icra olunmur", r["done"], False)
check("quru rejimdə eBay-ə sorğu getmir",
      "ReviseInventoryStatus" in SENT_CALLS, False)
check("quru rejimdə nə ediləcəyi yazılır",
      "say 0 ediləcəkdi" in r["message"], True)

# ===========================================================================
section("3. REAL REJİM — hər şey qaydasındadırsa icra olunur")
# ===========================================================================
SENT_CALLS.clear()
r = ebay_write.zero_out("157968828656", 50, dry_run=False)
check("icra olundu", r["done"], True)
check("eBay-ə ReviseInventoryStatus getdi",
      "ReviseInventoryStatus" in SENT_CALLS, True)

# eBay xəta qaytararsa
ebay_write._call = lambda c, i: (False, "Auth token is invalid")
r = ebay_write.zero_out("157968828656", 50, dry_run=False)
check("eBay xətası düzgün oxunur", r["done"], False)
check("xəta mətni saxlanılır", "Auth token is invalid" in r["skipped"], True)
ebay_write._call = fake_call

# ===========================================================================
section("4. XML SORĞUSUNUN DÜZGÜNLÜYÜ")
# ===========================================================================
CAPTURED = {}


def capture(call_name, inner):
    CAPTURED["call"] = call_name
    CAPTURED["inner"] = inner
    return True, "<Ack>Success</Ack>"


ebay_write._call = capture
ebay_write.zero_out("157968828656", 50, dry_run=False)
check("çağırış adı doğrudur", CAPTURED["call"], "ReviseInventoryStatus")
check("listinq nömrəsi XML-dədir",
      "<ItemID>157968828656</ItemID>" in CAPTURED["inner"], True)
check("say 0 göndərilir", "<Quantity>0</Quantity>" in CAPTURED["inner"], True)
ebay_write._call = fake_call

# ===========================================================================
section("5. TAM AXIN — hansı məhsula toxunulur?")
# ===========================================================================
import ebay_api
import notify
import pricing
import scraper
import sheets

now = datetime.utcnow()


def row(r, key, auto, qty):
    return {"row": r, "ebay_link": f"https://www.ebay.com/itm/15700000000{r}",
            "amazon_link": f"https://www.amazon.com/dp/{key}", "product_name": key,
            "ebay_price": 40.0, "ebay_qty": qty, "amazon_old": 15.0, "stock_old": "",
            "last_check": (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
            "next_check": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
            "prev_status": "OK", "auto": auto}


FAKE = [
    row(2, "OOS_ICAZE", "beli", 50),      # stok bitib + icazə var  → toxunulur
    row(3, "OOS_ICAZESIZ", "", 50),        # stok bitib, icazə YOX   → toxunulmur
    row(4, "STOKDA_ICAZE", "beli", 50),    # stokdadır + icazə var   → toxunulmur
]
PAGES = {
    "OOS_ICAZE": '<span id="productTitle">Stoku bitib (icazə var)</span>'
                 '<div id="outOfStock">x</div>',
    "OOS_ICAZESIZ": '<span id="productTitle">Stoku bitib (icazəsiz)</span>'
                    '<div id="outOfStock">x</div>',
    "STOKDA_ICAZE": '<span id="productTitle">Stokda (icazə var)</span>'
                    '<script>"priceAmount":15.00</script>'
                    '<div id="availability" class="a"><span>In Stock</span></div>',
}

W, SENT = {}, []
fs = types.ModuleType("sheets")
fs.open_sheet = lambda: "WS"
fs.ensure_structure = lambda w: True
fs.read_rows = lambda w: FAKE
for n in ["pick_batch", "count_due", "should_fetch_ebay",
          "needs_ebay_refresh", "previous_interval_days"]:
    setattr(fs, n, getattr(sheets, n))
fs.write_results = lambda w, res: [W.__setitem__(x["row"], x) for x in res]
sys.modules["sheets"] = fs

fn = types.ModuleType("notify")
for n in ["format_alerts", "format_blocked", "format_health", "format_auto_actions"]:
    setattr(fn, n, getattr(notify, n))
fn.send = lambda t, silent=False: SENT.append(t) or True
sys.modules["notify"] = fn

scraper.fetch_via_fallback = lambda url, skip_first=False: next(
    (v for k, v in PAGES.items() if url.endswith("/" + k)), "<html>Page Not Found</html>")
scraper.polite_delay = lambda api_mode=False: None
ebay_api.fetch_item = lambda url: None          # eBay API-ni söndürürük
ebay_api.is_configured = lambda: False
scraper.scrape_ebay_info = lambda b, u, api_mode=False: {"price": None, "qty": None}

TOUCHED = []
ebay_write._oos_pref_cache.update({"checked": True, "enabled": True})
_orig = ebay_write.zero_out


def spy(item_id, qty, dry_run):
    TOUCHED.append(item_id)
    return _orig(item_id, qty, dry_run)


ebay_write.zero_out = spy
sys.modules["ebay_write"] = ebay_write

spec = importlib.util.spec_from_file_location("main_auto", os.path.join(ROOT, "src/main.py"))
main = importlib.util.module_from_spec(spec)
_out = sys.stdout
sys.stdout = open(os.devnull, "w")
try:
    spec.loader.exec_module(main)
    main.run()
finally:
    sys.stdout.close()
    sys.stdout = _out

check("stok bitib + icazə var → toxunuldu", len(TOUCHED), 1)
check("icazəsiz məhsula toxunulmadı",
      all("3" not in (t or "")[-2:] for t in TOUCHED), True)
check("stokda olan məhsula toxunulmadı",
      all("4" not in (t or "")[-2:] for t in TOUCHED), True)

auto_msg = next((m for m in SENT if "QURU REJİM" in m or "avtomatik" in m.lower()), "")
check("Telegram-a hesabat göndərildi", bool(auto_msg), True)
check("hesabatda quru rejim yazılıb", "QURU REJİM" in auto_msg, True)

print("\n  --- Telegram mesajı ---")
for line in auto_msg.replace("<b>", "").replace("</b>", "") \
        .replace("<i>", "").replace("</i>", "").split("\n"):
    print("  " + line)

# ===========================================================================
section("NƏTİCƏ")
# ===========================================================================
print(f"\n  Keçdi: {len(PASS)}   Uğursuz: {len(FAIL)}")
if FAIL:
    print("\n  UĞURSUZ:")
    for f in FAIL:
        print(f"    ❌ {f}")
    sys.exit(1)
print("\n  ✅ AVTOMATİK SIFIRLAMA TESTLƏRİ KEÇDİ\n")
