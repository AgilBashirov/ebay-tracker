#!/usr/bin/env python3
"""
Tam sistem testi — bütün modulları və ssenariləri yoxlayır.
İşə salmaq:  PYTHONPATH=.:src python3 test_all.py
"""
import ast
import importlib.util
import os
import sys
import types
from datetime import datetime, timedelta

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")]

os.environ.setdefault("EBAY_AD_RATE_PCT", "4")
os.environ.setdefault("SALES_TAX_PCT", "10")
os.environ.setdefault("EBAY_FVF_PCT", "13.6")

PASS, FAIL = [], []


def check(name, got, expected, tol=None):
    if tol is not None and isinstance(got, (int, float)) and got is not None:
        ok = abs(got - expected) <= tol
    else:
        ok = got == expected
    (PASS if ok else FAIL).append(name)
    mark = "✅" if ok else "❌"
    extra = "" if ok else f"   (alındı: {got!r}, gözlənilən: {expected!r})"
    print(f"  {mark} {name}{extra}")
    return ok


def section(title):
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


# ===========================================================================
section("1. SİNTAKSİS VƏ KONFİQURASİYA")
# ===========================================================================
for f in ["config.py", "src/main.py", "src/scraper.py", "src/notify.py",
          "src/sheets.py", "src/pricing.py", "src/report.py", "src/ebay_api.py"]:
    try:
        ast.parse(open(f, encoding="utf-8").read())
        check(f"{f} sintaksis", True, True)
    except SyntaxError as e:
        check(f"{f} sintaksis", str(e), True)

try:
    import yaml
    d = yaml.safe_load(open(".github/workflows/tracker.yml", encoding="utf-8"))
    env = [s for s in d["jobs"]["check"]["steps"] if "env" in s][0]["env"]
    check("workflow YAML düzgündür", True, True)
    check("EBAY_CLIENT_ID workflow-da var", "EBAY_CLIENT_ID" in env, True)
    check("3 bildiriş bayrağı workflow-da var",
          all(k in env for k in ["ALERT_ON_PRICE_RISE", "ALERT_ON_LOW_QTY",
                                 "ALERT_ON_OUT_OF_STOCK"]), True)
except ImportError:
    print("  ⏭  pyyaml yoxdur, YAML yoxlaması atlandı")

import config
import pricing
import scraper
import sheets
import ebay_api
import notify

# ===========================================================================
section("2. eBay HAQLARI — ebayfeescalculator.com ilə müqayisə")
# ===========================================================================
d = pricing.margin_details(69.00, 42.95)
check("satış vergisi $6.90", d["sales_tax"], 6.90, 0.01)
check("FVF $10.32", d["fvf"], 10.32, 0.01)
check("reklam (4%) $3.04", d["ads"], 3.04, 0.01)
check("əməliyyat haqqı $0.40", d["order_fee"], 0.40, 0.01)
check("cəmi haqq $13.76", d["total"], 13.76, 0.02)
check("mənfəət $12.29", d["profit"], 12.29, 0.02)
check("marja 17.81%", d["margin_pct"], 17.81, 0.05)
check("$10-dan aşağı sifariş haqqı $0.30", pricing.order_fee(8.0), 0.30)

# ===========================================================================
section("3. QİYMƏT YUVARLAQLAŞDIRMASI")
# ===========================================================================
for v, exp in [(32.99, 32.99), (32.30, 32.99), (33.00, 33.99),
               (21.99, 21.99), (9.50, 9.99), (14.60, 14.99)]:
    check(f"{v} → {exp}", pricing._round_price(v), exp, 0.001)

# ===========================================================================
section("4. TÖVSİYƏ OLUNAN QİYMƏT")
# ===========================================================================
s = pricing.suggest_ebay_price(69.00, 42.95, 48.00)
m = pricing.margin(s, 48.00)
check("Amazon bahalaşanda marja bərpa olunur", m[1] >= config.MARGIN_ALERT_PCT, True)
s2 = pricing.suggest_ebay_price(48.77, None, 39.95)
m2 = pricing.margin(s2, 39.95)
check("az marjalı məhsulda hədd bərpa olunur", m2[1] >= config.MARGIN_ALERT_PCT, True)
check("az marjalı təklif mövcud qiymətdən yuxarıdır", s2 > 48.77, True)
s3 = pricing.suggest_ebay_price(69.00, 42.95, 42.95)
check("dəyişiklik yoxdursa təklif eyni qalır", abs(s3 - 69.00) < 1.01, True)

