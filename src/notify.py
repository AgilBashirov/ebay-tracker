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


REASON_TITLES = {
    "OUT_OF_STOCK": "🔴 AMAZON-DA STOK BİTİB",
    "LOW_QTY":      "📦 AMAZON-DA SAY SİZDƏKİNDƏN AZDIR",
    "PRICE_RISE":   "📈 AMAZON QİYMƏTİ BAHALAŞDI",
    "PRICE_DROP":   "📉 AMAZON QİYMƏTİ UCUZLAŞDI",
    "RESTOCK":      "🟢 AMAZON-A QAYIDIB",
    "LOW_MARGIN":   "⚠️ MARJA AZDIR",
}


def format_alerts(alerts: list[dict]) -> str:
    """
    Telegram mesajı. Hər məhsul üçün YALNIZ bildirişin səbəbi və ona aid
    faktlar yazılır — artıq məlumat yoxdur.
    """
    lines = [f"<b>Bildiriş — {len(alerts)} məhsul</b>", ""]

    for a in alerts:
        reason = a.get("reason") or ""
        name = _e(a.get("product_name") or "Adsız məhsul")
        if len(name) > 65:
            name = name[:62] + "..."

        lines.append(REASON_TITLES.get(reason, "ℹ️ DƏYİŞİKLİK"))
        lines.append(f"<b>{name}</b>")

        # ---- 1) Stok bitib ----
        if reason == "OUT_OF_STOCK":
            lines.append(f"   Amazon: {_e(a.get('stock')) or 'əlçatmaz'}")
            eq = a.get("ebay_qty")
            if eq:
                lines.append(f"   eBay-də hələ <b>{eq}</b> ədəd satışdadır")
            lines.append("   💡 Listinqi dayandırın və ya başqa təchizatçı tapın")

        # ---- 2) Amazon sayı azdır ----
        elif reason == "LOW_QTY":
            aq, eq = a.get("amazon_qty"), a.get("ebay_qty")
            lines.append(f"   Amazon-da qalıb: <b>{aq}</b> ədəd")
            lines.append(f"   Sizin eBay sayınız: <b>{eq}</b> ədəd")
            lines.append(f"   💡 eBay sayını <b>{aq}</b>-ə salın "
                         f"({eq - aq} sifarişi çatdıra bilməzsiniz)")

        # ---- 3) Qiymət bahalaşıb ----
        elif reason in ("PRICE_RISE", "PRICE_DROP"):
            old, new = a.get("amazon_old"), a.get("amazon_new")
            if old is not None and new is not None:
                diff = new - old
                pct = (diff / old * 100) if old else 0
                lines.append(
                    f"   Amazon: {_money(old)} → <b>{_money(new)}</b> "
                    f"({'+' if diff > 0 else ''}{diff:,.2f} / {pct:+.1f}%)"
                )
            ebay = a.get("ebay_price")
            m_usd, m_pct = a.get("margin_usd"), a.get("margin_pct")
            if ebay is not None:
                lines.append(f"   Sizin eBay qiyməti: {_money(ebay)}")
            if m_usd is not None:
                lines.append(f"   Yeni marja: <b>{_money(m_usd)}</b> ({m_pct:.1f}%)")
            sug = a.get("suggested_ebay")
            if sug is not None and ebay is not None and abs(sug - ebay) >= 0.01:
                lines.append(f"   💡 <b>Tövsiyə: eBay qiymətini {_money(sug)} edin</b>")

        # ---- Digər (defolt bağlıdır, amma açılarsa) ----
        else:
            if a.get("amazon_new") is not None:
                lines.append(f"   Amazon: <b>{_money(a['amazon_new'])}</b>")
            m_usd, m_pct = a.get("margin_usd"), a.get("margin_pct")
            if m_usd is not None:
                lines.append(f"   Marja: {_money(m_usd)} ({m_pct:.1f}%)")
            sug = a.get("suggested_ebay")
            if sug is not None:
                lines.append(f"   💡 Tövsiyə olunan qiymət: {_money(sug)}")

        links = []
        if a.get("ebay_link"):
            links.append(f'<a href="{_e(a["ebay_link"])}">eBay</a>')
        if a.get("amazon_link"):
            links.append(f'<a href="{_e(a["amazon_link"])}">Amazon</a>')
        if links:
            lines.append("🔗 " + " · ".join(links))

        lines.append("")

    return "\n".join(lines).strip()


def format_blocked(checked: int, remaining: int, reason: str, lost: int = 0) -> str:
    # Ehtiyat kanal hər şeyi əhatə edibsə — bu problem deyil, sadəcə məlumatdır.
    if lost == 0 and config.has_api_fallback():
        return (
            "<b>ℹ️ Məlumat: API kanalı istifadə olundu</b>\n\n"
            f"Amazon birbaşa girişi blokladı, yoxlama API üzərindən tamamlandı.\n"
            f"Yoxlanılan məhsul: <b>{checked}</b> · İtirilən: <b>0</b>\n\n"
            "<i>Hər şey qaydasındadır, tədbir tələb olunmur.</i>"
        )

    base = (
        "<b>🛑 Amazon bloklaması aşkarlandı</b>\n\n"
        f"Səbəb: <code>{_e(reason)}</code>\n"
        f"Yoxlanıldı: <b>{checked}</b> · Oxuna bilmədi: <b>{lost}</b> · "
        f"Növbəyə qaldı: <b>{remaining}</b>\n\n"
    )
    if config.has_api_fallback():
        return base + (
            "Ehtiyat API kanalı da cavab vermədi — kredit bitmiş ola bilər. "
            "Provayder panelində qalan kredite baxın."
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


def format_auto_actions(actions: list[dict], dry_run: bool) -> str:
    """Avtomatik say sıfırlama əməliyyatlarının hesabatı."""
    if dry_run:
        head = ("<b>🧪 QURU REJİM — heç nə dəyişdirilmədi</b>\n\n"
                "Real rejimdə bunlar edilə bilərdi:")
    else:
        head = "<b>🤖 eBay listinqlərində avtomatik dəyişiklik</b>"

    lines = [head, ""]
    for a in actions:
        name = _e((a.get("name") or "Adsız")[:55])
        if a.get("done"):
            lines.append(f"✅ <b>{name}</b>")
            lines.append(f"   eBay sayı {a.get('qty_before')} → <b>0</b> edildi")
        elif a.get("skipped"):
            lines.append(f"⏭ <b>{name}</b>")
            lines.append(f"   Toxunulmadı: {_e(a['skipped'])}")
        else:
            lines.append(f"🧪 <b>{name}</b>")
            lines.append(f"   Say {a.get('qty_before')} → 0 ediləcəkdi")
        lines.append("")

    if dry_run:
        lines.append("<i>Razısınızsa AUTO_DRY_RUN dəyişənini 0 edin.</i>")
    return "\n".join(lines).strip()
