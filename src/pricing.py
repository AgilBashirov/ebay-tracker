"""
eBay haqları, marja və tövsiyə olunan qiymət.

Model ebayfeescalculator.com ilə eynidir:

    vergi        = (satış + göndərmə haqqı) × vergi%
    haqq bazası  = satış + göndərmə haqqı + vergi
    FVF          = baza × FVF%
    reklam       = baza × reklam%
    beynəlxalq   = baza × 1.65%   (yalnız xaricə satışda)
    əməliyyat    = $0.40  (sifariş ≤ $10 olduqda $0.30)

    mənfəət      = satış + göndərmə haqqı − məhsul xərci − göndərmə xərci − haqlar
    marja %      = mənfəət / satış qiyməti

Vacib nüans: satış vergisi alıcıdan alınır və sizə çatmır, AMMA eBay haqqı
məhz vergi daxil bazadan hesablanır. Yəni vergi sizin xərcinizi artırır.
"""
import math

import config


# ---------------------------------------------------------------------------
# Haqlar
# ---------------------------------------------------------------------------

def order_fee(sold_price: float, shipping_charged: float = 0.0) -> float:
    """Sifariş başına sabit əməliyyat haqqı."""
    total = sold_price + shipping_charged
    if total <= config.EBAY_ORDER_FEE_THRESHOLD:
        return config.EBAY_ORDER_FEE_LOW
    return config.EBAY_ORDER_FEE


def fee_breakdown(sold_price: float, shipping_charged: float | None = None) -> dict:
    """Bütün eBay haqlarını ayrı-ayrı qaytarır."""
    if shipping_charged is None:
        shipping_charged = config.SHIPPING_CHARGED

    gross = sold_price + shipping_charged
    tax = gross * config.SALES_TAX_PCT / 100
    base = gross + tax

    fvf = base * config.EBAY_FVF_PCT / 100
    ads = base * config.EBAY_AD_RATE_PCT / 100
    intl = base * config.EBAY_INTERNATIONAL_PCT / 100
    per_order = order_fee(sold_price, shipping_charged)

    total = fvf + ads + intl + per_order
    return {
        "sales_tax": round(tax, 2),
        "fee_base": round(base, 2),
        "fvf": round(fvf, 2),
        "ads": round(ads, 2),
        "international": round(intl, 2),
        "order_fee": round(per_order, 2),
        "total": round(total, 2),
    }


def total_fees(sold_price: float, shipping_charged: float | None = None) -> float:
    return fee_breakdown(sold_price, shipping_charged)["total"]


def net_after_fees(sold_price: float) -> float:
    """Haqlar çıxıldıqdan sonra əlinizə çatan məbləğ (geriyə uyğunluq üçün)."""
    return sold_price + config.SHIPPING_CHARGED - total_fees(sold_price)


# ---------------------------------------------------------------------------
# Marja
# ---------------------------------------------------------------------------

def margin(ebay_price: float | None, amazon_price: float | None):
    """(marja $, marja %) qaytarır. Məlumat çatmırsa (None, None)."""
    if ebay_price is None or amazon_price is None or ebay_price <= 0:
        return None, None
    profit = (
        ebay_price
        + config.SHIPPING_CHARGED
        - amazon_price
        - config.SHIPPING_COST
        - total_fees(ebay_price)
    )
    return round(profit, 2), round(profit / ebay_price * 100, 2)


def margin_details(ebay_price: float | None, amazon_price: float | None) -> dict | None:
    """Marja + haqların tam bölgüsü (bildirişdə göstərmək üçün)."""
    if ebay_price is None or amazon_price is None or ebay_price <= 0:
        return None
    fees = fee_breakdown(ebay_price)
    profit = (
        ebay_price + config.SHIPPING_CHARGED
        - amazon_price - config.SHIPPING_COST - fees["total"]
    )
    return {
        **fees,
        "profit": round(profit, 2),
        "margin_pct": round(profit / ebay_price * 100, 2),
    }


# ---------------------------------------------------------------------------
# Tövsiyə olunan qiymət
# ---------------------------------------------------------------------------

def _fee_coefficient() -> float:
    """
    Satış qiymətinin faiz kimi gedən hissəsi.
    (1 + vergi%) × (FVF% + reklam% + beynəlxalq%)
    """
    rate = (
        config.EBAY_FVF_PCT
        + config.EBAY_AD_RATE_PCT
        + config.EBAY_INTERNATIONAL_PCT
    ) / 100
    return (1 + config.SALES_TAX_PCT / 100) * rate