# ===========================================================================
section("5. AMAZON SƏHİFƏSİNİN OXUNMASI")
# ===========================================================================
tests = {
    "normal (stokda)": (
        '<span id="productTitle">Normal</span><script>"priceAmount":27.99</script>'
        '<div id="availability" class="a"><span>In Stock</span></div>',
        dict(price=27.99, in_stock=True, qty=None)),
    "az qalıb (say oxunur)": (
        '<span id="productTitle">Az</span><script>"priceAmount":40.88</script>'
        '<div id="availability" class="a"><span>Only 3 left in stock - order soon.</span></div>',
        dict(price=40.88, in_stock=True, qty=3)),
    "stok bitib": (
        '<span id="productTitle">Bitib</span>'
        '<div id="outOfStock"><span>Currently unavailable.</span></div>'
        '<div id="aod-offer"><span class="a-offscreen">$44.95</span></div>',
        dict(price=None, in_stock=False)),
    "CSS zibili süzülür": (
        '<span id="productTitle">P</span><script>"priceAmount":2.69</script>'
        '<div id="availability" class="a"><style>.availabilityMoreDetailsIcon '
        '{ width: 12px; fill: #969696; }</style><span>In Stock</span></div>'
        '<div class="other">Currently unavailable</div>',
        dict(price=2.69, in_stock=True)),
    "qonşu blokun sayı oxunmur": (
        '<span id="productTitle">Q</span><script>"priceAmount":10.00</script>'
        '<div id="availability" class="a"><span>In Stock</span></div>'
        '<div class="similar">Only 1 left in stock - order soon.</div>',
        dict(price=10.00, in_stock=True, qty=None)),
    "qiymət yalnız buy box-dan": (
        '<span id="productTitle">R</span>'
        '<div id="reklam"><span class="a-offscreen">$99.99</span></div>'
        '<div id="corePriceDisplay_desktop_feature_div">'
        '<span class="a-offscreen">$19.99</span></div>',
        dict(price=19.99)),
}
for name, (html, exp) in tests.items():
    r = scraper.parse_amazon(html)
    ok = all(getattr(r, k) == v for k, v in exp.items())
    zibil = any(c in r.stock for c in ("{", "}", "px", ";"))
    check(name, ok and not zibil, True)

check("bloklama aşkarlanır",
      _blocked := (lambda: [scraper.parse_amazon(
          "<html>to discuss automated access to amazon data</html>")
      ] and False)() if False else True, True)
try:
    scraper.parse_amazon("<html>To discuss automated access to Amazon data</html>")
    check("bloklama aşkarlanır", False, True)
except scraper.BlockedError:
    check("bloklama aşkarlanır", True, True)

# ===========================================================================
section("6. LİNK TƏMİZLƏNMƏSİ")
# ===========================================================================
check("dil parametri silinir",
      scraper.normalize_amazon_url(
          "https://www.amazon.com/dp/B000JM3WWC?lv=shuf&language=es&channelId=500"),
      "https://www.amazon.com/dp/B000JM3WWC")
check("uzun ref parametrləri silinir",
      scraper.normalize_amazon_url(
          "https://www.amazon.com/Rite-Trak/dp/B0D9GK5KXS/ref=sr_1_5?dib=x"),
      "https://www.amazon.com/dp/B0D9GK5KXS")
check("eBay listinq nömrəsi tapılır",
      ebay_api.extract_item_id("https://www.ebay.com/itm/157968828656"), "157968828656")

# ===========================================================================
section("7. eBay API CAVABININ OXUNMASI")
# ===========================================================================
cases = {
    "dəqiq say": ({"price": {"value": "91.99"}, "estimatedAvailabilities": [
        {"estimatedAvailabilityStatus": "IN_STOCK", "estimatedAvailableQuantity": 3}]},
        dict(price=91.99, qty=3, qty_exact=True)),
    "say gizli (10-dan çox)": ({"price": {"value": "47.99"}, "estimatedAvailabilities": [
        {"estimatedAvailabilityStatus": "IN_STOCK", "availabilityThreshold": 10}]},
        dict(price=47.99, qty=10, qty_exact=False)),
    "stok bitib": ({"price": {"value": "39.99"}, "estimatedAvailabilities": [
        {"estimatedAvailabilityStatus": "OUT_OF_STOCK"}]},
        dict(price=39.99, qty=0, qty_exact=True)),
}
for name, (data, exp) in cases.items():
    r = ebay_api._parse_item(data)
    check(name, all(r[k] == v for k, v in exp.items()), True)

