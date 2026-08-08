"""
Günlük sağlamlıq hesabatı — sheet-in mövcud vəziyyətini oxuyub Telegram-a xülasə göndərir.
Scraping etmir, ona görə sürətli və risksizdir.
"""
from datetime import datetime, timedelta

import config
import notify
import sheets


def main():
    ws = sheets.open_sheet()
    rows = sheets.read_rows(ws)

    values = ws.get_all_values()
    stats = {"ok": 0, "changed": 0, "oos": 0, "error": 0,
             "blocked": 0, "total": len(rows), "stale": 0}

    cutoff = datetime.utcnow() - timedelta(hours=36)

    for raw in values[config.FIRST_DATA_ROW - 1:]:
        padded = raw + [""] * (len(config.HEADERS) - len(raw))
        if not padded[config.COL["amazon_link"] - 1].strip():
            continue

        status = padded[config.COL["status"] - 1].strip().upper()
        last = padded[config.COL["last_check"] - 1].strip()

        if status.startswith("STOK YOX"):
            stats["oos"] += 1
        elif status.startswith("BLOKLANDI"):
            stats["blocked"] += 1
        elif status.startswith("XETA"):
            stats["error"] += 1
        elif status.startswith("QIYMET") or status.startswith("AZ MARJA"):
            stats["changed"] += 1
        elif status.startswith("OK"):
            stats["ok"] += 1

        if last:
            try:
                dt = datetime.strptime(last[:16], "%Y-%m-%d %H:%M")
                if dt < cutoff:
                    stats["stale"] += 1
            except ValueError:
                stats["stale"] += 1
        else:
            stats["stale"] += 1

    text = notify.format_health(stats)
    if stats["stale"]:
        text += (
            f"\n\n⏳ 36 saatdan çoxdur yoxlanılmayıb: <b>{stats['stale']}</b> məhsul"
            "\n<i>BATCH_SIZE artırmaq lazım ola bilər.</i>"
        )
    notify.send(text, silent=True)
    print(stats)


if __name__ == "__main__":
    main()
