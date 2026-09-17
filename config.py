"""
Konfiqurasiya — bütün ayarlar burada.
Həssas məlumatlar (token, açar) GitHub Secrets-dən gəlir, bu fayla YAZILMIR.
"""
import os

# ---------------------------------------------------------------------------
# GOOGLE SHEET
# ---------------------------------------------------------------------------
SHEET_ID = os.environ.get(
    "SHEET_ID",
    "1h5DJGfwCYPSUyMhzMcxHC-5NJQhnS8qXPVD_nfOF7tE",
)
SHEET_NAME = os.environ.get("SHEET_NAME", "Sheet1")

# Sütun sırası (1-dən başlayır). Sheet-i dəyişsəniz burada da dəyişin.
COL = {
    "ebay_link":      1,   # A
    "amazon_link":    2,   # B
    "product_name":   3,   # C
    "ebay_price":     4,   # D  <- sizin eBay satış qiymətiniz
    "ebay_qty":       5,   # E  <- eBay listinginizdəki qalıq say
    "amazon_old":     6,   # F
    "amazon_new":     7,   # G
    "stock":          8,   # H
    "ebay_fee":       9,   # I  <- eBay haqları (FVF + reklam + əməliyyat)
    "margin_usd":    10,   # J
    "margin_pct":    11,   # K
    "suggested_ebay": 12,  # L
    "last_check":    13,   # M
    "next_check":    14,   # N  <- növbəti yoxlama vaxtı (kredit qənaəti)
    "status":        15,   # O
}
HEADERS = [
    "eBay Link", "Amazon Link", "Məhsul Adı", "eBay Qiymətim", "eBay Say",
    "Amazon (əvvəlki)", "Amazon (indiki)", "Stok",
    "eBay Haqqı", "Marja $", "Marja %", "Tövsiyə eBay",
    "Son Yoxlama", "Növbəti Yoxlama", "Status",
]
FIRST_DATA_ROW = 2

# ---------------------------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ---------------------------------------------------------------------------
# TELEGRAM BİLDİRİŞ ŞƏRTLƏRİ
# ---------------------------------------------------------------------------
# Bildiriş YALNIZ bu üç halda gedir. Qalan bütün vəziyyətlər (marja azalması,
# qiymət düşməsi, listinqin yenidən açıla bilməsi) sheet-də Status sütununda
# görünür, amma Telegram-a mesaj göndərilmir.

def _flag(name: str, default: bool) -> bool:
    return os.environ.get(name, "1" if default else "0").strip() == "1"


# 1) Amazon qiyməti bahalaşanda
ALERT_ON_PRICE_RISE = _flag("ALERT_ON_PRICE_RISE", True)
PRICE_RISE_MIN_USD = float(os.environ.get("PRICE_RISE_MIN_USD", "0.50"))
PRICE_RISE_MIN_PCT = float(os.environ.get("PRICE_RISE_MIN_PCT", "2.0"))

# 2) Amazon-dakı say sizin eBay sayınızdan az olanda
ALERT_ON_LOW_QTY = _flag("ALERT_ON_LOW_QTY", True)

# 3) Amazon-da stok bitəndə
ALERT_ON_OUT_OF_STOCK = _flag("ALERT_ON_OUT_OF_STOCK", True)

# --- Defolt olaraq BAĞLI olanlar (istəsəniz "1" edin) ---
ALERT_ON_PRICE_DROP = _flag("ALERT_ON_PRICE_DROP", False)
ALERT_ON_LOW_MARGIN = _flag("ALERT_ON_LOW_MARGIN", False)
ALERT_ON_RESTOCK = _flag("ALERT_ON_RESTOCK", False)

# Marja bu faizin altına düşərsə sheet-də "AZ MARJA" yazılır
# (bildiriş yalnız ALERT_ON_LOW_MARGIN=1 olduqda).
MARGIN_ALERT_PCT = float(os.environ.get("MARGIN_ALERT_PCT", "15.0"))

