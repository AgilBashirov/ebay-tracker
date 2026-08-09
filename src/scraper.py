"""
Amazon və eBay səhifələrindən qiymət/stok oxuma.

Bloklamaya qarşı strategiya:
  1. Real brauzer (Playwright + Chromium), headless izləri gizlədilir
  2. Təsadüfi User-Agent və pəncərə ölçüsü
  3. Məhsullar arası uzun təsadüfi gecikmə
  4. Bloklama aşkarlananda dərhal dayanma (IP-ni yandırmamaq üçün)
  5. Ehtiyat kanal: pulsuz scraping API kreditləri
"""
import random
import re
import time
from dataclasses import dataclass, field

import config

# ---------------------------------------------------------------------------

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
]

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
]

BLOCK_MARKERS = [
    "enter the characters you see below",
    "type the characters you see in this image",
    "sorry, we just need to make sure you're not a robot",
    "to discuss automated access to amazon data",
    "api-services-support@amazon.com",
    "captcha",
    "robot check",
]

OOS_MARKERS = [
    "currently unavailable",
    "temporarily out of stock",
    "out of stock",
    "we don't know when or if this item will be back",
]


class BlockedError(Exception):
    """Amazon bizi bot kimi tanıdı."""


class NotFoundError(Exception):
    """Səhifə mövcud deyil (404 / silinmiş listing)."""


@dataclass
class ScrapeResult:
    price: float | None = None
    stock: str = ""
    name: str = ""
    in_stock: bool = True
    # Amazon-da qalan say. Yalnız "Only N left in stock" göründükdə bilinir.
    # None = say açıqlanmayıb (adətən bol olduğu üçün).
    qty: int | None = None
    notes: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Brauzer
# ---------------------------------------------------------------------------

class Browser:
    """Playwright brauzerini bir dəfə açıb bütün məhsullar üçün təkrar istifadə edir."""

    def __init__(self):
        self._pw = None
        self._browser = None
        self._context = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-gpu",
            ],
        )
        self._context = self._browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            viewport=random.choice(VIEWPORTS),
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Upgrade-Insecure-Requests": "1",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
            },
        )
        # headless izlərini gizlət
        self._context.add_init_script(
            """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            window.chrome = { runtime: {} };
            """
        )
        return self

    def __exit__(self, *exc):
        for obj in (self._context, self._browser):
            try:
                obj and obj.close()
            except Exception:
                pass
        try:
            self._pw and self._pw.stop()
        except Exception:
            pass

    def fetch_html(self, url: str) -> tuple[str, int]:
        page = self._context.new_page()
        try:
            resp = page.goto(
                url,
                timeout=config.PAGE_TIMEOUT_SEC * 1000,
                wait_until="domcontentloaded",
            )
            page.wait_for_timeout(random.randint(800, 2200))
            status = resp.status if resp else 0
            html = page.content()
            return html, status
        finally:
            try:
                page.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Amazon
# ---------------------------------------------------------------------------

# VACİB: qiymət YALNIZ buy box-dan oxunur.
# Səhifə boyu "a-offscreen" axtarmaq təhlükəlidir — stokda olmayan məhsullarda
# başqa satıcının və ya oxşar məhsulun qiymətini tutur və məhsulu səhvən
# "satışda və qiyməti var" kimi göstərir.
PRICE_PATTERNS = [
    r'"priceAmount"\s*:\s*([\d.]+)',
    r'id=["\']?priceblock_ourprice["\']?[^>]*>\s*\$([\d,]+\.\d{2})',
    r'"displayPrice"\s*:\s*"\$([\d,]+\.\d{2})"',
]

# Qiymət buy box JSON-unda tapılmasa, yalnız bu bölgələr daxilində axtarılır.
PRICE_REGIONS = [
    r'id=["\']?corePriceDisplay_desktop_feature_div["\']?',
    r'id=["\']?corePrice_feature_div["\']?',
    r'id=["\']?apex_desktop["\']?',
    r'id=["\']?desktop_buybox["\']?',
]
PRICE_IN_REGION = r'<span class=["\']?a-offscreen["\']?>\s*\$([\d,]+\.\d{2})'

# Amazon-un "satışda deyil" bloku — ən etibarlı siqnal, dildən asılı deyil.
OUT_OF_STOCK_BLOCK = r'id=["\']?outOfStock["\']?'

NAME_PATTERNS = [
    r'id="productTitle"[^>]*>\s*(.*?)\s*</span>',
    r'<title>\s*(?:Amazon\.com\s*:\s*)?(.*?)\s*(?::|</title>)',
]

# DİQQƏT: xam HTML-də stok mətni birbaşa <div id="availability"> içində olur,
# <span> içində DEYİL. Həmçinin "Only N left in stock" ifadəsi səhifənin başqa
# yerlərində DİGƏR məhsullar üçün də keçir — ona görə yalnız bu element oxunur.
AVAILABILITY_BLOCK = r'id=["\']?availability["\']?[^>]*>([\s\S]{0,400}?)</div>'


