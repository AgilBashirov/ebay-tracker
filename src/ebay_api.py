"""
eBay Browse API — listinq qiyməti və qalıq sayı.

NİYƏ API, SCRAPING DEYİL:
eBay səhifəsində qalıq say yalnız 10-dan az olanda göstərilir. Yoxlanılan
6 listinqdən 4-də say nə HTML-də, nə də səhifədə var idi — yəni scraping
ilə bu məlumatı almaq mümkün deyil. API isə həmişə cavab verir.

ÜSTÜNLÜKLƏRİ:
  • Pulsuz — gündə 5,000 sorğu
  • İstifadəçi icazəsi (OAuth razılıq ekranı) TƏLƏB ETMİR — yalnız 2 açar
  • ScraperAPI krediti xərclənmir
  • Qiyməti də verir, yəni eBay scraping-i tamamilə əvəz edir

Sənəd: developer.ebay.com/api-docs/buy/browse/resources/item/methods/getItemByLegacyId
"""
import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import config

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
ITEM_URL = "https://api.ebay.com/buy/browse/v1/item/get_item_by_legacy_id"
SCOPE = "https://api.ebay.com/oauth/api_scope"

# Token 2 saat etibarlıdır — bir işləmə ərzində bir dəfə alırıq.
_token_cache = {"value": None, "expires_at": 0.0}


def is_configured() -> bool:
    return bool(config.EBAY_CLIENT_ID and config.EBAY_CLIENT_SECRET)


def extract_item_id(url: str) -> str | None:
    """eBay linkindən listinq nömrəsini çıxarır: /itm/157968828656 -> 157968828656"""
    if not url:
        return None
    for pat in (r"/itm/(?:[^/]+/)?(\d{9,15})", r"[?&]item=(\d{9,15})"):
        m = re.search(pat, url)
        if m:
            return m.group(1)
    return None


def _get_token() -> str | None:
    now = time.time()
    if _token_cache["value"] and now < _token_cache["expires_at"]:
        return _token_cache["value"]

    creds = f"{config.EBAY_CLIENT_ID}:{config.EBAY_CLIENT_SECRET}".encode()
    basic = base64.b64encode(creds).decode()
    body = urllib.parse.urlencode(
        {"grant_type": "client_credentials", "scope": SCOPE}
    ).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        token = data.get("access_token")
        if not token:
            print(f"[ebay_api] Token alınmadı: {data}")
            return None
        _token_cache["value"] = token
        _token_cache["expires_at"] = now + int(data.get("expires_in", 7200)) - 120
        return token
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:200]
        print(f"[ebay_api] Token xətası {e.code}: {detail}")
    except Exception as e:
        print(f"[ebay_api] Token xətası: {e}")
    return None


def fetch_item(url_or_id: str) -> dict | None:
    """
    Listinq məlumatını qaytarır:
      {"price": float|None, "qty": int|None, "qty_exact": bool, "status": str|None}

    qty_exact=False o deməkdir ki, eBay dəqiq say vermir, yalnız "N-dən çox"
    deyir — bu halda qty həmin astana dəyəridir (ən azı bu qədər var).
    """
    if not is_configured():
        return None

    item_id = url_or_id if str(url_or_id).isdigit() else extract_item_id(url_or_id)
    if not item_id:
        return None

    token = _get_token()
    if not token:
        return None

    req = urllib.request.Request(
        f"{ITEM_URL}?legacy_item_id={item_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "X-EBAY-C-MARKETPLACE-ID": config.EBAY_MARKETPLACE,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"price": None, "qty": 0, "qty_exact": True,
                    "status": "NOT_FOUND"}
        print(f"[ebay_api] {item_id}: HTTP {e.code}")
        return None
    except Exception as e:
        print(f"[ebay_api] {item_id}: {e}")
        return None

    return _parse_item(data)


def _parse_item(data: dict) -> dict:
    price = None
    try:
        price = float(data["price"]["value"])
    except (KeyError, TypeError, ValueError):
        pass

    qty, exact, status = None, False, None
    for av in data.get("estimatedAvailabilities") or []:
        status = av.get("estimatedAvailabilityStatus") or status

        if av.get("estimatedAvailableQuantity") is not None:
            qty = int(av["estimatedAvailableQuantity"])
            exact = True
            break

        if av.get("estimatedRemainingQuantity") is not None:
            qty = int(av["estimatedRemainingQuantity"])
            exact = True
            break

        # Dəqiq say verilmir, yalnız "N-dən çox" deyilir
        if av.get("availabilityThreshold") is not None:
            qty = int(av["availabilityThreshold"])
            exact = False

    if status == "OUT_OF_STOCK":
        qty, exact = 0, True

    return {"price": price, "qty": qty, "qty_exact": exact, "status": status}
