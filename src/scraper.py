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

# Sıra vacibdir: "priceAmount" Amazon-un buy-box JSON dəyəridir — ən etibarlısı.
# a-offscreen sonuncudur, çünki bəzən reklam bloklarının qiymətini tuta bilər.
PRICE_PATTERNS = [
    r'"priceAmount"\s*:\s*([\d.]+)',
    r'id="priceblock_ourprice"[^>]*>\s*\$([\d,]+\.\d{2})',
    r'"displayPrice"\s*:\s*"\$([\d,]+\.\d{2})"',
    r'data-a-color="price"[^>]*>\s*<span class="a-offscreen">\$([\d,]+\.\d{2})',
    r'<span class="a-offscreen">\s*\$([\d,]+\.\d{2})\s*</span>',
]

NAME_PATTERNS = [
    r'id="productTitle"[^>]*>\s*(.*?)\s*</span>',
    r'<title>\s*(?:Amazon\.com\s*:\s*)?(.*?)\s*(?::|</title>)',
]

STOCK_PATTERNS = [
    r'id="availability"[^>]*>.*?<span[^>]*>\s*(.*?)\s*</span>',
    r'(Only \d+ left in stock[^<]*)',
    r'>\s*(In Stock)\s*<',
]


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

    for pat in PRICE_PATTERNS:
        m = re.search(pat, html, re.S)
        if m:
            try:
                res.price = float(m.group(1).replace(",", ""))
                break
            except ValueError:
                continue

    for pat in STOCK_PATTERNS:
        m = re.search(pat, html, re.S | re.I)
        if m:
            res.stock = _clean(m.group(1))[:80]
            break

    # ---- Stok qərarı ----
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


def scrape_amazon(browser: Browser, url: str) -> ScrapeResult:
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

EBAY_PRICE_PATTERNS = [
    r'"price"\s*:\s*\{\s*"value"\s*:\s*"?([\d.]+)',
    r'itemprop="price"[^>]*content="([\d.]+)"',
    r'id="prcIsum"[^>]*>\s*(?:US\s*)?\$([\d,]+\.\d{2})',
    r'class="x-price-primary"[^>]*>.*?\$([\d,]+\.\d{2})',
    r'"binPrice"\s*:\s*"?\$?([\d,]+\.\d{2})',
]


# Listinginizdəki qalıq say. "10 available", "More than 10 available",
# "Last one" və s. formatlarında olur.
EBAY_QTY_PATTERNS = [
    r'class="x-quantity__availability"[^>]*>.*?(?:<span[^>]*>)?\s*(More than [\d,]+|[\d,]+)\s+available',
    r'id="qtySubTxt"[^>]*>.*?(More than [\d,]+|[\d,]+)\s+available',
    r'"quantityAvailable"\s*:\s*(\d+)',
    r'"availableQuantity"\s*:\s*(\d+)',
    r'>\s*(More than [\d,]+|[\d,]+)\s+available\s*<',
]

EBAY_SOLDOUT_MARKERS = [
    "out of stock",
    "this listing has ended",
    "this listing was ended",
    "no longer available",
    "item is out of stock",
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


def _parse_ebay_qty(html: str) -> int | None:
    """
    eBay listinginizdəki qalıq sayı qaytarır.
    0  -> satışda deyil / bitib
    None -> oxuna bilmədi (qərar verərkən "naməlum" kimi baxılır)
    """
    low = html.lower()

    if any(m in low for m in EBAY_SOLDOUT_MARKERS):
        return 0

    if re.search(r"\blast one\b", low):
        return 1

    for pat in EBAY_QTY_PATTERNS:
        m = re.search(pat, html, re.S | re.I)
        if m:
            raw = m.group(1)
            digits = re.sub(r"[^\d]", "", raw)
            if digits:
                qty = int(digits)
                # "More than 10 available" -> ən azı 11, biz 10-dan çox kimi qeyd edirik
                return qty
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
    html = fetch_via_fallback(url)
    if html is None:
        raise RuntimeError("API kanalı cavab vermədi (kredit bitib ola bilər)")
    return parse_amazon(html)


# ---------------------------------------------------------------------------

def polite_delay():
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