# ---------------------------------------------------------------------------
# eBay QİYMƏT TƏKLİFİ
# ---------------------------------------------------------------------------
# Hədəf marja faizi — yeni eBay qiyməti bunu qorumaq üçün hesablanır.
TARGET_MARGIN_PCT = float(os.environ.get("TARGET_MARGIN_PCT", "0"))
# 0 = mövcud marjanızı qoruyur (Amazon nə qədər artıbsa, eBay də o qədər artır).
# Məs. 25 yazsanız, hər məhsulda 25% marja hədəflənəcək.

# ---------------------------------------------------------------------------
# eBay HAQLARI (ebayfeescalculator.com modeli ilə eyni)
# ---------------------------------------------------------------------------
# Vergi bazası = satış qiyməti + göndərmə haqqı + alıcıdan alınan satış vergisi
# FVF və reklam haqqı MƏHZ bu bazadan hesablanır — yəni vergi sizin haqqınızı
# artırır, baxmayaraq ki, vergi pulu sizə çatmır.

# Final Value Fee faizi. Mağazası olmayan satıcı, "Everything else" kateqoriyası
# üçün 13.6%. Öz kateqoriyanıza uyğun dəyişin.
EBAY_FVF_PCT = float(os.environ.get("EBAY_FVF_PCT", "13.6"))

# Promoted Listings reklam dərəcəsi (%). Reklam işlətmirsinizsə 0 qoyun.
EBAY_AD_RATE_PCT = float(os.environ.get("EBAY_AD_RATE_PCT", "0"))

# Sifariş başına sabit əməliyyat haqqı.
EBAY_ORDER_FEE = float(os.environ.get("EBAY_ORDER_FEE", "0.40"))
EBAY_ORDER_FEE_LOW = float(os.environ.get("EBAY_ORDER_FEE_LOW", "0.30"))
EBAY_ORDER_FEE_THRESHOLD = float(os.environ.get("EBAY_ORDER_FEE_THRESHOLD", "10"))

# Alıcıdan alınan satış vergisi (%). ABŞ-da ştatdan asılıdır, orta ~8-10%.
# eBay bunu alıcıdan yığır, sizə çatmır, AMMA haqq bazasını artırır.
SALES_TAX_PCT = float(os.environ.get("SALES_TAX_PCT", "10"))

# Beynəlxalq satış haqqı (%). eBay-də qeydiyyat ünvanınız satışın getdiyi
# ölkədən kənardadırsa tutulur — dropshipping-də DEMƏK OLAR HƏMİŞƏ.
#
# eBay rəsmi cədvəli (International fees for eBay global sellers, id=5224):
#   Azərbaycan → "Europe Unsited (excl. EU)" qrupu → 1.30%
#   Rest of APAC 1.30% · Rest of World 1.55% · Hindistan 1.70% · Yaponiya 1.35%
# Baza FVF ilə eynidir (qiymət + göndərmə + vergi).
EBAY_INTERNATIONAL_PCT = float(os.environ.get("EBAY_INTERNATIONAL_PCT", "1.30"))

# Valyuta çevrilişi haqqı (%). eBay ödənişi USD-dən başqa valyutaya
# çevirirsə 3.0 tutulur (Azərbaycan "All other eBay global countries").
# USD alırsınızsa 0 qalsın.
EBAY_FX_PCT = float(os.environ.get("EBAY_FX_PCT", "0"))

# ƏDV — eBay ÖZ HAQLARININ üstünə əlavə edir (satışın üstünə yox!).
# Dərəcə satıcının qeydiyyat ölkəsinə görədir: Azərbaycan 18%, Böyük Britaniya 20%.
#
# Yəni:  ödəyəcəyiniz = (FVF + reklam + beynəlxalq + əməliyyat) × 1.18
#
# Biznes satıcısısınızsa və eBay-ə ƏDV nömrənizi vermisinizsə 0 ola bilər
# ("reverse charge"). Dəqiq rəqəmi eBay hesab-fakturanızdan yoxlayın:
# Payments → Reports → fee invoice.
EBAY_FEE_VAT_PCT = float(os.environ.get("EBAY_FEE_VAT_PCT", "18"))

