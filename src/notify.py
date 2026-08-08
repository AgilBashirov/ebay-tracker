"""
Telegram bildirişləri — Bot API üzərindən birbaşa.
GitHub Actions serverlərindən api.telegram.org əlçatandır.
"""
import html
import json
import urllib.parse
import urllib.request

import config

API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_LEN = 3900  # Telegram limiti 4096, ehtiyat saxlayırıq


def send(text: str, silent: bool = False) -> bool:
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[notify] Telegram konfiqurasiyası yoxdur, bildiriş atlandı.")
        return False

    ok = True
    for chunk in _split(text):
        payload = urllib.parse.urlencode(
            {
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
                "disable_notification": "true" if silent else "false",
            }
        ).encode()
        try:
            req = urllib.request.Request(
                API.format(token=config.TELEGRAM_TOKEN), data=payload
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
                if not body.get("ok"):
                    print(f"[notify] Telegram xətası: {body}")
                    ok = False
        except Exception as e:
            print(f"[notify] Göndərilə bilmədi: {e}")
            ok = False
    return ok


def _split(text: str):
    if len(text) <= MAX_LEN:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MAX_LEN:
            parts.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        parts.append(current)
    return parts


# ---------------------------------------------------------------------------
# Mesaj formatları
# ---------------------------------------------------------------------------

def _e(text) -> str:
    return html.escape(str(text if text is not None else ""))


def _money(v):
    return "—" if v is None else f"${v:,.2f}"


def format_alerts(alerts: list[dict]) -> str:
    """alerts: main.py-dan gələn dəyişiklik siyahısı."""
    lines = ["<b>⚠️ Qiymət / stok dəyişikliyi</b>", ""]

    for a in alerts:
        name = _e(a.get("product_name") or "Adsız məhsul")
        if len(name) > 70:
            name = name[:67] + "..."

        lines.append(f"<b>{name}</b>")

        if a["status"].startswith("STOK YOX"):
            lines.append("🔴 <b>Amazon-da STOK BİTİB</b>")
            lines.append(f"   Stok: {_e(a.get('stock'))}")
            lines.append("   💡 eBay listingini dayandırın və ya başqa təchizatçı tapın")
        else:
            old, new = a.get("amazon_old"), a.get("amazon_new")
            if old is not None and new is not None:
                diff = new - old
                arrow = "📈" if diff > 0 else "📉"
                pct = (diff / old * 100) if old else 0
                lines.append(
                    f"{arrow} Amazon: {_money(old)} → <b>{_money(new)}</b> "
                    f"({'+' if diff > 0 else ''}{diff:,.2f} / {pct:+.1f}%)"
                )
            else:
                lines.append(f"Amazon: <b>{_money(new)}</b>")

            ebay = a.get("ebay_price")
            m_usd, m_pct = a.get("margin_usd"), a.get("margin_pct")
            if ebay is not None:
                lines.append(f"🏷 Sizin eBay: {_money(ebay)}")
            if m_usd is not None:
                warn = " ⚠️" if (m_pct is not None and m_pct < config.MARGIN_ALERT_PCT) else ""
                lines.append(f"💰 Marja: {_money(m_usd)} ({m_pct:.1f}%){warn}")

            sug = a.get("suggested_ebay")
            if sug is not None and ebay is not None and abs(sug - ebay) >= 0.01:
                lines.append(
                    f"💡 <b>Tövsiyə: eBay qiymətini {_money(sug)} edin</b> "
                    f"(marjanı qorumaq üçün)"
                )

        links = []
        if a.get("ebay_link"):
            links.append(f'<a href="{_e(a["ebay_link"])}">eBay</a>')
        if a.get("amazon_link"):
            links.append(f'<a href="{_e(a["amazon_link"])}">Amazon</a>')
        if links:
            lines.append("🔗 " + " · ".join(links))

        lines.append("")

    return "\n".join(lines).strip()


def format_blocked(checked: int, remaining: int, reason: str) -> str:
    base = (
        "<b>🛑 Amazon bloklaması aşkarlandı</b>\n\n"
        f"Səbəb: <code>{_e(reason)}</code>\n"
        f"Bu işləmədə yoxlanıldı: <b>{checked}</b> məhsul\n"
        f"Növbəyə qaldı: <b>{remaining}</b> məhsul\n\n"
    )
    if config.has_api_fallback():
        return base + (
            "Ehtiyat API kanalı işə düşdü. Qalan məhsullar oradan oxunur — "
            "heç nə itmir."
        )
    return base + (
        "⚠️ <b>Ehtiyat API açarı təyin edilməyib.</b>\n"
        "GitHub server IP-lərini Amazon bloklayır. Həll üçün "
        "<code>SCRAPERAPI_KEY</code> və/və ya <code>SCRAPINGBEE_KEY</code> "
        "secret-lərini əlavə edin (pulsuz kredit verirlər)."
    )


def format_health(stats: dict) -> str:
    return (
        "<b>📊 Günlük hesabat</b>\n\n"
        f"✅ Uğurlu: <b>{stats.get('ok', 0)}</b>\n"
        f"⚠️ Dəyişiklik: <b>{stats.get('changed', 0)}</b>\n"
        f"🔴 Stok yox: <b>{stats.get('oos', 0)}</b>\n"
        f"❌ Xəta: <b>{stats.get('error', 0)}</b>\n"
        f"🛑 Bloklama: <b>{stats.get('blocked', 0)}</b>\n\n"
        f"Ümumi məhsul sayı: <b>{stats.get('total', 0)}</b>"
    )
