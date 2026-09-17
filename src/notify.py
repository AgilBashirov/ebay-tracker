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
            if a.get("auto_applied"):
                lines.append("   🤖 <i>Qiymət avtomatik tənzimləndi</i>")
            else:
                sug = a.get("suggested_ebay")
                if sug is not None and ebay is not None and abs(sug - ebay) >= 0.01:
                    lines.append(
                        f"   💡 <b>Tövsiyə: eBay qiymətini {_money(sug)} edin</b>")

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
    """eBay listinqlərində edilən (və ya ediləcək) avtomatik dəyişikliklər."""
    if dry_run:
        head = ("<b>🧪 QURU REJİM — heç nə dəyişdirilmədi</b>\n\n"
                "Real rejimdə bunlar edilə bilərdi:")
    else:
        head = "<b>🤖 eBay listinqlərində avtomatik dəyişiklik</b>"

    lines = [head, ""]
    for a in actions:
        name = _e((a.get("name") or "Adsız")[:55])
        qb, qa = a.get("qty_before"), a.get("qty_after")
        pb, pa = a.get("price_before"), a.get("price_after")
        plan = a.get("plan") or {}

        if a.get("skipped"):
            lines.append(f"⏭ <b>{name}</b>")
            lines.append(f"   Toxunulmadı: {_e(a['skipped'])}")
            lines.append("")
            continue

        lines.append(("✅ " if a.get("done") else "🧪 ") + f"<b>{name}</b>")

        # --- Say ---
        if qa is not None and qa != qb:
            if qa == 0:
                lines.append(f"   📦 Say <b>{qb} → 0</b> (satışdan çıxarıldı, "
                             f"listinq açıq qalır)")
            elif qb in (0, None):
                lines.append(f"   📦 Say <b>{qb if qb is not None else '—'} → {qa}</b> "
                             f"(yenidən satışa qoyuldu)")
            else:
                lines.append(f"   📦 Say <b>{qb} → {qa}</b>")

        # --- Qiymət ---
        if pa is not None and pb is not None:
            arrow = "📈" if pa > pb else "📉"
            lines.append(f"   {arrow} Qiymət <b>{_money(pb)} → {_money(pa)}</b>")
            if plan.get("new_profit") is not None:
                lines.append(f"   💵 Təmiz qazanc: <b>{_money(plan['new_profit'])}</b> "
                             f"(hədəf {_money(plan.get('target_profit'))})")
        elif a.get("message") and not a.get("done"):
            lines.append(f"   {_e(a['message'].replace('[QURU REJİM] ', ''))}")

        if plan.get("capped"):
            lines.append("   ⚠️ Təhlükəsizlik həddi tətbiq olundu "
                         "(bir dəfəyə maksimum dəyişiklik)")
        lines.append("")

    if dry_run:
        lines.append("<i>Razısınızsa AUTO_DRY_RUN dəyişənini 0 edin.</i>")
    return "\n".join(lines).strip()


def format_low_profit(items: list[dict]) -> str:
    """Qiymət qaldırılsa da hədəf qazanca çatmayan məhsullar."""
    lines = ["<b>⚠️ Bu məhsullar artıq az qazanc verir</b>", ""]
    for it in items:
        name = _e((it.get("name") or "Adsız")[:55])
        lines.append(f"<b>{name}</b>")
        lines.append(f"   Amazon: {_money(it.get('amazon_price'))} · "
                     f"eBay: {_money(it.get('current_price'))}")
        if it.get("new_price"):
            lines.append(f"   Yeni qiymət: <b>{_money(it['new_price'])}</b> → "
                         f"qazanc {_money(it.get('new_profit'))} "
                         f"(hədəf {_money(it.get('target'))})")
        else:
            lines.append(f"   Cari qazanc: <b>{_money(it.get('current_profit'))}</b> "
                         f"(hədəf {_money(it.get('target'))})")
            lines.append(f"   ⛔ Avtomatik düzəliş edilmədi — "
                         f"{_e(it.get('reason', ''))}")
        links = []
        if it.get("ebay_link"):
            links.append(f'<a href="{_e(it["ebay_link"])}">eBay</a>')
        if it.get("amazon_link"):
            links.append(f'<a href="{_e(it["amazon_link"])}">Amazon</a>')
        if links:
            lines.append("🔗 " + " · ".join(links))
        lines.append("")
    lines.append("<i>Başqa təchizatçı axtarmaq və ya listinqi dayandırmaq "
                 "barədə düşünə bilərsiniz.</i>")
    return "\n".join(lines).strip()