# Alıcıdan aldığınız göndərmə haqqı və sizin göndərmə xərciniz (adətən 0).
SHIPPING_CHARGED = float(os.environ.get("SHIPPING_CHARGED", "0"))
SHIPPING_COST = float(os.environ.get("SHIPPING_COST", "0"))

# Təklif olunan qiyməti yuvarlaqlaşdırma: "99" -> x.99, "none" -> yuvarlaqlaşdırma yox
PRICE_ROUNDING = os.environ.get("PRICE_ROUNDING", "99")

# ---------------------------------------------------------------------------
# SCRAPING TEMPİ (bloklamaya qarşı ən vacib parametrlər)
# ---------------------------------------------------------------------------
# Hər işləmədə neçə məhsul yoxlanılsın.
# "auto" (defolt) = sistem özü hesablayır: hər məhsul gündə ~1 dəfə yoxlansın deyə
#   batch = məhsul_sayı / 24 (saatlıq işləmə), 5-60 arasında saxlanılır.
# Məhsul sayı artdıqca özü uyğunlaşır — heç nə dəyişdirmək lazım deyil.
# İstəsəniz rəqəm yaza bilərsiniz (məs. "30"), amma adətən ehtiyac yoxdur.
BATCH_SIZE = os.environ.get("BATCH_SIZE", "auto").strip().lower()

# "auto" rejimində hədlər
AUTO_BATCH_MIN = int(os.environ.get("AUTO_BATCH_MIN", "3"))
AUTO_BATCH_MAX = int(os.environ.get("AUTO_BATCH_MAX", "60"))
RUNS_PER_DAY = int(os.environ.get("RUNS_PER_DAY", "24"))  # cron saatlıq işləyir

# ---------------------------------------------------------------------------
# UYĞUNLAŞAN YOXLAMA TEZLİYİ (API kreditinə qənaətin əsas mexanizmi)
# ---------------------------------------------------------------------------
# Hər məhsulun öz "növbəti yoxlama" vaxtı olur (N sütunu).
# Qiyməti dəyişən məhsul tez-tez, sabit qalan isə getdikcə seyrək yoxlanılır.
# Nəticə: 54 sabit məhsulda kredit sərfi ~3 dəfə azalır.

CHECK_INTERVAL_DAYS = float(os.environ.get("CHECK_INTERVAL_DAYS", "1"))  # başlanğıc

# Sabit qalan məhsul üçün maksimum aralıq (gün).
MAX_INTERVAL_DAYS = float(os.environ.get("MAX_INTERVAL_DAYS", "3"))

# Diqqət tələb edən məhsul (az marja, az stok, stok yox) neçə gündən bir.
ATTENTION_INTERVAL_DAYS = float(os.environ.get("ATTENTION_INTERVAL_DAYS", "1"))

# Xəta (ölü link, oxuna bilməyən səhifə) — boş yerə kredit yandırmamaq üçün.
ERROR_INTERVAL_DAYS = float(os.environ.get("ERROR_INTERVAL_DAYS", "7"))

# Bloklama — növbəti işləmə başqa IP-dən gedəcək, tez təkrar cəhd edirik.
BLOCKED_INTERVAL_DAYS = float(os.environ.get("BLOCKED_INTERVAL_DAYS", "0.08"))  # ~2 saat


def resolve_batch_size(total_products: int) -> int:
    """
    Bu işləmədə maksimum neçə məhsul yoxlana bilər (LİMİT).

    Faktiki say bundan az ola bilər — yalnız yoxlama vaxtı çatmış məhsullar
    seçilir (bax: sheets.pick_batch). Limit sadəcə bir işləmənin çox uzun
    çəkməməsi üçündür.
    """
    import math

    if BATCH_SIZE != "auto":
        try:
            return max(1, int(BATCH_SIZE))
        except ValueError:
            pass  # səhv dəyər yazılıbsa auto-ya keç

    if total_products <= 0:
        return AUTO_BATCH_MIN

    # Nominal pay (cron gecikməsiz halda) — buna ehtiyat üçün 4 dəfə pay veririk,
    # çünki GitHub cron-u tez-tez ötürür və növbə yığılır.
    slots = max(1.0, RUNS_PER_DAY * CHECK_INTERVAL_DAYS)
    nominal = math.ceil(total_products / slots)
    return max(AUTO_BATCH_MIN, min(AUTO_BATCH_MAX, nominal * 4))

