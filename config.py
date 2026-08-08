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
    "margin_usd":     9,   # I
    "margin_pct":    10,   # J
    "suggested_ebay": 11,  # K
    "last_check":    12,   # L
    "status":        13,   # M
}
HEADERS = [
    "eBay Link", "Amazon Link", "Məhsul Adı", "eBay Qiymətim", "eBay Say",
    "Amazon (əvvəlki)", "Amazon (indiki)", "Stok",
    "Marja $", "Marja %", "Tövsiyə eBay", "Son Yoxlama", "Status",
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

# eBay komissiyası + göndərmə payı (təklif hesablanarkən nəzərə alınır).
EBAY_FEE_PCT = float(os.environ.get("EBAY_FEE_PCT", "13.25"))

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


def resolve_batch_size(total_products: int) -> int:
    """Məhsul sayına görə bu işləmədə neçə məhsul yoxlanacağını qaytarır."""
    import math

    if BATCH_SIZE != "auto":
        try:
            return max(1, int(BATCH_SIZE))
        except ValueError:
            pass  # səhv dəyər yazılıbsa auto-ya keç

    if total_products <= 0:
        return AUTO_BATCH_MIN
    per_run = math.ceil(total_products / RUNS_PER_DAY)
    return max(AUTO_BATCH_MIN, min(AUTO_BATCH_MAX, per_run))

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

# eBay qiyməti neçə gündən bir yenilənsin (listing qiymətiniz tez-tez dəyişmir).
EBAY_REFRESH_DAYS = int(os.environ.get("EBAY_REFRESH_DAYS", "7"))

# ---------------------------------------------------------------------------
# AMAZON-A GİRİŞ ÜSULU
# ---------------------------------------------------------------------------
# "auto"   -> əvvəlcə birbaşa cəhd et, bloklama olsa API-yə keç (defolt)
# "api"    -> həmişə API üzərindən (GitHub Actions üçün ən etibarlısı)
# "direct" -> yalnız birbaşa (öz kompüterinizdə / rezident IP-də)
SCRAPE_METHOD = os.environ.get("SCRAPE_METHOD", "auto").strip().lower()

# Pulsuz kredit verən scraping API-ləri (rezident proksi ilə işləyirlər).
# Açar yoxdursa avtomatik ötürülür.
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")
SCRAPINGBEE_KEY = os.environ.get("SCRAPINGBEE_KEY", "")


def has_api_fallback() -> bool:
    return bool(SCRAPERAPI_KEY or SCRAPINGBEE_KEY)