def parse_amazon(html: str) -> ScrapeResult:
    low = html.lower()

    for marker in BLOCK_MARKERS:
        if marker in low:
            raise BlockedError(f"Bloklama markeri: '{marker}'")

    if "page not found" in low or "looking for something?" in low:
        raise NotFoundError("Səhifə tapılmadı")

    res = ScrapeResult()

    for pat in NAME_PATTERNS:
        m = re.search(pat, html, re.S | re.I)
        if m:
            res.name = _clean(m.group(1))[:200]
            break

    # 1) Buy box JSON dəyəri (ən etibarlısı)
    for pat in PRICE_PATTERNS:
        m = re.search(pat, html, re.S)
        if m:
            try:
                res.price = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                continue

    # 2) Tapılmasa — yalnız qiymət bölgəsi daxilində axtar
    if res.price is None:
        for region_pat in PRICE_REGIONS:
            rm = re.search(region_pat, html, re.I)
            if not rm:
                continue
            region = html[rm.start(): rm.start() + 3000]
            pm = re.search(PRICE_IN_REGION, region, re.S | re.I)
            if pm:
                try:
                    res.price = float(pm.group(1).replace(",", ""))
                    break
                except ValueError:
                    continue

    # Stok mətni — yalnız availability elementindən
    m = re.search(AVAILABILITY_BLOCK, html, re.S | re.I)
    if m:
        text = _clean(m.group(1))
        # Bəzən element boş olur, sonrakı təkrarı yoxlayaq
        if not text:
            for m2 in re.finditer(AVAILABILITY_BLOCK, html, re.S | re.I):
                text = _clean(m2.group(1))
                if text:
                    break
        res.stock = text[:80]

    # Qalan say — YALNIZ stok mətnindən (səhifənin qalanı digər məhsullara aiddir)
    qm = re.search(r"only\s+(\d+)\s+left", res.stock, re.I)
    if qm:
        res.qty = int(qm.group(1))

    # ---- Stok qərarı ----
    # ƏN ETİBARLI SİQNAL: Amazon-un "outOfStock" bloku.
    # Dildən asılı deyil (ispan/alman səhifələrində də eynidir) və buy box
    # boş olanda mütləq görünür.
    if re.search(OUT_OF_STOCK_BLOCK, html, re.I):
        res.in_stock = False
        res.price = None          # buy box qiyməti yoxdur — nə tapılıbsa yaddır
        res.stock = res.stock or "Currently unavailable"
        return res

    # VACİB: OOS markerlərini YALNIZ #availability mətnində axtarırıq.
    # Bütün HTML-də axtarmaq yanlış nəticə verir, çünki "out of stock" ifadəsi
    # digər variantlarda, oxşar məhsullarda və rəylərdə də keçir.
    stock_low = res.stock.lower()

    if any(x in stock_low for x in OOS_MARKERS):
        res.in_stock = False
        if not res.stock:
            res.stock = "Currently unavailable"

    elif res.price is not None:
        # Qiymət var → satışdadır
        res.in_stock = True
        if not res.stock:
            res.stock = "In Stock"

    else:
        # Qiymət yoxdur və availability də aydın deyil.
        # Yalnız bu halda səhifədə açıq-aydın "əlçatmaz" siqnalı axtarırıq.
        hard_oos = ("currently unavailable", "temporarily out of stock",
                    "we don't know when or if this item will be back")
        if any(x in low for x in hard_oos):
            res.in_stock = False
            res.stock = res.stock or "Currently unavailable"
        else:
            # Nə qiymət, nə aydın stok mesajı → bu, stok problemi deyil,
            # oxuma problemidir. Səhv "stok bitdi" bildirişi göndərməyək.
            res.in_stock = True
            res.price = None
            res.stock = res.stock or "Qiymət oxuna bilmədi"
            res.notes.append("price_missing")

    return res


ASIN_PATTERNS = [
    r"/dp/([A-Z0-9]{10})",
    r"/gp/product/([A-Z0-9]{10})",
    r"/product/([A-Z0-9]{10})",
    r"[?&]asin=([A-Z0-9]{10})",
]


def normalize_amazon_url(url: str) -> str:
    """
    Linki təmiz formaya salır: https://www.amazon.com/dp/ASIN

    Niyə lazımdır: sheet-dəki linklərdə `language=es` kimi parametrlər olur və
    səhifə ispan dilində açılır — ingilis stok mətnləri uyğun gəlmir. Həmçinin
    uzun `ref=` parametrləri bəzən başqa variantı açır.
    """
    if not url:
        return url
    for pat in ASIN_PATTERNS:
        m = re.search(pat, url, re.I)
        if m:
            return f"https://www.amazon.com/dp/{m.group(1).upper()}"
    return url