# Məhsullar arası təsadüfi gecikmə (saniyə). Aşağı salmayın — bloklamanın əsas səbəbi budur.
DELAY_MIN_SEC = int(os.environ.get("DELAY_MIN_SEC", "8"))
DELAY_MAX_SEC = int(os.environ.get("DELAY_MAX_SEC", "22"))

# Ardıcıl neçə bloklama aşkarlansa işləmə dayandırılsın (IP-ni qorumaq üçün).
BLOCK_ABORT_THRESHOLD = int(os.environ.get("BLOCK_ABORT_THRESHOLD", "3"))

# Bir məhsul üçün maksimum təkrar cəhd.
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "2"))

# Səhifə yüklənmə limiti (saniyə).
PAGE_TIMEOUT_SEC = int(os.environ.get("PAGE_TIMEOUT_SEC", "45"))

# ---------------------------------------------------------------------------
# eBay QİYMƏTİNİN MƏNBƏYİ
# ---------------------------------------------------------------------------
# "sheet"  -> D sütununu siz doldurursunuz (ən təhlükəsiz)
# "scrape" -> eBay listinginizdən avtomatik oxunur
EBAY_PRICE_SOURCE = os.environ.get("EBAY_PRICE_SOURCE", "scrape")

# ---------------------------------------------------------------------------
# eBay QALIQ SAYININ MƏNBƏYİ
# ---------------------------------------------------------------------------
# "sheet"  -> YALNIZ E sütunundakı dəyər (siz yazırsınız) — DEFOLT
# "scrape" -> eBay səhifəsindən oxumağa cəhd edilir
#
# NİYƏ DEFOLT "sheet":
# eBay qalıq sayı səhifədə JavaScript ilə çəkilir və xam HTML-də çox vaxt
# olmur. Dolayı siqnallar (marketinq etiketləri, variant JSON-ları, "sold"
# sayğacları) dəfələrlə YANLIŞ nəticə verdi — açıq listinqlər "bağlı" kimi,
# satılan sayı isə qalıq kimi oxundu. Bu, səhv bildirişlərə səbəb olurdu.
# Sizin öz sayınızı bilməyiniz bizim təxminimizdən qat-qat dəqiqdir.
EBAY_QTY_SOURCE = os.environ.get("EBAY_QTY_SOURCE", "sheet").strip().lower()

# ---------------------------------------------------------------------------
# eBay BROWSE API (ən etibarlı mənbə — scraping-i əvəz edir)
# ---------------------------------------------------------------------------
# Açarlar varsa, eBay qiyməti VƏ qalıq sayı birbaşa API-dən alınır:
#   • pulsuz (gündə 5,000 sorğu)
#   • istifadəçi icazəsi (OAuth razılıq ekranı) tələb etmir
#   • ScraperAPI krediti xərclənmir
# developer.ebay.com -> Application Keys -> Production
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID", "")       # App ID (Client ID)
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET", "")  # Cert ID (Client Secret)
EBAY_MARKETPLACE = os.environ.get("EBAY_MARKETPLACE", "EBAY_US")

# ---------------------------------------------------------------------------
# eBay LİSTİNQİNƏ YAZMA (Trading API) — Amazon-da stok bitəndə sayı 0 etmək
# ---------------------------------------------------------------------------
# Application Keys -> Production -> Dev ID
EBAY_DEV_ID = os.environ.get("EBAY_DEV_ID", "")
# Application Keys -> User Tokens (eBay Sign-in) -> Production -> token
EBAY_AUTH_TOKEN = os.environ.get("EBAY_AUTH_TOKEN", "")