def price_for_profit(target_profit: float, amazon_price: float) -> float | None:
    """
    Verilmiş dollar mənfəəti üçün lazım olan eBay qiymətini həll edir.

        mənfəət = (P + S)·(1 − k) − C − Sc − sifariş_haqqı
        =>  P = (mənfəət + C + Sc + sifariş_haqqı) / (1 − k) − S
    """
    k = _fee_coefficient()
    if k >= 1:
        return None
    s = config.SHIPPING_CHARGED
    # Sifariş haqqı qiymətdən asılıdır — iki dəfə hesablayıb dəqiqləşdiririk
    fee = config.EBAY_ORDER_FEE
    for _ in range(3):
        p = (target_profit + amazon_price + config.SHIPPING_COST + fee) / (1 - k) - s
        fee = order_fee(p, s)
    return p


def price_for_margin_pct(target_pct: float, amazon_price: float) -> float | None:
    """Verilmiş FAİZ marjasını verən eBay qiymətini həll edir."""
    k = _fee_coefficient()
    t = target_pct / 100
    denom = 1 - k - t
    if denom <= 0:
        return None
    s = config.SHIPPING_CHARGED
    fee = config.EBAY_ORDER_FEE
    for _ in range(3):
        p = (amazon_price + config.SHIPPING_COST + fee - s * (1 - k)) / denom
        fee = order_fee(p, s)
    return p


def suggest_ebay_price(
    ebay_price: float | None,
    amazon_old: float | None,
    amazon_new: float | None,
) -> float | None:
    """
    Tövsiyə olunan yeni eBay qiyməti.

    İki şərti eyni anda ödəyir:
      1. Əvvəlki dollar mənfəətini qoruyur (və ya TARGET_MARGIN_PCT-ə çatır)
      2. Marja minimum həddin (MARGIN_ALERT_PCT) altına düşmür

    İkinci şərt vacibdir: marja onsuz da aşağı olanda köhnə (pis) mənfəəti
    qorumaq mənasızdır — təklif praktiki olaraq mövcud qiymətlə eyni çıxırdı.
    Bu halda təklif həddi bərpa edən qiyməti göstərir.
    """
    if amazon_new is None:
        return None

    candidates = []

    if config.TARGET_MARGIN_PCT > 0:
        p = price_for_margin_pct(config.TARGET_MARGIN_PCT, amazon_new)
        if p:
            candidates.append(p)
    elif ebay_price is not None:
        base_amazon = amazon_old if amazon_old is not None else amazon_new
        old_profit, _ = margin(ebay_price, base_amazon)
        if old_profit is not None:
            p = price_for_profit(max(old_profit, 0.0), amazon_new)
            if p:
                candidates.append(p)

    # Minimum marja həddi — təklif heç vaxt bundan aşağı olmamalıdır
    if config.MARGIN_ALERT_PCT > 0:
        floor_price = price_for_margin_pct(config.MARGIN_ALERT_PCT, amazon_new)
        if floor_price:
            candidates.append(floor_price)

    if not candidates:
        return None
    return _round_price(max(candidates))


def _round_price(value: float) -> float:
    """
    .99 ilə bitən ən yaxın (aşağı olmayan) dəyər.
    Sentlə işləyirik — float müqayisəsi (32.99 % 1 = 0.990000000000002)
    qiyməti səhvən bir dollar yuxarı qaldırırdı.
    """
    if config.PRICE_ROUNDING != "99":
        return round(value, 2)
    cents = round(value * 100)
    target = math.ceil((cents - 99) / 100) * 100 + 99
    return target / 100


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

# Bildiriş səbəbləri — Telegram mesajının başlığını bunlar müəyyən edir.
REASON_PRICE_RISE = "PRICE_RISE"
REASON_LOW_QTY = "LOW_QTY"
REASON_OUT_OF_STOCK = "OUT_OF_STOCK"
REASON_PRICE_DROP = "PRICE_DROP"
REASON_LOW_MARGIN = "LOW_MARGIN"
REASON_RESTOCK = "RESTOCK"

_REASON_FLAGS = {
    REASON_PRICE_RISE: "ALERT_ON_PRICE_RISE",
    REASON_LOW_QTY: "ALERT_ON_LOW_QTY",
    REASON_OUT_OF_STOCK: "ALERT_ON_OUT_OF_STOCK",
    REASON_PRICE_DROP: "ALERT_ON_PRICE_DROP",
    REASON_LOW_MARGIN: "ALERT_ON_LOW_MARGIN",
    REASON_RESTOCK: "ALERT_ON_RESTOCK",
}


def _alert_enabled(reason: str | None) -> bool:
    if reason is None:
        return False
    return bool(getattr(config, _REASON_FLAGS[reason], False))


