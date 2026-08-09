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
# BİLDİRİŞ ŞƏRTLƏRİ
# ---------------------------------------------------------------------------
# Amazon qiyməti bu qədər ($) və ya bu faizdən çox artarsa bildiriş gəlir.
PRICE_RISE_MIN_USD = float(os.environ.get("PRICE_RISE_MIN_USD", "0.50"))
PRICE_RISE_MIN_PCT = float(os.environ.get("PRICE_RISE_MIN_PCT", "2.0"))

# Marja bu faizin altına düşərsə xəbərdarlıq.
MARGIN_ALERT_PCT = float(os.environ.get("MARGIN_ALERT_PCT", "15.0"))

# Stok bitəndə həmişə bildiriş.
ALERT_ON_OUT_OF_STOCK = True

# Qiymət düşəndə bildiriş (defolt: bağlı, spam olmasın deyə).
ALERT_ON_PRICE_DROP = os.environ.get("ALERT_ON_PRICE_DROP", "0") == "1"

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

# Beynəlxalq satış əlavəsi (%). Yalnız xaricə satırsınızsa 1.65 qoyun.
EBAY_INTERNATIONAL_PCT = float(os.environ.get("EBAY_INTERNATIONAL_PCT", "0"))

# Alıcıdan aldığınız göndərmə haqqı və sizin göndərmə xərciniz (adətən 0).
SHIPPING_CHARGED = float(os.environ.get("SHIPPING_CHARGED", "0"))
SHIPPING_COST = float(os.environ.get("SHIPPING_COST", "0"))

# Köhnə ad — geriyə uyğunluq üçün saxlanılır.
EBAY_FEE_PCT = EBAY_FVF_PCT

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