# Amazon-da stok bitəndə eBay sayını avtomatik 0 etmək.
AUTO_ZERO_QTY = _flag("AUTO_ZERO_QTY", False)

# ---------------------------------------------------------------------------
# AVTOMATİK SAY İDARƏSİ
# ---------------------------------------------------------------------------
# Amazon-dakı vəziyyətə görə eBay sayınız avtomatik tənzimlənir:
#   Amazon-da stok yoxdur          -> 0   (listinq bağlanmır, tarixçə qalır)
#   Amazon sayı 10-dan azdır       -> 1   (yalnız bir sifariş öhdəliyi)
#   Amazon sayı 10+ / say bilinmir -> 3   (Amazon "In Stock" deyirsə bol sayılır)
AUTO_QTY = _flag("AUTO_QTY", False)

QTY_PLENTY_THRESHOLD = int(os.environ.get("QTY_PLENTY_THRESHOLD", "10"))
QTY_WHEN_PLENTY = int(os.environ.get("QTY_WHEN_PLENTY", "3"))
QTY_WHEN_LOW = int(os.environ.get("QTY_WHEN_LOW", "1"))

# ---------------------------------------------------------------------------
# AVTOMATİK QİYMƏT İDARƏSİ
# ---------------------------------------------------------------------------
# Hər satışdan MİNİMUM təmiz qazanc (bütün haqlar çıxıldıqdan sonra).
#
# DİQQƏT — bu HƏDD-dir, HƏDƏF deyil:
#   qazanc bundan azdırsa  -> qiymət qaldırılır
#   qazanc bundan çoxdursa -> TOXUNULMUR (çox qazanc problem deyil)
#
# Format: "Amazon_qiymət_həddi:minimum_qazanc"
#   20:5   -> Amazon $20-a qədərdirsə ən az $5
#   50:7   -> $20-50 arası  -> ən az $7
#   1e9:10 -> $50-dən baha  -> ən az $10
PROFIT_TIERS_RAW = os.environ.get("PROFIT_TIERS", "20:5,50:7,1000000:10")

# Bu məbləğdən az qazanc verən məhsul sərf etmir — bildiriş göndərilir.
MIN_PROFIT_USD = float(os.environ.get("MIN_PROFIT_USD", "5"))

AUTO_PRICE = _flag("AUTO_PRICE", False)

# Qiymətin AŞAĞI salınmasına icazə.
#
# DEFOLT BAĞLIDIR və buna ciddi səbəb var: hədd dollarla olduğu üçün açıq
# olanda yaxşı qazanan məhsullar da hədd səviyyəsinə "endirilir".
# Real mağazada ölçdük: 22 məhsulun qiyməti enirdi, ümumi qazanc
# $508 → $294 düşürdü (bir məhsul $136 qazancdan $11-ə enirdi).
#
# Açıq olmadıqda sistem yalnız AZ qazanclı məhsulun qiymətini qaldırır,
# çox qazanclıya toxunmur — amma "ucuzlaşdıra bilərsiniz" bildirişi göndərir.
AUTO_PRICE_ALLOW_DOWN = _flag("AUTO_PRICE_ALLOW_DOWN", False)

# Qazanc həddən bu qədər ÇOX olanda "ucuzlaşdıra bilərsiniz" bildirişi gedir
# (AUTO_PRICE_ALLOW_DOWN=1 olarsa qiymət avtomatik enir).
AUTO_PRICE_DOWN_TOLERANCE = float(os.environ.get("AUTO_PRICE_DOWN_TOLERANCE", "2.00"))

# Qazanc hədəfdən bu qədər AZ olanda qiymət qaldırılır.
AUTO_PRICE_UP_TOLERANCE = float(os.environ.get("AUTO_PRICE_UP_TOLERANCE", "0.25"))

