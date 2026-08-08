"""
Əsas icraçı.

Hər işləmədə:
  1. Sheet-dən bütün məhsulları oxuyur (dinamik — 54 da olsa 500 də)
  2. Ən köhnə yoxlanılan BATCH_SIZE qədərini seçir
  3. Amazon (və lazımsa eBay) qiymətini oxuyur — yavaş, təsadüfi templə
  4. Marja hesablayır, yeni eBay qiyməti təklif edir
  5. Sheet-i yeniləyir və rəngləyir
  6. Yalnız dəyişiklik varsa Telegram-a bildiriş göndərir
  7. Bloklama olarsa dayanır + xəbərdarlıq göndərir; qalanlar növbəti işləməyə qalır
"""
import argparse
import sys
import traceback

import config
import notify
import pricing
import scraper
import sheets


def run(health_report: bool = False) -> int:
    print("=" * 60)
    print("eBay Dropshipping — qiymət/stok yoxlaması")
    print("=" * 60)

    ws = sheets.open_sheet()
    sheets.ensure_structure(ws)

    all_rows = sheets.read_rows(ws)
    print(f"Sheet-də cəmi {len(all_rows)} məhsul var.")

    batch = sheets.pick_batch(all_rows, config.BATCH_SIZE)
    print(f"Bu işləmədə yoxlanacaq: {len(batch)} məhsul.\n")

    if not batch:
        print("Yoxlanacaq məhsul yoxdur.")
        return 0

    results, alerts = [], []
    stats = {"ok": 0, "changed": 0, "oos": 0, "error": 0, "blocked": 0,
             "total": len(all_rows)}
    consecutive_blocks = 0
    block_reason = None
    processed = 0

    with scraper.Browser() as browser:
        for idx, row in enumerate(batch, start=1):
            label = (row["product_name"] or row["amazon_link"])[:60]
            print(f"[{idx}/{len(batch)}] sətir {row['row']}: {label}")

            if not row["amazon_link"].startswith("http"):
                results.append({**_base(row), "status": "XETA link yoxdur"})
                stats["error"] += 1
                continue

            # --- Amazon ---
            try:
                data = scraper.scrape_amazon(browser, row["amazon_link"])
                consecutive_blocks = 0

            except scraper.BlockedError as e:
                consecutive_blocks += 1
                stats["blocked"] += 1
                block_reason = str(e)
                print(f"    🛑 BLOKLAMA: {e}")

                html_fb = scraper.fetch_via_fallback(row["amazon_link"])
                if html_fb:
                    try:
                        data = scraper.parse_amazon(html_fb)
                        consecutive_blocks = 0
                        print("    ↩️  Ehtiyat kanal işlədi.")
                    except Exception:
                        data = None
                else:
                    data = None

                if data is None:
                    results.append({**_base(row), "status": "BLOKLANDI"})
                    if consecutive_blocks >= config.BLOCK_ABORT_THRESHOLD:
                        print("\n🛑 Ardıcıl bloklama həddi keçildi — işləmə dayandırılır.")
                        break
                    scraper.polite_delay()
                    continue

            except scraper.NotFoundError:
                print("    ❌ Səhifə tapılmadı (404)")
                results.append({**_base(row), "status": "XETA link ölüdür"})
                stats["error"] += 1
                scraper.polite_delay()
                continue

            except Exception as e:
                print(f"    ❌ Xəta: {e}")
                results.append({**_base(row), "status": "XETA"})
                stats["error"] += 1
                scraper.polite_delay()
                continue

            processed += 1

            # --- eBay qiyməti ---
            ebay_price = row["ebay_price"]
            if config.EBAY_PRICE_SOURCE == "scrape" and sheets.needs_ebay_refresh(row):
                scraper.polite_delay()
                fetched = scraper.scrape_ebay_price(browser, row["ebay_link"])
                if fetched:
                    ebay_price = fetched
                    print(f"    eBay qiyməti oxundu: ${fetched:,.2f}")

            # --- Hesablama ---
            amazon_old = row["amazon_old"]
            amazon_new = data.price

            m_usd, m_pct = pricing.margin(ebay_price, amazon_new)
            suggested = pricing.suggest_ebay_price(ebay_price, amazon_old, amazon_new)
            status, should_alert = pricing.classify(
                ebay_price, amazon_old, amazon_new, data.in_stock, m_pct
            )

            print(
                f"    Amazon: {_m(amazon_old)} → {_m(amazon_new)} | "
                f"{data.stock} | marja {_m(m_usd)} | {status}"
            )

            record = {
                "row": row["row"],
                "product_name": data.name or row["product_name"],
                "ebay_price": ebay_price,
                "amazon_old": amazon_old,
                "amazon_new": amazon_new,
                "stock": data.stock,
                "margin_usd": m_usd,
                "margin_pct": m_pct,
                "suggested_ebay": suggested,
                "status": status,
            }
            results.append(record)

            if not data.in_stock:
                stats["oos"] += 1
            elif status == "OK":
                stats["ok"] += 1
            else:
                stats["changed"] += 1

            if should_alert:
                alerts.append(
                    {
                        **record,
                        "ebay_link": row["ebay_link"],
                        "amazon_link": row["amazon_link"],
                    }
                )

            if idx < len(batch):
                scraper.polite_delay()

    # --- Sheet-i yenilə ---
    print(f"\nSheet yenilənir ({len(results)} sətir)...")
    sheets.write_results(ws, results)

    # --- Bildirişlər ---
    if alerts:
        print(f"Telegram-a {len(alerts)} bildiriş göndərilir...")
        notify.send(notify.format_alerts(alerts))
    else:
        print("Dəyişiklik yoxdur — Telegram bildirişi göndərilmir.")

    if block_reason:
        remaining = len(batch) - processed
        notify.send(notify.format_blocked(processed, remaining, block_reason))

    if health_report:
        notify.send(notify.format_health(stats), silent=True)

    print("\n" + "=" * 60)
    print(f"Bitdi. {stats}")
    print("=" * 60)
    return 0


def _base(row):
    return {
        "row": row["row"],
        "product_name": row["product_name"],
        "ebay_price": row["ebay_price"],
        "amazon_old": row["amazon_old"],
        "amazon_new": None,
        "stock": "",
        "margin_usd": None,
        "margin_pct": None,
        "suggested_ebay": None,
    }


def _m(v):
    return "—" if v is None else f"${v:,.2f}"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--health-report",
        action="store_true",
        help="İşləmənin sonunda günlük sağlamlıq hesabatı göndər",
    )
    args = parser.parse_args()

    try:
        sys.exit(run(health_report=args.health_report))
    except Exception:
        traceback.print_exc()
        try:
            notify.send(
                "<b>❌ Script xətası</b>\n\n"
                "Yoxlama işləməsi tamamlana bilmədi. "
                "GitHub Actions loglarına baxın."
            )
        except Exception:
            pass
        sys.exit(1)
