"""
Günlük sağlamlıq hesabatı — sheet-in mövcud vəziyyətini oxuyub Telegram-a xülasə göndərir.
Scraping etmir, ona görə sürətli və risksizdir (API krediti xərcləmir).
"""
from datetime import datetime, timedelta

import config
import notify
import sheets

# Status → (hesabat başlığı, diqqət tələb edirmi)
CATEGORIES = [
    ("OK",         "✅ Qaydasındadır",              False),
    ("QIYMET+",    "📈 Amazon qiyməti artıb",       True),
    ("QIYMET-",    "📉 Amazon qiyməti düşüb",       False),
    ("AZ MARJA",   "⚠️ Marja azdır",                True),
    ("AZ STOK",    "📦 Amazon-da say azalıb",       True),
    ("STOK YOX (eBay bağlı)", "⚪ Stok yox (listing bağlı)", False),
    ("STOK YOX",   "🔴 Amazon-da stok bitib",       True),
    ("TEKRAR AC",  "🟢 Yenidən açıla bilər",        True),
    ("BLOKLANDI",  "🛑 Bloklandı",                  True),
    ("XETA",       "❌ Xəta",                       True),
]


def _categorize(status: str) -> str:
    """Statusu kateqoriyaya salır. Sıra vacibdir — daha spesifik olan öndədir."""
    s = (status or "").strip()
    if not s:
        return "YOXLANMAYIB"
    for key, _, _ in CATEGORIES:
        if s.startswith(key):
            return key
    return "DIGER"


def main():
    ws = sheets.open_sheet()
    values = ws.get_all_values()

    counts = {}
    attention = []   # diqqət tələb edən məhsullar (ad + status)
    stale = 0
    total = 0
    missing_ebay_price = 0

    cutoff = datetime.utcnow() - timedelta(hours=36)
    attention_keys = {k for k, _, need in CATEGORIES if need}

    for raw in values[config.FIRST_DATA_ROW - 1:]:
        padded = raw + [""] * (len(config.HEADERS) - len(raw))
        if not padded[config.COL["amazon_link"] - 1].strip():
            continue
        total += 1

        status = padded[config.COL["status"] - 1].strip()
        key = _categorize(status)
        counts[key] = counts.get(key, 0) + 1

        if key in attention_keys:
            name = padded[config.COL["product_name"] - 1].strip() or "(adsız)"
            attention.append((key, name))

        if not padded[config.COL["ebay_price"] - 1].strip():
            missing_ebay_price += 1

        last = padded[config.COL["last_check"] - 1].strip()
        if not last:
            stale += 1
        else:
            try:
                if datetime.strptime(last[:16], "%Y-%m-%d %H:%M") < cutoff:
                    stale += 1
            except ValueError:
                stale += 1

    notify.send(
        _build_message(counts, attention, total, stale, missing_ebay_price),
        silent=True,
    )
    print({"total": total, "counts": counts, "stale": stale,
           "missing_ebay_price": missing_ebay_price})


def _build_message(counts, attention, total, stale, missing_ebay_price) -> str:
    lines = [f"<b>📊 Günlük hesabat — {total} məhsul</b>", ""]

    shown = 0
    for key, title, _ in CATEGORIES:
        n = counts.get(key, 0)
        if n:
            lines.append(f"{title}: <b>{n}</b>")
            shown += n

    # Kateqoriyaya düşməyənlər (belə olmamalıdır, amma gizlətmirik)
    for extra_key, extra_title in (("YOXLANMAYIB", "⏸ Hələ yoxlanmayıb"),
                                   ("DIGER", "❔ Naməlum status")):
        n = counts.get(extra_key, 0)
        if n:
            lines.append(f"{extra_title}: <b>{n}</b>")
            shown += n

    if shown != total:
        lines.append(f"<i>(sayılmayan: {total - shown})</i>")

    # Diqqət tələb edənlərin adları — hesabatı əməli edir
    if attention:
        lines.append("")
        lines.append("<b>Diqqət tələb edir:</b>")
        for key, name in attention[:12]:
            title = next(t for k, t, _ in CATEGORIES if k == key)
            short = name[:45] + ("…" if len(name) > 45 else "")
            lines.append(f"• {title.split(' ', 1)[1]} — {_esc(short)}")
        if len(attention) > 12:
            lines.append(f"<i>…və daha {len(attention) - 12} məhsul</i>")
    else:
        lines.append("")
        lines.append("<i>Diqqət tələb edən məhsul yoxdur.</i>")

    # Texniki xəbərdarlıqlar
    notes = []
    if missing_ebay_price:
        notes.append(
            f"💲 eBay qiyməti bilinmir: <b>{missing_ebay_price}</b> məhsul "
            f"— marja hesablana bilmir, D sütununu doldura bilərsiniz"
        )
    if stale:
        notes.append(
            f"⏳ 36 saatdan çoxdur yoxlanılmayıb: <b>{stale}</b> məhsul"
        )
    if notes:
        lines.append("")
        lines.extend(notes)

    return "\n".join(lines)


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


if __name__ == "__main__":
    main()
