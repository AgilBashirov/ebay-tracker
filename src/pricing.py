"""
Marja hesablaması və yeni eBay qiyməti təklifi.

Marja = eBay satış qiyməti − eBay komissiyası − Amazon alış qiyməti
"""
import math

import config


def net_after_fees(ebay_price: float) -> float:
    """eBay komissiyası çıxıldıqdan sonra əlinizə çatan məbləğ."""
    return ebay_price * (1 - config.EBAY_FEE_PCT / 100)


def margin(ebay_price: float | None, amazon_price: float | None):
    """(marja $, marja %) qaytarır. Məlumat çatmırsa (None, None)."""
    if ebay_price is None or amazon_price is None or ebay_price <= 0:
        return None, None
    profit = net_after_fees(ebay_price) - amazon_price
    pct = profit / ebay_price * 100
    return round(profit, 2), round(pct, 2)


def suggest_ebay_price(
    ebay_price: float | None,
    amazon_old: float | None,
    amazon_new: float | None,
) -> float | None:
    """
    Yeni eBay qiymətini hesablayır.

    TARGET_MARGIN_PCT = 0  -> əvvəlki marjanı ($ olaraq) qoruyur
    TARGET_MARGIN_PCT > 0  -> hədəf faiz marjasına görə hesablayır
    """
    if amazon_new is None:
        return None

    fee = config.EBAY_FEE_PCT / 100

    if config.TARGET_MARGIN_PCT > 0:
        # net = ebay*(1-fee); marja% = (net - amazon)/ebay
        # => ebay = amazon / (1 - fee - target)
        denom = 1 - fee - config.TARGET_MARGIN_PCT / 100
        if denom <= 0:
            return None
        suggested = amazon_new / denom
    else:
        if ebay_price is None:
            return None
        base_amazon = amazon_old if amazon_old is not None else amazon_new
        old_profit = net_after_fees(ebay_price) - base_amazon
        if old_profit <= 0:
            # Əvvəlcədən zərərdə idi — heç olmasa sıfıra çıxaraq
            old_profit = 0.0
        suggested = (amazon_new + old_profit) / (1 - fee)

    return _round_price(suggested)


def _round_price(value: float) -> float:
    """
    Qiyməti .99 ilə bitən ən yaxın (aşağı olmayan) dəyərə yuvarlaqlaşdırır.
    Sentlə işləyirik — float müqayisəsi 32.99 % 1 = 0.990000000000002 kimi
    xətalar verir və qiyməti səhvən bir dollar yuxarı qaldırırdı.
    """
    if config.PRICE_ROUNDING != "99":
        return round(value, 2)

    cents = round(value * 100)
    target = math.ceil((cents - 99) / 100) * 100 + 99
    return target / 100


def classify(
    ebay_price: float | None,
    amazon_old: float | None,
    amazon_new: float | None,
    in_stock: bool,
    margin_pct: float | None,
    ebay_qty: int | None = None,
) -> tuple[str, bool]:
    """
    (status_etiketi, bildiriş_lazımdır) qaytarır.

    eBay qalıq sayı nəzərə alınır:
      eBay 0  + Amazon yoxdur -> bildiriş YOX (listing artıq bağlıdır, tədbir lazım deyil)
      eBay 0  + Amazon var    -> bildiriş VAR (yenidən satışa çıxarmaq imkanı)
      eBay >0 + Amazon yoxdur -> bildiriş VAR (təcili: listingi dayandırın)
    """
    ebay_closed = ebay_qty is not None and ebay_qty <= 0

    if not in_stock:
        if ebay_closed:
            # Listing onsuz da bağlıdır — narahat etməyə ehtiyac yoxdur.
            return "STOK YOX (eBay bağlı)", False
        return "STOK YOX", config.ALERT_ON_OUT_OF_STOCK

    # Amazon-da var, sizin listing bağlıdır → satış imkanı
    if ebay_closed:
        return "TEKRAR AC", True

    # Qiymət oxuna bilməyibsə bu stok problemi deyil — səhv bildiriş göndərməyək.
    if amazon_new is None:
        return "XETA qiymət oxunmadı", False

    if amazon_old is not None and amazon_new is not None:
        diff = amazon_new - amazon_old
        pct = (diff / amazon_old * 100) if amazon_old else 0

        if diff >= config.PRICE_RISE_MIN_USD or pct >= config.PRICE_RISE_MIN_PCT:
            return "QIYMET+ artdı", True

        if diff <= -config.PRICE_RISE_MIN_USD or pct <= -config.PRICE_RISE_MIN_PCT:
            return "QIYMET- düşdü", config.ALERT_ON_PRICE_DROP

    if margin_pct is not None and margin_pct < config.MARGIN_ALERT_PCT:
        return "AZ MARJA", True

    return "OK", False