def scrape_amazon(browser: Browser, url: str) -> ScrapeResult:
    url = normalize_amazon_url(url)
    last_err = None
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            html, status = browser.fetch_html(url)
            if status == 404:
                raise NotFoundError("HTTP 404")
            if status in (503, 429):
                raise BlockedError(f"HTTP {status}")
            return parse_amazon(html)
        except (BlockedError, NotFoundError):
            raise
        except Exception as e:  # şəbəkə/timeout — təkrar cəhd
            last_err = e
            if attempt < config.MAX_RETRIES:
                time.sleep(random.randint(5, 12))
    raise RuntimeError(f"Oxuna bilmədi: {last_err}")


# ---------------------------------------------------------------------------
# eBay
# ---------------------------------------------------------------------------

# DİQQƏT: eBay-in xam HTML-ində atributlar DIRNAQSIZ olur (class=x-price-primary).
# Ona görə bütün nümunələrdə dırnaq ixtiyaridir: ["']?
EBAY_PRICE_PATTERNS = [
    r'data-testid=["\']?x-price-primary["\']?[\s\S]{0,400}?\$\s*([\d,]+\.\d{2})',
    r'class=["\']?x-price-primary["\']?[\s\S]{0,400}?\$\s*([\d,]+\.\d{2})',
    r'"value"\s*:\s*\{\s*"value"\s*:\s*([\d.]+)\s*,\s*"currency"\s*:\s*"USD"',
    r'id=["\']?prcIsum["\']?[^>]*>\s*(?:US\s*)?\$\s*([\d,]+\.\d{2})',
    r'itemprop=["\']?price["\']?[^>]*content=["\']?([\d.]+)',
    # Son çarə — səhifədəki ilk "US $..." dəyəri (adətən əsas qiymətdir)
    r'US\s*\$\s*([\d,]+\.\d{2})',
]


# Listinginizdəki qalıq say. "10 available", "More than 10 available",
# "Last one" və s. formatlarında olur.
EBAY_QTY_PATTERNS = [
    r'class=["\']?x-quantity__availability["\']?[\s\S]{0,300}?(More than [\d,]+|[\d,]+)\s+available',
    r'id=["\']?qtySubTxt["\']?[\s\S]{0,200}?(More than [\d,]+|[\d,]+)\s+available',
    r'>\s*(More than [\d,]+|[\d,]+)\s+available\s*<',
    r'"quantityAvailable"\s*:\s*(\d+)',
    r'"availableQuantity"\s*:\s*(\d+)',
    r'(More than [\d,]+|[\d,]+)\s+available',
]

# Listinqin bağlı olduğunu bildirən açıq siqnallar.
# VACİB: bunlar bütün HTML-də deyil, YALNIZ dar sahədə axtarılır — çünki
# "out of stock" ifadəsi məhsulun bir variantı üçün JSON blokunda da keçir
# və bütöv səhifə axtarışı işləyən listinqi səhvən "bağlı" göstərir.
EBAY_ENDED_MARKERS = [
    "this listing has ended",
    "this listing was ended",
    "bidding has ended",
    "listing ended",
]

EBAY_SOLDOUT_NARROW = [
    "out of stock",
    "sold out",
]


def _parse_ebay_price(html: str) -> float | None:
    for pat in EBAY_PRICE_PATTERNS:
        m = re.search(pat, html, re.S | re.I)
        if m:
            try:
                value = float(m.group(1).replace(",", ""))
                if value > 0:
                    return value
            except ValueError:
                continue
    return None