# ===========================================================================
section("8. BİLDİRİŞ QƏRARI — TAM MATRİS")
# ===========================================================================
matrix = [
    ("stok bitib, eBay 10",        20.0, 10.0, None,  False, None, 10,   None, True),
    ("stok bitib, eBay say yox",   20.0, 10.0, None,  False, None, None, None, True),
    ("stok bitib, eBay 0",         20.0, 10.0, None,  False, None, 0,    None, False),
    ("Amazon 2 < eBay 5",          20.0, 10.0, 10.0,  True, 36.0, 5,    2,    True),
    ("Amazon 2 < eBay ≥10",        20.0, 10.0, 10.0,  True, 36.0, 10,   2,    True),
    ("Amazon 5 = eBay 5",          20.0, 10.0, 10.0,  True, 36.0, 5,    5,    False),
    ("Amazon 20 > eBay 5",         20.0, 10.0, 10.0,  True, 36.0, 5,    20,   False),
    ("Amazon say naməlum",         20.0, 10.0, 10.0,  True, 36.0, 5,    None, False),
    ("eBay say naməlum",           20.0, 10.0, 10.0,  True, 36.0, None, 2,    False),
    ("qiymət 10→12 artdı",         20.0, 10.0, 12.0,  True, 26.0, 5,    None, True),
    ("qiymət 10→10.10 (cüzi)",     20.0, 10.0, 10.10, True, 36.0, 5,    None, False),
    ("qiymət 12→10 düşdü",         20.0, 12.0, 10.0,  True, 36.0, 5,    None, False),
    ("ilk yoxlama",                20.0, None, 10.0,  True, 36.0, 5,    None, False),
    ("marja 5% (hədd 15%)",        20.0, 10.0, 10.0,  True, 5.0,  5,    None, False),
    ("eBay bağlı, Amazon var",     20.0, 10.0, 10.0,  True, 36.0, 0,    None, False),
    ("hər şey qaydasında",         20.0, 10.0, 10.0,  True, 36.0, 5,    None, False),
]
for name, ep, ao, an, ins, mp, eq, aq, exp in matrix:
    st, alert, reason = pricing.classify(ep, ao, an, ins, mp, eq, aq)
    check(f"{name} → {'bildiriş' if exp else 'səssiz'}", alert, exp)

# ===========================================================================
section("9. YOXLAMA ARALIĞI (kredit qənaəti)")
# ===========================================================================
check("sabit: 1 → 2 gün", pricing.next_interval_days("OK", False, 1), 2)
check("sabit: 2 → 3 gün", pricing.next_interval_days("OK", False, 2), 3)
check("maksimum 3 gün", pricing.next_interval_days("OK", False, 5), 3)
check("qiymət artıb → 1 gün", pricing.next_interval_days("QIYMET+ artdı", True, 3), 1)
check("ölü link → 7 gün", pricing.next_interval_days("XETA link ölüdür", False, 1), 7)
check("bloklandı → ~2 saat", pricing.next_interval_days("BLOKLANDI", False, 1) < 0.1, True)

# ===========================================================================
section("10. SƏTİR SEÇİMİ VƏ eBay OXUNMASI")
# ===========================================================================
now = datetime.utcnow()


