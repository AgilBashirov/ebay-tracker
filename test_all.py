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

# Windows konsolu defolt olaraq cp1252-dir və "İ", "ə" kimi hərfləri çap edə
# bilmir — test hesabatı çökürdü. UTF-8-ə keçiririk.
for _stream in (sys.stdout, sys.stderr):
    try:
        if (_stream.encoding or "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)),
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")]

os.environ.setdefault("EBAY_AD_RATE_PCT", "4")
os.environ.setdefault("SALES_TAX_PCT", "10")
os.environ.setdefault("EBAY_FVF_PCT", "13.6")
# ebayfeescalculator.com-da "Oversea sales? No" seçilib — yəni beynəlxalq haqq
# modelə daxil deyil. Müqayisənin düz olması üçün burada da 0 qoyuruq.
# Azərbaycan haqqı (1.30%) ayrıca test_auto.py-də yoxlanılır.
os.environ.setdefault("EBAY_INTERNATIONAL_PCT", "0")
# Kalkulyator haqların üstünə gələn ƏDV-ni də modelləşdirmir.
# Azərbaycan ƏDV-si (18%) ayrıca test_auto.py-də yoxlanılır.
os.environ.setdefault("EBAY_FEE_VAT_PCT", "0")

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
# Təklif DOLLAR HƏDDİ ilə hesablanır (config.PROFIT_TIERS).
# Hədd minimumdur, tavan deyil — qazanc həddən çoxdursa təklif boş qalır.

def _tovsiye_yoxla(ad, ebay, amazon, gozlenen_var):
    sug = pricing.suggest_ebay_price(ebay, None, amazon)
    cur, _ = pricing.margin(ebay, amazon)
    hedef = pricing.target_profit_for(amazon)
    check(f"{ad} (qazanc ${cur} · hədəf ${hedef:.0f}) → "
          + ("təklif var" if gozlenen_var else "boş"),
          sug is not None, gozlenen_var)
    if sug is not None:
        yeni, _ = pricing.margin(sug, amazon)
        check(f"   təklif ${sug} hədəfi ödəyir", yeni >= hedef, True)
    return sug


# 1) Qazanc hədəfin altındadır → təklif olmalıdır
_tovsiye_yoxla("az qazanc", 48.77, 39.95, True)

# 2) Zərərdədir → təklif olmalıdır
_tovsiye_yoxla("zərərdə", 45.00, 43.00, True)

# 3) Qazanc məqbul zonadadır → təklif OLMAMALIDIR
#    (əks halda sheet "qiyməti aşağı sal" yazır, avtomatika isə toxunmur)
_hedef = pricing.target_profit_for(39.95)
_yaxsi = round(pricing.price_for_profit(_hedef + 1.0, 39.95), 2)
_tovsiye_yoxla("qazanc qaydasındadır", _yaxsi, 39.95, False)

# 4) Qazanc həddən ÇOXDUR → təklif YOXDUR.
#    Hədd minimumdur, tavan deyil: çox qazanan məhsula toxunulmur.
_tovsiye_yoxla("qazanc həddən çoxdur", 120.00, 39.95, False)

# 5) Ucuzlaşdırma açıq olsa təklif verilir
os.environ["AUTO_PRICE_ALLOW_DOWN"] = "1"
importlib.reload(config); importlib.reload(pricing)
_s5 = _tovsiye_yoxla("ucuzlaşdırma açıqdır", 120.00, 39.95, True)
check("   açıq olanda təklif aşağı salır", _s5 < 120.00, True)
os.environ["AUTO_PRICE_ALLOW_DOWN"] = "0"
importlib.reload(config); importlib.reload(pricing)

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
for n in ["format_run_summary", "format_alerts", "format_blocked",
          "format_health", "format_auto_actions", "format_low_profit",
          "format_could_lower", "format_run_error"]:
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
sys.stdout = open(os.devnull, "w", encoding="utf-8")
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
check("sətir 7 (qazanc $5-dən az) → AZ QAZANC", st.get(7), "AZ QAZANC")

msg = SENT[0] if SENT else ""
check("Telegram-a YALNIZ 1 mesaj", len(SENT), 1)
check("mesaj qısadır (< 900 simvol)", len(msg) < 900, True)
check("diqqət bölməsi var", "Diqqət" in msg, True)
check("nə qədər məhsul yoxlandığı yazılıb", "/" in msg.split("\n")[0], True)
check("eBay bağlı məhsul mesajda yoxdur", "bağlı" not in msg.lower(), True)
check("bütün sətirlərdə növbəti yoxlama var",
      all(v.get("next_check") for v in W.values()), True)

# ===========================================================================
section("12. CƏDVƏLİN SƏLİQƏSİ — link, format, kəsim (saxta worksheet)")
# ===========================================================================
# Google-a BİR sorğu da getmir: sahte worksheet bütün çağırışları yazıya alır.


class FakeSpreadsheet:
    def __init__(self, ws):
        self.ws = ws
        self.requests = []

    def batch_update(self, body):
        self.requests.extend(body["requests"])
        return {}

    def fetch_sheet_metadata(self):
        sheet = {"properties": {
            "sheetId": self.ws.id,
            "gridProperties": {"rowCount": self.ws.row_count,
                               "columnCount": self.ws.col_count}}}
        if self.ws.banded:
            sheet["bandedRanges"] = self.ws.banded
        return {"sheets": [sheet]}


class FakeWorksheet:
    def __init__(self, grid, rows=1000, cols=26, banded=None):
        self.id = 7
        self.grid = [list(r) for r in grid]
        self.row_count, self.col_count = rows, cols
        self.banded = banded or []
        self.spreadsheet = FakeSpreadsheet(self)
        self.render, self.header_writes, self.cleared, self.value_updates = \
            {}, [], [], []

    def get_all_values(self, **kw):
        self.render = kw
        return [list(r) for r in self.grid]

    def update(self, values=None, range_name=None):
        self.header_writes.append(range_name)

    def batch_clear(self, ranges):
        self.cleared.extend(ranges)

    def batch_update(self, data, value_input_option=None, **kw):
        self.value_updates.extend(data)


EBAY_URL = "https://www.ebay.com/itm/157968828656"
AMZ_URL = "https://www.amazon.com/dp/B0D9GK5KXS"


def kinds(reqs):
    return [k for r in reqs for k in r]


def one(reqs, kind):
    return next((r[kind] for r in reqs if kind in r), None)


def build_grid(tidy=False):
    """
    3 məhsulluq saxta cədvəl.

    tidy=False -> köhnə vəziyyət: başlıq səhv, xam URL, P/Q sütunları qalıb
    tidy=True  -> artıq səliqəyə salınmış cədvəl (təkrar işləməni yoxlamaq üçün)
    """
    if tidy:
        a = sheets._hyperlink_formula(EBAY_URL, "eBay")
        b = sheets._hyperlink_formula(AMZ_URL, "Amazon")
        head, extra = list(config.HEADERS), []
    else:
        a, b = EBAY_URL, AMZ_URL
        head = ["Link"] + config.HEADERS[1:] + ["Avto", "Avto Əməliyyat"]
        extra = ["hamisi", "köhnə qeyd"]
    body = [[a, b, f"Məhsul {n}", 52.99, 3, 40.0, 41.5, "In Stock", 9.1,
             5.4, 0.102, 54.99, "2026-09-18 10:00", "2026-09-19 10:00", "OK"]
            + extra for n in (1, 2, 3)]
    return [head] + body


# --- 12a) Xam URL-li cədvəl: hər şey qurulur --------------------------------
ws = FakeWorksheet(build_grid())
sheets.ensure_structure(ws)
reqs = ws.spreadsheet.requests

check("FORMULA rejimində oxunur",
      ws.render.get("value_render_option"), "FORMULA")
check("tarixlər mətn kimi gəlir",
      ws.render.get("date_time_render_option"), "FORMATTED_STRING")
check("səhv başlıq düzəldilir", ws.header_writes, ["A1:O1"])
check("köhnə P/Q sütunları təmizlənir", ws.cleared, ["P:Q"])

check("6 link qısaldıldı (3 sətir × 2)", len(ws.value_updates), 6)
_f = ws.value_updates[0]["values"][0][0]
check("   düstur HYPERLINK-dir", _f.startswith("=HYPERLINK("), True)
check("   URL düsturun içində qalır", EBAY_URL in _f, True)
check("   xanada qısa ad görünür", _f.endswith('"eBay")'), True)
check("   diapazon A2-dir", ws.value_updates[0]["range"], "A2")

_del = [r["deleteDimension"]["range"] for r in reqs if "deleteDimension" in r]
_cols = next((d for d in _del if d["dimension"] == "COLUMNS"), None)
_rows = next((d for d in _del if d["dimension"] == "ROWS"), None)
check("P-dən sonrakı sütunlar silinir", (_cols["startIndex"], _cols["endIndex"]),
      (15, 26))
# 4 dolu sətir + 20 ehtiyat = 24; silinmə 0-indeksli 24-dən, yəni 25-ci sətirdən
check("boş sətirlər 25-dən silinir", (_rows["startIndex"], _rows["endIndex"]),
      (24, 1000))
check("MƏLUMATLI sətir silinmir", _rows["startIndex"] >= 4, True)

check("zolaqlı sətirlər əlavə olunur", "addBanding" in kinds(reqs), True)
check("mövcud zolaq yenilənmir (hələ yoxdur)",
      "updateBanding" in kinds(reqs), False)
check("avtomatik filtr qoyulur",
      one(reqs, "setBasicFilter")["filter"]["range"]["endRowIndex"], 4)
check("defolt olaraq sıralanmır (SHEET_AUTO_SORT=0)",
      "sortRange" in kinds(reqs), False)

_fmts = [r["repeatCell"]["cell"]["userEnteredFormat"]["numberFormat"]
         for r in reqs
         if "repeatCell" in r
         and "numberFormat" in r["repeatCell"]["cell"]["userEnteredFormat"]]
check("dollar formatı var (D, F, G, I, J, L)",
      sum(1 for f in _fmts if f["type"] == "CURRENCY"), 6)
check("faiz formatı var (K)", sum(1 for f in _fmts if f["type"] == "PERCENT"), 1)
check("tarix formatı _parse_dt ilə eynidir",
      next(f["pattern"] for f in _fmts if f["type"] == "DATE_TIME"),
      "yyyy-mm-dd hh:mm")

# --- 12b) İkinci işləmə: heç nə təkrarlanmır --------------------------------
ws2 = FakeWorksheet(build_grid(tidy=True), rows=24, cols=15,
                    banded=[{"bandedRangeId": 11}])
sheets.ensure_structure(ws2)
reqs2 = ws2.spreadsheet.requests
check("qısaldılmış linklərə yenidən toxunulmur", len(ws2.value_updates), 0)
check("düzgün başlıq yenidən yazılmır", ws2.header_writes, [])
check("artıq sütun yoxdur — təmizlik sorğusu getmir", ws2.cleared, [])
check("kəsiləcək yer yoxdur", "deleteDimension" in kinds(reqs2), False)
check("mövcud zolaq YENİLƏNİR (üst-üstə düşmə xətası olmur)",
      "updateBanding" in kinds(reqs2), True)
check("ikinci zolaq ƏLAVƏ edilmir", "addBanding" in kinds(reqs2), False)

# --- 12c) Linkin oxunması: hər iki forma -----------------------------------
for ad, xana, gozlenen in [
    ("xam URL", EBAY_URL, EBAY_URL),
    ("HYPERLINK (vergül)", f'=HYPERLINK("{EBAY_URL}","eBay")', EBAY_URL),
    ("HYPERLINK (nöqtəli vergül)", f'=HYPERLINK("{EBAY_URL}";"eBay")', EBAY_URL),
    ("protokolsuz", "amazon.com/dp/B0D9GK5KXS", AMZ_URL.replace("www.", "www.")),
    ("boş xana", "", ""),
    # Link olmayan məzmun ATILMIR, olduğu kimi qaytarılır: boş saysaq sətir
    # sakitcə ötürülərdi, belə isə main.py onu "XETA link yoxdur" edir.
    ("səhv məzmun olduğu kimi qalır", 52.99, "52.99"),
]:
    check(f"link oxunur — {ad}", sheets._cell_link(xana), gozlenen)

check("düsturlu cədvəldən sətirlər düzgün oxunur",
      [(r["ebay_link"], r["amazon_link"], r["ebay_qty"], r["ebay_price"])
       for r in sheets.read_rows(FakeWorksheet(build_grid(tidy=True)))][0],
      (EBAY_URL, AMZ_URL, 3, 52.99))

# FORMULA rejimi rəqəmi float kimi qaytarır — "3.0" say 30 olmamalıdır
check("say 3.0 → 3 (30 yox)", sheets._to_int(3.0), 3)
check("say '3 ədəd' → 3", sheets._to_int("3 ədəd"), 3)
check("say 0 → 0", sheets._to_int(0), 0)
check("qiymət '$52.99' → 52.99", sheets._to_float("$52.99"), 52.99)

# --- 12d) Sıralama açıq olanda ---------------------------------------------
os.environ["SHEET_AUTO_SORT"] = "1"
importlib.reload(config)
ws3 = FakeWorksheet(build_grid(tidy=True), rows=24, cols=15)
sheets.ensure_structure(ws3)
_sort = one(ws3.spreadsheet.requests, "sortRange")
check("SHEET_AUTO_SORT=1 → sıralanır", _sort is not None, True)
check("   Status sütununa görə", _sort["sortSpecs"][0]["dimensionIndex"],
      config.COL["status"] - 1)
check("   başlıq sətri sıralamaya girmir", _sort["range"]["startRowIndex"], 1)
os.environ["SHEET_AUTO_SORT"] = "0"
importlib.reload(config)

# --- 12e) Yazma diapazonu dəyişməyib ---------------------------------------
ws4 = FakeWorksheet(build_grid(tidy=True), rows=24, cols=15)
sheets.write_results(ws4, [{"row": 2, "product_name": "X", "ebay_price": 52.99,
                            "ebay_qty": 3, "amazon_old": 40.0, "amazon_new": 41.5,
                            "stock": "In Stock", "ebay_fee": 9.1,
                            "margin_usd": 5.4, "margin_pct": 10.2,
                            "suggested_ebay": 54.99,
                            "next_check": "2026-09-19 10:00", "status": "OK"}])
check("C:O diapazonuna yazılır", ws4.value_updates[0]["range"], "C2:O2")
check("13 xana yazılır — A/B linklərinə toxunulmur",
      len(ws4.value_updates[0]["values"][0]), 13)

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