# Bir işləmədə qiymətin maksimum dəyişməsi (%) — səhv oxunuşa qarşı sığorta.
AUTO_PRICE_MAX_UP_PCT = float(os.environ.get("AUTO_PRICE_MAX_UP_PCT", "50"))
AUTO_PRICE_MAX_DOWN_PCT = float(os.environ.get("AUTO_PRICE_MAX_DOWN_PCT", "25"))

# Bundan kiçik fərqə görə qiymət dəyişdirilmir (boş yerə sorğu getməsin).
AUTO_PRICE_MIN_DIFF_USD = float(os.environ.get("AUTO_PRICE_MIN_DIFF_USD", "0.50"))


def _parse_tiers(raw: str):
    tiers = []
    for part in raw.split(","):
        part = part.strip()
        if not part or ":" not in part:
            continue
        upto, profit = part.split(":", 1)
        try:
            tiers.append((float(upto), float(profit)))
        except ValueError:
            continue
    return sorted(tiers) or [(1e9, 5.0)]


PROFIT_TIERS = _parse_tiers(PROFIT_TIERS_RAW)

# QURU REJİM — defolt AÇIQ. Nə ediləcəyini yazır, amma HEÇ NƏYİ dəyişmir.
# Bir neçə gün nəticələrə baxıb əmin olandan sonra "0" edin.
AUTO_DRY_RUN = _flag("AUTO_DRY_RUN", True)

# Sətir üzrə icazə sütunu ARTIQ YOXDUR.
# Bütün məhsullar avtomatik idarə olunur — sheet-də heç nə yazmaq lazım deyil.
# Sistemi tam dayandırmaq üçün GitHub Variables-da AUTO_QTY=0 / AUTO_PRICE=0.

# eBay səhifəsi neçə gündən bir tam yenilənsin.
# Öz listinginizin qiymətini siz təyin etdiyiniz üçün tez-tez oxumağa ehtiyac yoxdur —
# bu, API kreditinə qənaət edir. Qalıq say azalanda və ya Amazon-da stok bitəndə
# bu müddətdən asılı olmayaraq dərhal oxunur.
EBAY_REFRESH_DAYS = int(os.environ.get("EBAY_REFRESH_DAYS", "30"))

# Qalıq say bu həddə enəndə eBay hər yoxlamada oxunur (tezliklə bitə bilər).
EBAY_LOW_QTY = int(os.environ.get("EBAY_LOW_QTY", "2"))

# ---------------------------------------------------------------------------
# AMAZON-A GİRİŞ ÜSULU
# ---------------------------------------------------------------------------
# "auto"   -> əvvəlcə birbaşa cəhd et, bloklama olsa API-yə keç (defolt)
# "api"    -> həmişə API üzərindən (GitHub Actions üçün ən etibarlısı)
# "direct" -> yalnız birbaşa (öz kompüterinizdə / rezident IP-də)
_scrape_method_raw = os.environ.get("SCRAPE_METHOD", "").strip().lower()

# Pulsuz kredit verən scraping API-ləri (rezident proksi ilə işləyirlər).
# Açar yoxdursa avtomatik ötürülür.
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")
SCRAPINGBEE_KEY = os.environ.get("SCRAPINGBEE_KEY", "")


def has_api_fallback() -> bool:
    return bool(SCRAPERAPI_KEY or SCRAPINGBEE_KEY)


def _resolve_scrape_method() -> str:
    """
    SCRAPE_METHOD təyin edilməyibsə ağıllı defolt seçir.

    GitHub Actions serverlərini Amazon istisnasız bloklayır — orada birbaşa
    cəhd etmək hər işləmədə bir sorğunu və ~1 dəqiqəni boş yerə xərcləyir.
    Ona görə CI mühitində API açarı varsa birbaşa "api" rejimi seçilir.
    Öz kompüterinizdə (rezident IP) isə "auto" qalır.
    """
    if _scrape_method_raw in ("api", "direct", "auto"):
        return _scrape_method_raw
    in_ci = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"
    if in_ci and has_api_fallback():
        return "api"
    return "auto"


SCRAPE_METHOD = _resolve_scrape_method()