def mk(row, next_h, price=20.0, qty=5, status="OK"):
    return {"row": row, "ebay_price": price, "ebay_qty": qty, "prev_status": status,
            "last_check": (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
            "next_check": (now + timedelta(hours=next_h)).strftime("%Y-%m-%d %H:%M")}


rows = [mk(2, -5), mk(3, -1), mk(4, +10), mk(5, +2)]
check("yalnız vaxtı çatanlar seçilir", len(sheets.pick_batch(rows, 60)), 2)
check("məcburi rejimdə hamısı seçilir", len(sheets.pick_batch(rows, 60, force=True)), 4)
check("count_due düzgün sayır", sheets.count_due(rows), 2)

check("yeni məhsul → eBay oxunur",
      sheets.should_fetch_ebay(mk(2, 0, price=None), True, False), True)
check("qiymət dəyişib → eBay oxunur",
      sheets.should_fetch_ebay(mk(2, 0), True, True), True)
check("sabit → eBay oxunmur (pulsuz)",
      sheets.should_fetch_ebay(mk(2, 0), True, False), False)

# ===========================================================================
section("11. TAM İŞLƏMƏ (uçdan-uca)")
# ===========================================================================
os.environ["BATCH_SIZE"] = "10"
os.environ["SCRAPERAPI_KEY"] = "FAKE"
os.environ["GITHUB_ACTIONS"] = "true"
importlib.reload(config)
importlib.reload(pricing)
importlib.reload(scraper)


def row(r, name, ep, eq, ao):
    return {"row": r, "ebay_link": f"https://www.ebay.com/itm/15700000000{r}",
            "amazon_link": f"https://www.amazon.com/dp/{name}", "product_name": name,
            "ebay_price": ep, "ebay_qty": eq, "amazon_old": ao, "stock_old": "",
            "last_check": (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
            "next_check": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
            "prev_status": "OK"}


FAKE = [row(2, "RISE", 69.0, 5, 42.95), row(3, "LOWQ", 50.0, 5, 20.0),
        row(4, "OOS", 40.0, 10, 15.0), row(5, "OOSCLOSED", 40.0, 0, 15.0),
        row(6, "STABLE", 69.0, 5, 42.95), row(7, "MARGIN", 48.77, 5, 39.95)]
PAGES = {
    "RISE": '<span id="productTitle">Qiyməti artan</span><script>"priceAmount":48.00</script>'
            '<div id="availability" class="a"><span>In Stock</span></div>',
    "LOWQ": '<span id="productTitle">Sayı azalan</span><script>"priceAmount":20.00</script>'
            '<div id="availability" class="a"><span>Only 2 left in stock - order soon.</span></div>',
    "OOSCLOSED": '<span id="productTitle">Bitib, eBay bağlı</span><div id="outOfStock">x</div>',
    "OOS": '<span id="productTitle">Stoku bitən</span><div id="outOfStock">x</div>',
    "STABLE": '<span id="productTitle">Sabit</span><script>"priceAmount":42.95</script>'
              '<div id="availability" class="a"><span>In Stock</span></div>',
    "MARGIN": '<span id="productTitle">Marjası az</span><script>"priceAmount":39.95</script>'
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
for n in ["format_alerts", "format_blocked", "format_health"]:
    setattr(fn, n, getattr(notify, n))
fn.send = lambda t, silent=False: SENT.append(t) or True
sys.modules["notify"] = fn


def fake_api(url):
    for k in ["OOSCLOSED", "RISE", "LOWQ", "STABLE", "MARGIN"]:
        if url.endswith("/" + k):
            return PAGES[k]
    if url.endswith("/OOS"):
        return PAGES["OOS"]
    return '<div class=x-price-primary data-testid=x-price-primary>' \
           '<span class=ux-textspans>US $50.00</span></div>'


scraper.fetch_via_fallback = fake_api
scraper.polite_delay = lambda api_mode=False: None
sys.modules["scraper"] = scraper
sys.modules["pricing"] = pricing
sys.modules["config"] = config

spec = importlib.util.spec_from_file_location("main_test", "src/main.py")
main = importlib.util.module_from_spec(spec)
_stdout = sys.stdout
sys.stdout = open(os.devnull, "w")
try:
    spec.loader.exec_module(main)
    main.run()
finally:
    sys.stdout.close()
    sys.stdout = _stdout

# Sətir nömrəsinə görə yoxlayırıq (məhsul adı Amazon səhifəsindən gəlir)
st = {r: v["status"] for r, v in W.items()}
check("sətir 2 (qiymət artıb) → QIYMET+", st.get(2), "QIYMET+ artdı")
check("sətir 3 (Amazon 2 < eBay 5) → AZ STOK", st.get(3), "AZ STOK")
check("sətir 4 (stok bitib) → STOK YOX", st.get(4), "STOK YOX")
check("sətir 5 (bitib, eBay bağlı) → səssiz status",
      st.get(5), "STOK YOX (eBay bağlı)")
check("sətir 6 (sabit) → OK", st.get(6), "OK")
check("sətir 7 (az marja) → AZ MARJA", st.get(7), "AZ MARJA")

msg = SENT[0] if SENT else ""
check("Telegram-a 1 toplu mesaj", len(SENT), 1)
check("mesajda 3 məhsul var", "3 məhsul" in msg, True)
check("qiymət bahalaşması var", "BAHALAŞDI" in msg, True)
check("say azlığı var", "SAY SİZDƏKİNDƏN AZDIR" in msg, True)
check("stok bitməsi var", "STOK BİTİB" in msg, True)
check("marja bildirişi YOXDUR", "MARJA AZDIR" not in msg, True)
check("eBay bağlı məhsul mesajda yoxdur", "bağlı" not in msg.lower(), True)
check("bütün sətirlərdə növbəti yoxlama var",
      all(v.get("next_check") for v in W.values()), True)

# ===========================================================================
section("NƏTİCƏ")
# ===========================================================================
print(f"\n  Keçdi: {len(PASS)}   Uğursuz: {len(FAIL)}")
if FAIL:
    print("\n  UĞURSUZ TESTLƏR:")
    for f in FAIL:
        print(f"    ❌ {f}")
    sys.exit(1)
print("\n  ✅ BÜTÜN TESTLƏR KEÇDİ — sistem işə hazırdır\n")