def _short(name, n=34):
    name = (name or "Adsız").strip()
    return _e(name if len(name) <= n else name[:n - 1] + "…")


def format_run_summary(checked: int, total: int, actions: list[dict],
                       alerts: list[dict], low_profit: list[dict],
                       dry_run: bool, blocked: int = 0,
                       block_reason: str | None = None) -> str:
    """
    Bir işləmənin YEGANƏ Telegram mesajı — qısa və konkret.

    Əvvəllər eyni işləmədə 4-5 ayrı mesaj gedirdi (bildirişlər, avtomatik
    əməliyyatlar, az qazanc, bloklama). İndi hamısı burada birləşir.
    Dəyişiklik və diqqət tələb edən hal yoxdursa boş sətir qaytarılır —
    yəni heç nə göndərilmir.
    """
    qiymet, say, maneə = [], [], []

    for a in actions:
        if a.get("skipped"):
            maneə.append(f"• {_short(a.get('name'))} — {_e(a['skipped'])}")
            continue
        nm = _short(a.get("name"))
        qb, qa = a.get("qty_before"), a.get("qty_after")
        pb, pa = a.get("price_before"), a.get("price_after")
        plan = a.get("plan") or {}

        if dry_run and not a.get("done"):
            # Quru rejim: nə ediləcəyi mətn kimi gəlir
            msg = (a.get("message") or "").replace("[QURU REJİM] ", "")
            if msg:
                qiymet.append(f"• {nm} — {_e(msg)}")
            continue

        if pa is not None and pb is not None:
            ox = "↑" if pa > pb else "↓"
            qazanc = plan.get("new_profit")
            son = f" · qazanc {_money(qazanc)}" if qazanc is not None else ""
            qiymet.append(f"• {nm} — {_money(pb)} {ox} <b>{_money(pa)}</b>{son}")

        if qa is not None and qa != qb:
            if qa == 0:
                say.append(f"• {nm} — {qb} → <b>0</b> (Amazon-da bitib)")
            elif qb in (0, None):
                say.append(f"• {nm} — {qb if qb is not None else '—'} → "
                           f"<b>{qa}</b> (satışa qayıtdı)")
            else:
                say.append(f"• {nm} — {qb} → <b>{qa}</b>")

    # Diqqət tələb edənlər: sistemin həll edə bilmədikləri
    toxunulan = {(_short(a.get("name"))) for a in actions}
    diqqet = []
    for lp in low_profit:
        diqqet.append(f"• {_short(lp.get('name'))} — qazanc "
                      f"{_money(lp.get('current_profit'))}, "
                      f"hədəf {_money(lp.get('target'))} tutmur")
    for al in alerts:
        nm = _short(al.get("product_name"))
        if nm in toxunulan:
            continue           # avtomatika onsuz da həll etdi
        title = {"OUT_OF_STOCK": "Amazon-da stok bitib",
                 "LOW_QTY": "Amazon-da say azdır",
                 "PRICE_RISE": "Amazon bahalaşdı"}.get(al.get("reason"))
        if title:
            diqqet.append(f"• {nm} — {title}")

    if not (qiymet or say or diqqet or maneə or blocked):
        return ""

    bas = ("🧪 <b>Quru rejim</b> — heç nə dəyişdirilmədi"
           if dry_run else "<b>eBay yoxlaması</b>")
    lines = [f"{bas}  ·  {checked}/{total} məhsul", ""]

    def blok(basliq, items, limit=6):
        if not items:
            return
        lines.append(f"<b>{basliq} ({len(items)})</b>")
        lines.extend(items[:limit])
        if len(items) > limit:
            lines.append(f"<i>… və {len(items) - limit} daha</i>")
        lines.append("")

    blok("📈 Qiymət", qiymet)
    blok("📦 Say", say)
    blok("⚠️ Diqqət", diqqet)
    blok("⛔ Toxunulmadı", maneə, 4)

    if blocked:
        lines.append(f"🛑 Amazon {blocked} məhsulu blokladı — "
                     f"növbəti işləmədə təkrar yoxlanacaq")
        lines.append("")

    if dry_run:
        lines.append("<i>Tətbiq etmək üçün AUTO_DRY_RUN = 0</i>")

    return "\n".join(lines).strip()