def classify(
    ebay_price: float | None,
    amazon_old: float | None,
    amazon_new: float | None,
    in_stock: bool,
    margin_pct: float | None,
    ebay_qty: int | None = None,
    amazon_qty: int | None = None,
) -> tuple[str, bool, str | None]:
    """
    (sheet_statusu, bildiriş_getsin_mi, səbəb) qaytarır.

    PRİORİTET SIRASI — bir sətir üçün yalnız bir status olur:
      1. Amazon-da stok yoxdur
      2. Amazon-dakı say sizin eBay sayınızdan azdır
      3. Amazon qiyməti artıb
      4. Amazon qiyməti düşüb        (bildiriş defolt BAĞLI)
      5. eBay listinqi bağlıdır      (bildiriş defolt BAĞLI)
      6. Marja həddin altındadır     (bildiriş defolt BAĞLI)
      7. OK

    ebay_qty yalnız SİZİN E sütununa yazdığınız dəyərdir (təxmin edilmir).
    amazon_qty yalnız Amazon "Only N left in stock" yazanda bilinir.
    """
    ebay_closed = ebay_qty is not None and ebay_qty <= 0

    # ---- 1) Amazon-da stok yoxdur -------------------------------------------
    if not in_stock:
        if ebay_closed:
            # Sizin listinq onsuz da bağlıdır — tədbir tələb olunmur.
            return "STOK YOX (eBay bağlı)", False, None
        return "STOK YOX", _alert_enabled(REASON_OUT_OF_STOCK), REASON_OUT_OF_STOCK

    # ---- Məlumat çatmırsa, səssiz status -------------------------------------
    if amazon_new is None:
        return "XETA Amazon qiyməti yoxdur", False, None

    # ---- 2) Amazon sayı < sizin eBay sayınız ---------------------------------
    if (amazon_qty is not None and ebay_qty is not None
            and ebay_qty > 0 and amazon_qty < ebay_qty):
        return "AZ STOK", _alert_enabled(REASON_LOW_QTY), REASON_LOW_QTY

    # ---- 3/4) Qiymət dəyişikliyi ---------------------------------------------
    if amazon_old is not None:
        diff = amazon_new - amazon_old
        pct = (diff / amazon_old * 100) if amazon_old else 0
        if diff >= config.PRICE_RISE_MIN_USD or pct >= config.PRICE_RISE_MIN_PCT:
            return "QIYMET+ artdı", _alert_enabled(REASON_PRICE_RISE), REASON_PRICE_RISE
        if diff <= -config.PRICE_RISE_MIN_USD or pct <= -config.PRICE_RISE_MIN_PCT:
            return "QIYMET- düşdü", _alert_enabled(REASON_PRICE_DROP), REASON_PRICE_DROP

    # ---- 5) Sizin listinq bağlıdır, Amazon-da isə var -------------------------
    if ebay_closed:
        return "TEKRAR AC", _alert_enabled(REASON_RESTOCK), REASON_RESTOCK

    # ---- 6) Marja həddin altında ----------------------------------------------
    if ebay_price is None:
        return "XETA eBay qiyməti yoxdur", False, None
    if margin_pct is not None and margin_pct < config.MARGIN_ALERT_PCT:
        return "AZ MARJA", _alert_enabled(REASON_LOW_MARGIN), REASON_LOW_MARGIN

    return "OK", False, None


# ---------------------------------------------------------------------------
# Növbəti yoxlama vaxtı — kredit qənaətinin əsası
# ---------------------------------------------------------------------------

def next_interval_days(status: str, price_changed: bool, prev_interval: float) -> float:
    """
    Məhsulun növbəti dəfə nə vaxt yoxlanacağını müəyyən edir.

    Məntiq:
      • qiymət dəyişib          -> 1 gün (yaxından izlə)
      • diqqət tələb edir       -> 1 gün
      • xəta / ölü link         -> 7 gün (kredit yandırmayaq)
      • bloklandı               -> ~2 saat (başqa IP ilə təkrar)
      • sabit və qaydasındadır  -> aralıq tədricən artır (1 → 2 → 3 gün)
    """
    s = status or ""
    if s.startswith("BLOKLANDI"):
        return config.BLOCKED_INTERVAL_DAYS
    if s.startswith("XETA"):
        return config.ERROR_INTERVAL_DAYS
    if s.startswith(("STOK YOX (eBay bağlı)",)):
        return config.ERROR_INTERVAL_DAYS / 2   # passiv məhsul, seyrək yoxla
    if s.startswith(("AZ MARJA", "AZ STOK", "STOK YOX", "TEKRAR AC", "QIYMET")):
        return config.ATTENTION_INTERVAL_DAYS
    if price_changed:
        return config.CHECK_INTERVAL_DAYS

    grown = max(prev_interval, config.CHECK_INTERVAL_DAYS) + 1
    return min(grown, config.MAX_INTERVAL_DAYS)