def _ebay_qty_region(html: str) -> str:
    """
    Say/mövcudluq məlumatının olduğu dar sahəni qaytarır.
    Səhifənin qalan hissəsindəki variant JSON-ları yanlış nəticə verir.
    """
    for pat in (
        r'class=["\']?x-quantity__availability["\']?',
        r'id=["\']?qtySubTxt["\']?',
        r'id=["\']?qtySubTxtGrp["\']?',
        r'class=["\']?x-buybox["\']?',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return html[m.start(): m.start() + 1500]
    return ""


def _parse_ebay_qty(html: str) -> int | None:
    """
    eBay listinginizdəki qalıq sayı qaytarır.
    0    -> listinq bitib (birmənalı siqnal)
    None -> oxuna bilmədi (sheet-dəki dəyər saxlanılır)

    NİYƏ BU QƏDƏR EHTİYATLI:
    eBay say modulunu JavaScript ilə çəkir, xam HTML-də çox vaxt olmur.
    Dolayı siqnalların hamısı yalanış nəticə verdi:
      • "out of stock"  -> variant JSON-unda keçir (açıq listinqi bağlı göstərirdi)
      • "Last one"      -> marketinq etiketidir (HotnessSignalText), say deyil
      • x-quantity yoxluğu -> açıq listinqlərdə də olmur
    Ona görə yalnız birmənalı "N available" mətnini qəbul edirik.
    Qalan hallarda None qaytarılır və sheet-dəki (sizin yazdığınız) dəyər qalır.
    """
    low = html.lower()

    # 1) Açıq şəkildə bitmiş listinq
    if any(m in low for m in EBAY_ENDED_MARKERS):
        return 0

    # 2) Yalnız birmənalı say mətni: "3 available" / "More than 10 available"
    for pat in EBAY_QTY_PATTERNS:
        m = re.search(pat, html, re.S | re.I)
        if m:
            digits = re.sub(r"[^\d]", "", m.group(1))
            if digits:
                return int(digits)

    # 3) "Last one" — YALNIZ say modulunun içində olarsa etibarlıdır.
    #    Səhifənin qalan hissəsindəki "LAST ONE" reklam etiketidir.
    region = _ebay_qty_region(html)
    if region and re.search(r"\blast one\b", region, re.I):
        return 1
    if region and any(m in region.lower() for m in EBAY_SOLDOUT_NARROW):
        return 0

    return None


def scrape_ebay_info(browser: Browser, url: str, api_mode: bool = False) -> dict:
    """
    eBay listinginizdən qiymət və qalıq sayı oxuyur.
    Birbaşa alınmasa (eBay-in də bot qoruması var) API kanalına keçir.
    Qaytarır: {"price": float|None, "qty": int|None}
    """
    empty = {"price": None, "qty": None}
    if not url or not url.startswith("http"):
        return empty

    html = None
    if not api_mode:
        try:
            fetched, status = browser.fetch_html(url)
            if status < 400 and fetched:
                html = fetched
        except Exception:
            html = None

    if html is None and config.has_api_fallback():
        html = fetch_via_fallback(url)

    if not html:
        return empty

    return {"price": _parse_ebay_price(html), "qty": _parse_ebay_qty(html)}


# ---------------------------------------------------------------------------
# Ehtiyat kanal — pulsuz scraping API kreditləri
# ---------------------------------------------------------------------------

def fetch_via_fallback(url: str) -> str | None:
    """
    Pulsuz scraping API kreditləri ilə səhifəni gətirir.
    Bu xidmətlər rezident proksi istifadə edir — Amazon bloklamır.
    """
    import urllib.parse
    import urllib.request

    endpoints = []
    if config.SCRAPERAPI_KEY:
        endpoints.append(
            (
                "ScraperAPI",
                "https://api.scraperapi.com/?api_key="
                f"{config.SCRAPERAPI_KEY}&url={urllib.parse.quote(url, safe='')}"
                "&country_code=us",
            )
        )
    if config.SCRAPINGBEE_KEY:
        endpoints.append(
            (
                "ScrapingBee",
                "https://app.scrapingbee.com/api/v1/?api_key="
                f"{config.SCRAPINGBEE_KEY}&url={urllib.parse.quote(url, safe='')}"
                "&render_js=false&country_code=us",
            )
        )

    for name, ep in endpoints:
        try:
            req = urllib.request.Request(
                ep, headers={"User-Agent": random.choice(USER_AGENTS)}
            )
            with urllib.request.urlopen(req, timeout=90) as resp:
                if resp.status == 200:
                    print(f"    ↩️  {name} ilə oxundu")
                    return resp.read().decode("utf-8", errors="ignore")
                print(f"    ⚠️  {name} HTTP {resp.status}")
        except Exception as e:
            print(f"    ⚠️  {name} xətası: {e}")
            continue
    return None


def scrape_amazon_via_api(url: str) -> ScrapeResult:
    """Yalnız API üzərindən oxuyur (birbaşa Amazon-a dəymir)."""
    html = fetch_via_fallback(normalize_amazon_url(url))
    if html is None:
        raise RuntimeError("API kanalı cavab vermədi (kredit bitib ola bilər)")
    return parse_amazon(html)


# ---------------------------------------------------------------------------

def polite_delay(api_mode: bool = False):
    """
    Sorğular arası gecikmə.
    API rejimində uzun gecikməyə ehtiyac yoxdur — provayder özü proksi rotasiyası
    edir və bloklama riski bizim tempimizdən asılı deyil. Bu, işləmə müddətini
    kəskin qısaldır və bir işləmədə daha çox məhsul yoxlamağa imkan verir.
    """
    if api_mode:
        time.sleep(random.uniform(0.5, 2.0))
    else:
        time.sleep(random.uniform(config.DELAY_MIN_SEC, config.DELAY_MAX_SEC))


def _clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
        .replace("&nbsp;", " ")
    )
    return re.sub(r"\s+", " ", text).strip()