def format_could_lower(items: list[dict]) -> str:
    """
    Qazancı həddən xeyli çox olan məhsullar.
    Bu, PROBLEM DEYİL — sadəcə istəsəniz ucuzlaşdırıb daha rəqabətli
    ola biləcəyiniz məhsulların siyahısıdır. Sistem özü toxunmur.
    """
    lines = ["<b>💡 İstəsəniz ucuzlaşdıra bilərsiniz</b>",
             "<i>Bunlar həddən yaxşı qazandırır — sistem toxunmadı. "
             "Rəqabət üçün aşağı salmaq istəsəniz:</i>", ""]
    for it in items[:15]:
        name = _e((it.get("name") or "Adsız")[:48])
        lines.append(f"<b>{name}</b>")
        lines.append(f"   {_money(it.get('current_price'))} → "
                     f"{_money(it.get('suggested'))}  ·  qazanc "
                     f"{_money(it.get('current_profit'))} → "
                     f"~{_money(it.get('floor'))}")
        if it.get("ebay_link"):
            lines.append(f'   🔗 <a href="{_e(it["ebay_link"])}">eBay</a>')
        lines.append("")
    if len(items) > 15:
        lines.append(f"<i>… və daha {len(items) - 15} məhsul</i>")
    lines.append("<i>Avtomatik ucuzlaşdırma istəyirsinizsə: "
                 "AUTO_PRICE_ALLOW_DOWN = 1</i>")
    return "\n".join(lines).strip()


# Müvəqqəti (bizdən asılı olmayan) nasazlıq əlamətləri
TRANSIENT_HINTS = [
    "503", "502", "500", "504", "429",
    "currently unavailable", "internal error", "timed out", "timeout",
    "connection reset", "temporarily unavailable", "rate limit",
]


def format_run_error(exc: Exception) -> str:
    """
    İşləmə xətası haqqında bildiriş.
    Müvəqqəti nasazlıqla (Google/eBay tərəfdə) real problemi ayırd edir ki,
    hər kiçik kəsintidə narahat olmayasınız.
    """
    text = f"{exc.__class__.__name__}: {exc}"
    transient = any(h in text.lower() for h in TRANSIENT_HINTS)

    if transient:
        return (
            "<b>⏳ İşləmə yarımçıq qaldı — müvəqqəti nasazlıq</b>\n\n"
            f"<code>{_e(text[:180])}</code>\n\n"
            "Bu, xidmət provayderinin (Google Sheets / eBay) qısamüddətli "
            "kəsintisidir, koddakı problem deyil.\n"
            "<i>Növbəti işləmə avtomatik davam edəcək — tədbir tələb olunmur.</i>"
        )

    return (
        "<b>❌ Script xətası</b>\n\n"
        f"<code>{_e(text[:180])}</code>\n\n"
        "Bu, təkrarlanan problem ola bilər. GitHub Actions loglarına baxın."
    )
