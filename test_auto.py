#!/usr/bin/env python3
"""
AVTOMATİK İDARƏETMƏNİN TAM TESTİ — say + qiymət.

Real eBay-ə, Amazon-a və Google Sheets-ə HEÇ BİR sorğu getmir.
Bütün cavablar saxtadır, bütün yazma əməliyyatları tutulur.

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
    "BATCH_SIZE": "10",
    # Agil-in real ayarları
    "EBAY_FVF_PCT": "13.6", "EBAY_AD_RATE_PCT": "4", "SALES_TAX_PCT": "8",
    "EBAY_INTERNATIONAL_PCT": "1.30", "EBAY_FX_PCT": "0",
    # Avtomatika tam açıq
    "AUTO_ZERO_QTY": "1", "AUTO_QTY": "1", "AUTO_PRICE": "1",
})

PASS, FAIL = [], []


def check(name, got, expected):
    ok = got == expected
    (PASS if ok else FAIL).append(name)
    print(f"  {'✅' if ok else '❌'} {name}"
          + ("" if ok else f"   (alındı: {got!r}, gözlənilən: {expected!r})"))


def near(name, got, expected, tol=0.02):
    ok = got is not None and abs(got - expected) <= tol
    (PASS if ok else FAIL).append(name)
    print(f"  {'✅' if ok else '❌'} {name}"
          + ("" if ok else f"   (alındı: {got!r}, gözlənilən: ~{expected})"))


def section(t):
    print(f"\n{'=' * 74}\n{t}\n{'=' * 74}")


import config
import ebay_write
import pricing

# ===========================================================================
section("1. HAQQ MODELİ — Azərbaycan satıcısı (beynəlxalq haqq 1.30%)")
# ===========================================================================
d = pricing.fee_breakdown(60.99)
print(f"  Satış $60.99 · vergi 8% · FVF 13.6% · reklam 4% · beynəlxalq 1.30%")
print(f"  Baza ${d['fee_base']}  =  60.99 + vergi ${d['sales_tax']}")
near("vergi (8% × 60.99)", d["sales_tax"], 4.88)
near("haqq bazası", d["fee_base"], 65.87)
near("FVF (13.6% × baza)", d["fvf"], 8.96)
near("reklam (4% × baza)", d["ads"], 2.63)
near("beynəlxalq (1.30% × baza)", d["international"], 0.86)
near("əməliyyat haqqı", d["order_fee"], 0.40)
near("CƏMİ haqq", d["total"], 12.85)

d0 = pricing.fee_breakdown(60.99)
os.environ["EBAY_INTERNATIONAL_PCT"] = "0"
importlib.reload(config); importlib.reload(pricing)
d_no = pricing.fee_breakdown(60.99)
print(f"\n  Beynəlxalq haqq OLMASA: ${d_no['total']} "
      f"→ fərq ${d0['total'] - d_no['total']:.2f} (hər satışda əlavə xərc)")
os.environ["EBAY_INTERNATIONAL_PCT"] = "1.30"
importlib.reload(config); importlib.reload(pricing)

# ===========================================================================
section("2. HƏDƏF QAZANC PİLLƏLƏRİ (20:$5 · 50:$7 · yuxarı:$10)")
# ===========================================================================
for amazon, gozlenen in [(9.99, 5), (20.00, 5), (20.01, 7), (39.99, 7),
                         (50.00, 7), (50.01, 10), (150.00, 10)]:
    check(f"Amazon ${amazon:>6.2f} → hədəf ${gozlenen}",
          pricing.target_profit_for(amazon), float(gozlenen))

# ===========================================================================
section("3. SAY PLANI — Amazon vəziyyətindən eBay sayı")
# ===========================================================================
qty_cases = [
    ("stok yoxdur",                    False, None, 0),
    ("stok yoxdur, say 0",             False, 0,    0),
    ("stokda, say bilinmir (bol)",     True,  None, 3),
    ("stokda, Amazon-da 25 ədəd",      True,  25,   3),
    ("stokda, Amazon-da tam 10 ədəd",  True,  10,   3),
    ("stokda, Amazon-da 9 ədəd",       True,  9,    1),
    ("stokda, Amazon-da 1 ədəd",       True,  1,    1),
    ("stokda deyilir, amma say 0",     True,  0,    0),
]
for ad, stok, aqty, gozlenen in qty_cases:
    check(f"{ad:32} → say {gozlenen}",
          pricing.desired_qty(stok, aqty), gozlenen)

# ===========================================================================
section("4. QİYMƏT PLANI")
# ===========================================================================
print("\n  a) Amazon bahalaşıb — qazanc hədəfdən aşağı düşüb")
cur_profit, _ = pricing.margin(60.99, 45.99)
p = pricing.plan_price_change(60.99, 45.99)
print(f"     Cari: eBay $60.99 · Amazon $45.99 · qazanc ${cur_profit}")
print(f"     Hədəf ${p['target_profit']} → yeni qiymət ${p['new_price']} "
      f"· yeni qazanc ${p['new_profit']}")
check("istiqamət: artım", p["direction"], "up")
# .99 yuvarlaqlaşdırma qiyməti yuxarı çəkir — qazanc bir az çox çıxır, bu normaldır
near("yeni qazanc hədəfə çatır", p["new_profit"], p["target_profit"], 1.00)
check("qiymət artıb", p["new_price"] > 60.99, True)

print("\n  a2) Qazanc hədəfdən bir az çoxdur — dözümlülük zonası")
p_ok = pricing.plan_price_change(60.99, 39.99)
c_ok, _ = pricing.margin(60.99, 39.99)
print(f"     Qazanc ${c_ok} · hədəf ${p_ok['target_profit']} "
      f"(dözümlülük +${config.AUTO_PRICE_DOWN_TOLERANCE}) → {p_ok['reason']}")
check("dözümlülük zonasında toxunulmur", p_ok["new_price"], None)

print("\n  b) Amazon ucuzlaşıb — qazanc hədəfi xeyli aşır")
p2 = pricing.plan_price_change(60.99, 25.00)
c2, _ = pricing.margin(60.99, 25.00)
print(f"     Cari qazanc ${c2} · hədəf ${p2['target_profit']} "
      f"→ yeni qiymət ${p2['new_price']} · qazanc ${p2['new_profit']}")
check("istiqamət: azalma", p2["direction"], "down")
check("qiymət aşağı salınıb", p2["new_price"] < 60.99, True)

print("\n  c) Qazanc hədəfə uyğundur — toxunulmamalıdır")
ideal = pricing._round_price(pricing.price_for_profit(7.0, 39.99))
p3 = pricing.plan_price_change(ideal, 39.99)
print(f"     Qiymət ${ideal} · qazanc ${pricing.margin(ideal, 39.99)[0]} "
      f"→ {p3['reason']}")
check("dəyişiklik yoxdur", p3["new_price"], None)

print("\n  d) Kiçik dalğalanma — qiymət oynamamalıdır")
p4 = pricing.plan_price_change(ideal, 40.09)   # Amazon 10 sent bahalaşıb
check("10 sentlik fərqə toxunulmur", p4["new_price"], None)

print("\n  e) Amazon çox bahalaşıb — təhlükəsizlik həddi")
p5 = pricing.plan_price_change(30.00, 80.00)
print(f"     eBay $30 · Amazon $80 → yeni ${p5['new_price']} "
      f"(hədd: maksimum +{config.AUTO_PRICE_MAX_UP_PCT}%)")
check("hədd tətbiq olundu", p5["capped"], True)
check("hədd daxilində qazanc alınmır → dəyişiklik yoxdur", p5["new_price"], None)
check("istifadəçiyə xəbər verilir (below_min)", p5["below_min"], True)
print(f"     Səbəb: {p5['reason']}")

print("\n  e2) Amazon orta dərəcədə bahalaşıb — hədd daxilində düzəlir")
p5b = pricing.plan_price_change(50.00, 45.00)
print(f"     eBay $50 · Amazon $45 → yeni ${p5b['new_price']} "
      f"· qazanc ${p5b['new_profit']}")
check("qiymət qaldırıldı", bool(p5b["new_price"] and p5b["new_price"] > 50.00), True)
check("artım həddi aşılmayıb", p5b["new_price"] <= 50.00 * 1.51, True)

print("\n  f) Zərər qoruması")
p6 = pricing.plan_price_change(20.00, 100.00)
check("zərərə satış edilmir", p6["new_price"] is None or p6["new_profit"] > 0, True)

print("\n  g) Stok yoxdursa qiymətə toxunulmur")
check("stok yox → dəyişiklik yoxdur",
      pricing.plan_price_change(60.99, 39.99, in_stock=False)["new_price"], None)

print("\n  h) Məlumat çatmırsa")
check("Amazon qiyməti yoxdur", pricing.plan_price_change(60.99, None)["new_price"], None)
check("eBay qiyməti yoxdur", pricing.plan_price_change(None, 39.99)["new_price"], None)

print("\n  i) Azalma bağlananda")
os.environ["AUTO_PRICE_ALLOW_DOWN"] = "0"
importlib.reload(config); importlib.reload(pricing)
check("azalma bağlıdır → toxunulmur",
      pricing.plan_price_change(60.99, 25.00)["new_price"], None)
check("artım yenə işləyir",
      pricing.plan_price_change(60.99, 45.99)["direction"], "up")
os.environ["AUTO_PRICE_ALLOW_DOWN"] = "1"
importlib.reload(config); importlib.reload(pricing)

# ===========================================================================
section("5. SƏTİR ÜZRƏ İCAZƏ (P sütunu)")
# ===========================================================================
for val, gozlenen in [("beli", {"qty", "price"}), ("hə", {"qty", "price"}),
                      ("1", {"qty", "price"}), ("say", {"qty"}),
                      ("sayı", {"qty"}), ("qiymet", {"price"}),
                      ("qiymət", {"price"}), ("", set()), ("yox", set()),
                      ("  BELI  ", {"qty", "price"})]:
    check(f"'{val}' → {sorted(gozlenen) or 'icazə yoxdur'}",
          config.auto_modes(val), gozlenen)

# ===========================================================================
section("6. YAZMA QORUYUCULARI — heç bir sorğu getməməli hallar")
# ===========================================================================
SENT = []


def fake_call(call_name, inner):
    SENT.append((call_name, inner))
    return True, "<Ack>Success</Ack>"


ebay_write._call = fake_call
ebay_write._oos_pref_cache.update({"checked": True, "enabled": True})


def try_apply(item="157968828656", qb=5, pb=50.0, qn=None, pn=None, dry=False):
    SENT.clear()
    return ebay_write.apply_changes(item, qb, pb, qn, pn, dry_run=dry)

r = try_apply(item="", qn=0)
check("listinq nömrəsi yoxdur → icra yox", r["done"], False)
check("listinq nömrəsi yoxdur → sorğu yox", len(SENT), 0)

r = try_apply(qb=3, qn=3)
check("say eynidir → sorğu göndərilmir", len(SENT), 0)
check("say eynidir → səbəb yazılır", r["skipped"], "dəyişiklik lazım deyil")

r = try_apply(pb=50.0, pn=50.0)
check("qiymət eynidir → sorğu göndərilmir", len(SENT), 0)

r = try_apply(qn=0, pn=None)
ebay_write._oos_pref_cache.update({"checked": True, "enabled": False})
r = try_apply(qn=0)
check("'Multi-quantity' bağlıdır → sayı 0 etmir", r["done"], False)
check("'Multi-quantity' bağlıdır → sorğu getmir", len(SENT), 0)

r = try_apply(qn=0, pn=55.0)
check("ayar bağlı, amma qiymət dəyişir → qiymət gedir", r["done"], True)
check("...və sorğuda say YOXDUR", "<Quantity>" in SENT[0][1], False)
check("...qiymət var", "<StartPrice>55.00</StartPrice>" in SENT[0][1], True)

ebay_write._oos_pref_cache.update({"checked": True, "enabled": None})
r = try_apply(qn=0)
check("ayar naməlum → sayı 0 etmir", r["done"], False)

ebay_write._oos_pref_cache.update({"checked": True, "enabled": True})
r = try_apply(qb=8, qn=3, pn=68.99)
check("hər ikisi BİR sorğuda gedir", len(SENT), 1)
check("sorğuda say var", "<Quantity>3</Quantity>" in SENT[0][1], True)
check("sorğuda qiymət var", "<StartPrice>68.99</StartPrice>" in SENT[0][1], True)
check("çağırış adı", SENT[0][0], "ReviseInventoryStatus")

r = try_apply(qb=8, qn=3, pn=68.99, dry=True)
check("quru rejim → sorğu getmir", len(SENT), 0)
check("quru rejim → nə ediləcəyi yazılır", "say 8 → 3" in r["message"], True)

ebay_write._call = lambda c, i: (False, "Auth token is invalid")
r = try_apply(qn=0)
check("eBay xətası tutulur", r["done"], False)
check("xəta mətni saxlanılır", "Auth token is invalid" in r["skipped"], True)
ebay_write._call = fake_call

# ===========================================================================
section("7. TAM AXIN — 6 məhsul, hansına nə edilir?")
# ===========================================================================
import ebay_api
import notify
import scraper
import sheets

now = datetime.utcnow()


def mkrow(r, key, auto, qty, price):
    return {"row": r, "ebay_link": f"https://www.ebay.com/itm/1570000000{r:02d}",
            "amazon_link": f"https://www.amazon.com/dp/{key}", "product_name": key,
            "ebay_price": price, "ebay_qty": qty, "amazon_old": 39.99, "stock_old": "",
            "last_check": (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
            "next_check": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
            "prev_status": "OK", "auto": auto, "auto_log": ""}


def page(title, price=None, oos=False, only=None):
    h = f'<span id="productTitle">{title}</span>'
    if oos:
        return h + '<div id="outOfStock">x</div>'
    h += f'<script>"priceAmount":{price:.2f}</script>'
    txt = f"Only {only} left in stock" if only else "In Stock"
    return h + f'<div id="availability" class="a"><span>{txt}</span></div>'


FAKE = [
    mkrow(2, "A_STOK_YOX",    "beli",   8,  60.99),   # stok bitib → say 0
    mkrow(3, "B_ICAZESIZ",    "",       8,  60.99),   # icazə yox → toxunulmur
    mkrow(4, "C_BOL_BAHA",    "beli",   8,  60.99),   # bol + bahalaşıb → say 3 + qiymət↑
    mkrow(5, "D_AZ_QALIB",    "beli",   8,  60.99),   # Amazon-da 4 ədəd → say 1
    mkrow(6, "E_YALNIZ_SAY",  "say",    8,  60.99),   # yalnız say rejimi
    mkrow(7, "F_YALNIZ_QIY",  "qiymet", 8,  60.99),   # yalnız qiymət rejimi
]
PAGES = {
    "A_STOK_YOX":   page("Stoku bitib", oos=True),
    "B_ICAZESIZ":   page("İcazəsiz məhsul", oos=True),
    "C_BOL_BAHA":   page("Bol və bahalaşıb", price=45.99),
    "D_AZ_QALIB":   page("Az qalıb", price=39.99, only=4),
    "E_YALNIZ_SAY": page("Yalnız say", price=45.99),
    "F_YALNIZ_QIY": page("Yalnız qiymət", price=45.99),
}

WRITTEN, MESSAGES = {}, []
fs = types.ModuleType("sheets")
fs.open_sheet = lambda: "WS"
fs.ensure_structure = lambda w: True
fs.read_rows = lambda w: FAKE
for n in ["pick_batch", "count_due", "should_fetch_ebay",
          "needs_ebay_refresh", "previous_interval_days"]:
    setattr(fs, n, getattr(sheets, n))
fs.write_results = lambda w, res: [WRITTEN.__setitem__(x["row"], x) for x in res]
sys.modules["sheets"] = fs

fn = types.ModuleType("notify")
for n in ["format_alerts", "format_blocked", "format_health",
          "format_auto_actions", "format_low_profit", "format_run_error"]:
    setattr(fn, n, getattr(notify, n))
fn.send = lambda t, silent=False: MESSAGES.append(t) or True
sys.modules["notify"] = fn

scraper.fetch_via_fallback = lambda url, skip_first=False: next(
    (v for k, v in PAGES.items() if url.endswith("/" + k)), "<html>Page Not Found</html>")
scraper.polite_delay = lambda api_mode=False: None
scraper.scrape_ebay_info = lambda b, u, api_mode=False: {"price": None, "qty": None}

# eBay Browse API — real vəziyyətdəki kimi işləyir (sizdə açarlar var).
# Hər listinq üçün cari qiymət və say qaytarır.
EBAY_LIVE = {}


def fake_fetch(url):
    iid = ebay_api.extract_item_id(url) or ""
    return EBAY_LIVE.get(iid[-2:], {"price": 60.99, "qty": 8,
                                    "qty_exact": True, "status": "IN_STOCK"})


ebay_api.fetch_item = fake_fetch
ebay_api.is_configured = lambda: True

CALLS = []
ebay_write._oos_pref_cache.update({"checked": True, "enabled": True})
_orig_apply = ebay_write.apply_changes


def spy(item_id, cq, cp, nq, np_, dry_run):
    res = _orig_apply(item_id, cq, cp, nq, np_, dry_run)
    CALLS.append({"item": item_id, "new_qty": nq, "new_price": np_, **res})
    return res


ebay_write.apply_changes = spy
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


def acted(suffix):
    return next((c for c in CALLS if c["item"].endswith(suffix)), None)


a, b = acted("02"), acted("03")
c, dd = acted("04"), acted("05")
e, f = acted("06"), acted("07")

print("  Sətir 2 — Amazon-da stok bitib (icazə: beli)")
check("   say 0 edildi", a and a["new_qty"], 0)
check("   qiymətə toxunulmadı", a and a["new_price"], None)

print("  Sətir 3 — icazə YOXDUR")
check("   heç nə edilmədi", b, None)

print("  Sətir 4 — bol stok + Amazon bahalaşıb (icazə: beli)")
check("   say 8 → 3", c and c["new_qty"], 3)
check("   qiymət qaldırıldı", bool(c and c["new_price"] and c["new_price"] > 60.99), True)

print("  Sətir 5 — Amazon-da yalnız 4 ədəd qalıb")
check("   say 8 → 1", dd and dd["new_qty"], 1)

print("  Sətir 6 — icazə: 'say' (yalnız say)")
check("   say dəyişdi", e and e["new_qty"], 3)
check("   qiymətə toxunulmadı", e and e["new_price"], None)

print("  Sətir 7 — icazə: 'qiymet' (yalnız qiymət)")
check("   saya toxunulmadı", f and f["new_qty"], None)
check("   qiymət dəyişdi", bool(f and f["new_price"]), True)

print("\n  Sheet-ə yazılanlar:")
for rownum in sorted(WRITTEN):
    w = WRITTEN[rownum]
    print(f"    sətir {rownum}: {w['product_name'][:14]:14} "
          f"say={w.get('ebay_qty')} qiymət={w.get('ebay_price')} "
          f"| {w.get('auto_log', '')}")
check("audit izi yazıldı (Q sütunu)",
      bool(WRITTEN.get(4, {}).get("auto_log")), True)
check("icazəsiz sətirdə audit izi yoxdur",
      bool(WRITTEN.get(3, {}).get("auto_log")), False)

# ===========================================================================
section("8A. SPAM YOXLAMASI — heç nə dəyişməyəndə hesabat getməməlidir")
# ===========================================================================
# Bütün sətirlər onsuz da hədəf vəziyyətdədir: say 3, qiymət hədəfə uyğun.
hedef_qiymet = pricing._round_price(pricing.price_for_profit(7.0, 39.99))
SAKIT = [mkrow(10 + i, f"SABIT_{i}", "beli", 3, hedef_qiymet) for i in range(4)]
for i in range(4):
    PAGES[f"SABIT_{i}"] = page(f"Sabit məhsul {i}", price=39.99)
for i in range(4):
    EBAY_LIVE[f"{10 + i}"] = {"price": hedef_qiymet, "qty": 3,
                              "qty_exact": True, "status": "IN_STOCK"}

FAKE[:] = SAKIT
WRITTEN.clear(); MESSAGES.clear(); CALLS.clear()
_out = sys.stdout
sys.stdout = open(os.devnull, "w")
try:
    main.run()
finally:
    sys.stdout.close()
    sys.stdout = _out

spam = [m for m in MESSAGES if "avtomatik dəyişiklik" in m.lower() or "QURU REJİM" in m]
check("dəyişiklik yoxdursa avto-hesabat GÖNDƏRİLMİR", len(spam), 0)
check("eBay-ə yazma sorğusu getmir",
      all(not c["done"] for c in CALLS), True)
print(f"     ({len(CALLS)} sətir yoxlandı, {len(MESSAGES)} mesaj göndərildi)")

# ===========================================================================
section("8B. HƏDD YUVARLAQLAŞDIRMASI — hədd aşılmamalıdır")
# ===========================================================================
for cur, amz in [(30.00, 80.00), (25.00, 60.00), (40.00, 90.00), (12.00, 30.00)]:
    pp = pricing.plan_price_change(cur, amz)
    if pp["new_price"]:
        limit = cur * (1 + config.AUTO_PRICE_MAX_UP_PCT / 100)
        check(f"${cur} → ${pp['new_price']} ≤ hədd ${limit:.2f}",
              pp["new_price"] <= limit + 0.001, True)
    else:
        check(f"${cur} (Amazon ${amz}) → dəyişiklik yoxdur", True, True)

# Aşağı hədd
for cur, amz in [(60.99, 10.00), (100.00, 20.00)]:
    pp = pricing.plan_price_change(cur, amz)
    if pp["new_price"]:
        limit = cur * (1 - config.AUTO_PRICE_MAX_DOWN_PCT / 100)
        check(f"${cur} → ${pp['new_price']} ≥ hədd ${limit:.2f}",
              pp["new_price"] >= limit - 0.001, True)

# ===========================================================================
section("8C. KÖHNƏ QİYMƏTLƏ AVTOMATİK DƏYİŞİKLİK EDİLMİR")
# ===========================================================================
FAKE[:] = [mkrow(20, "KOHNE_QIYMET", "qiymet", 3, 60.99)]
PAGES["KOHNE_QIYMET"] = page("Köhnə qiymət", price=45.99)
ebay_api.is_configured = lambda: False          # API söndürülüb
scraper.scrape_ebay_info = lambda b, u, api_mode=False: {"price": None, "qty": None}
WRITTEN.clear(); MESSAGES.clear(); CALLS.clear()
_out = sys.stdout
sys.stdout = open(os.devnull, "w")
try:
    main.run()
finally:
    sys.stdout.close()
    sys.stdout = _out
check("eBay qiyməti oxunmayıbsa qiymətə toxunulmur", len(CALLS), 0)
ebay_api.is_configured = lambda: True

# ===========================================================================
section("8D. DÜZƏLİŞDƏN SONRA STATUS YENİLƏNİR")
# ===========================================================================
FAKE[:] = [mkrow(30, "AZ_QAZANC", "beli", 3, 60.99)]
PAGES["AZ_QAZANC"] = page("Az qazanclı məhsul", price=52.99)
EBAY_LIVE["30"] = {"price": 60.99, "qty": 3, "qty_exact": True, "status": "IN_STOCK"}
os.environ["AUTO_DRY_RUN"] = "0"
importlib.reload(config)
main.config = config
WRITTEN.clear(); MESSAGES.clear(); CALLS.clear()
_out = sys.stdout
sys.stdout = open(os.devnull, "w")
try:
    main.run()
finally:
    sys.stdout.close()
    sys.stdout = _out
w30 = WRITTEN.get(30, {})
cur30, _ = pricing.margin(60.99, 52.99)
print(f"     Əvvəl: qiymət $60.99 · Amazon $52.99 · qazanc ${cur30}")
print(f"     Sonra: qiymət ${w30.get('ebay_price')} · qazanc ${w30.get('margin_usd')} "
      f"· status '{w30.get('status')}'")
check("qiymət düzəldildi", bool(w30.get("ebay_price") and w30["ebay_price"] > 60.99), True)
check("status 'AZ QAZANC' olaraq QALMIR", w30.get("status") != "AZ QAZANC", True)
check("marja yenidən hesablandı",
      bool(w30.get("margin_usd") and w30["margin_usd"] >= config.MIN_PROFIT_USD), True)

# ===========================================================================
section("8. TELEGRAM MESAJI")
# ===========================================================================
auto_msg = next((m for m in MESSAGES if "avtomatik dəyişiklik" in m.lower()
                 or "QURU REJİM" in m), "")
check("hesabat göndərildi", bool(auto_msg), True)
print()
for line in auto_msg.replace("<b>", "").replace("</b>", "").replace(
        "<i>", "").replace("</i>", "").split("\n"):
    print("  " + line)

# ===========================================================================
section("NƏTİCƏ")
# ===========================================================================
print(f"\n  Keçdi: {len(PASS)}   Uğursuz: {len(FAIL)}")
if FAIL:
    print("\n  UĞURSUZ:")
    for x in FAIL:
        print(f"    ❌ {x}")
    sys.exit(1)
print("\n  ✅ AVTOMATİK İDARƏETMƏ TESTLƏRİ KEÇDİ\n")
