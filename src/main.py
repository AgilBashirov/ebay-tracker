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
from datetime import datetime, timedelta

import config
import ebay_api
import ebay_write
import notify
import pricing
import scraper
import sheets


class _NoBrowser:
    """API rejimi üçün boş brauzer — Chromium açılmır."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_html(self, url):
        raise RuntimeError("Birbaşa brauzer rejimi aktiv deyil (API rejimindəyik)")


def run(health_report: bool = False) -> int:
    print("=" * 60)
    print("eBay Dropshipping — qiymət/stok yoxlaması")
    print("=" * 60)

    ws = sheets.open_sheet()
    sheets.ensure_structure(ws)

    all_rows = sheets.read_rows(ws)
    print(f"Sheet-də cəmi {len(all_rows)} məhsul var.")

    limit = config.resolve_batch_size(len(all_rows))

    # BATCH_SIZE əl ilə rəqəm kimi verilibsə (Run workflow → "54"), bu, məcburi
    # işləmədir: vaxt intervalına baxmadan ən köhnələrdən başlayaraq yoxlayırıq.
    forced = config.BATCH_SIZE != "auto"

    if forced:
        print(f"⚡ Məcburi işləmə — yoxlama vaxtı nəzərə alınmır. Limit: {limit}")
        batch = sheets.pick_batch(all_rows, limit, force=True)
    else:
        due = sheets.count_due(all_rows)
        print(f"Yoxlama vaxtı çatıb: {due} məhsul (limit: {limit})")
        batch = sheets.pick_batch(all_rows, limit)

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
    ebay_fetches = 0
    auto_actions = []

    # API rejimi: birbaşa Amazon-a dəymirik.
    # "api" seçilibsə əvvəldən, "auto"da isə ilk bloklamadan sonra aktivləşir.
    api_mode = config.SCRAPE_METHOD == "api"
    if api_mode and not config.has_api_fallback():
        print("⚠️  SCRAPE_METHOD=api seçilib, amma API açarı yoxdur — birbaşa rejimə keçilir.")
        api_mode = False
    if api_mode:
        print("🔑 API rejimi aktivdir — Amazon-a birbaşa sorğu getməyəcək.\n")

    # API rejimində brauzerə ehtiyac yoxdur — Chromium açmırıq.
    # Bu, həm sürət qazandırır, həm də Playwright quraşdırılmayıbsa
    # işləmənin çökməsinin qarşısını alır.
    browser_ctx = _NoBrowser() if api_mode else scraper.Browser()

    with browser_ctx as browser:
        for idx, row in enumerate(batch, start=1):
            label = (row["product_name"] or row["amazon_link"])[:60]
            print(f"[{idx}/{len(batch)}] sətir {row['row']}: {label}")

            if not row["amazon_link"].startswith("http"):
                results.append({**_base(row), "status": "XETA link yoxdur",
                                "next_check": _next_check(row, "XETA link yoxdur", False)})
                stats["error"] += 1
                continue

            # --- Amazon ---
            try:
                if api_mode:
                    data = scraper.scrape_amazon_via_api(row["amazon_link"])
                else:
                    data = scraper.scrape_amazon(browser, row["amazon_link"])
                consecutive_blocks = 0

            except scraper.BlockedError as e:
                stats["blocked"] += 1
                block_reason = str(e)
                print(f"    🛑 BLOKLAMA: {e}")

                data = None
                if config.has_api_fallback():
                    # Bu IP bloklanıb — qalan bütün məhsullar üçün API-yə keçirik,
                    # boş yerə Amazon-a dəyməyək.
                    if not api_mode:
                        api_mode = True
                        print("    🔑 Qalan məhsullar API üzərindən oxunacaq.")
                    try:
                        data = scraper.scrape_amazon_via_api(row["amazon_link"])
                        consecutive_blocks = 0
                    except Exception as fe:
                        print(f"    ❌ API də alınmadı: {fe}")

                if data is None:
                    consecutive_blocks += 1
                    results.append({**_base(row), "status": "BLOKLANDI",
                                "next_check": _next_check(row, "BLOKLANDI", False)})
                    if consecutive_blocks >= config.BLOCK_ABORT_THRESHOLD:
                        print("\n🛑 Ardıcıl bloklama həddi keçildi — işləmə dayandırılır.")
                        break
                    scraper.polite_delay(api_mode)
                    continue

            except scraper.NotFoundError:
                print("    ❌ Səhifə tapılmadı (404)")
                results.append({**_base(row), "status": "XETA link ölüdür",
                                "next_check": _next_check(row, "XETA link ölüdür", False)})
                stats["error"] += 1
                scraper.polite_delay(api_mode)
                continue

            except Exception as e:
                print(f"    ❌ Xəta: {e}")
                results.append({**_base(row), "status": "XETA",
                                "next_check": _next_check(row, "XETA", False)})
                stats["error"] += 1
                scraper.polite_delay(api_mode)
                continue

            processed += 1

            # --- eBay qiyməti ---
            # eBay qiyməti + qalıq say.
            # API kreditini qorumaq üçün yalnız qərar ondan asılı olanda oxuyuruq.
            amazon_old = row["amazon_old"]
            amazon_new = data.price
            price_changed = (
                amazon_old is not None and amazon_new is not None
                and abs(amazon_new - amazon_old) >= 0.01
            )

            ebay_price = row["ebay_price"]
            ebay_qty = row["ebay_qty"]

            # --- eBay Browse API (varsa) — ən etibarlı və pulsuz mənbə ---
            if ebay_api.is_configured():
                info = ebay_api.fetch_item(row["ebay_link"])
                if info:
                    if info["price"]:
                        ebay_price = info["price"]
                    if info["qty"] is not None:
                        ebay_qty = info["qty"]
                    dq = "dəqiq" if info["qty_exact"] else f"≥{info['qty']}"
                    print(f"    eBay API: qiymət {_m(ebay_price)} · "
                          f"say {ebay_qty} ({dq}) · {info['status']}")
                else:
                    print("    ⚠️  eBay API cavab vermədi — sheet dəyəri saxlanılır")

                # API qiymət vermədisə (variasiyalı listinq və s.) səhifədən oxuyaq
                if ebay_price is None:
                    fb = scraper.scrape_ebay_info(
                        browser, row["ebay_link"], api_mode=api_mode)
                    if fb["price"]:
                        ebay_price = fb["price"]
                        print(f"    ↩️  eBay qiyməti səhifədən: {_m(ebay_price)}")
                    ebay_fetches += 1

            elif sheets.should_fetch_ebay(row, data.in_stock, price_changed):
                if not api_mode:
                    scraper.polite_delay(api_mode)
                info = scraper.scrape_ebay_info(
                    browser, row["ebay_link"], api_mode=api_mode
                )
                if info["price"]:
                    ebay_price = info["price"]
                # Say yalnız "scrape" rejimində scraper-dən götürülür.
                # Defolt rejimdə E sütunundakı sizin dəyəriniz qorunur.
                if info["qty"] is not None:
                    ebay_qty = info["qty"]
                if info["price"] is None and info["qty"] is None:
                    print("    ⚠️  eBay səhifəsi oxuna bilmədi "
                          "(D/E sütunlarını əl ilə doldura bilərsiniz)")
                else:
                    print(f"    eBay: qiymət {_m(ebay_price)} · qalıq {ebay_qty}")
                ebay_fetches += 1
            else:
                print(f"    eBay: sheet-dən (qiymət {_m(ebay_price)} · qalıq {ebay_qty})")

            # --- Hesablama ---
            m_usd, m_pct = pricing.margin(ebay_price, amazon_new)
            fees = pricing.total_fees(ebay_price) if ebay_price else None
            suggested = pricing.suggest_ebay_price(ebay_price, amazon_old, amazon_new)
            status, should_alert, reason = pricing.classify(
                ebay_price, amazon_old, amazon_new, data.in_stock, m_pct,
                ebay_qty, data.qty
            )

            next_check = _next_check(row, status, price_changed)

            print(
                f"    Amazon: {_m(amazon_old)} → {_m(amazon_new)} | "
                f"{data.stock} | haqq {_m(fees)} | marja {_m(m_usd)} | {status}"
            )

            record = {
                "row": row["row"],
                "product_name": data.name or row["product_name"],
                "ebay_price": ebay_price,
                "ebay_qty": ebay_qty,
                "amazon_old": amazon_old,
                "amazon_new": amazon_new,
                "stock": data.stock,
                "ebay_fee": fees,
                "margin_usd": m_usd,
                "margin_pct": m_pct,
                "suggested_ebay": suggested,
                "next_check": next_check,
                "status": status,
                "reason": reason,
                "amazon_qty": data.qty,
            }
            results.append(record)

            if not data.in_stock:
                stats["oos"] += 1
            elif status == "OK":
                stats["ok"] += 1
            else:
                stats["changed"] += 1

            # --- Avtomatik sayı sıfırlama (Amazon-da stok bitibsə) ---
            if (reason == pricing.REASON_OUT_OF_STOCK
                    and config.AUTO_ZERO_QTY
                    and ebay_write.is_configured()
                    and config.auto_allowed(row.get("auto"))):
                item_id = ebay_api.extract_item_id(row["ebay_link"])
                res = ebay_write.zero_out(item_id, ebay_qty, config.AUTO_DRY_RUN)
                if res["done"]:
                    ebay_qty = 0
                    record["ebay_qty"] = 0
                    print(f"    ✅ eBay sayı 0 edildi ({item_id})")
                elif res["skipped"]:
                    print(f"    ⏭  Sayı sıfırlamadım: {res['skipped']}")
                else:
                    print(f"    🧪 {res['message']}")
                auto_actions.append({
                    "name": record["product_name"], "item_id": item_id,
                    "qty_before": row.get("ebay_qty"),
                    **res,
                })

            if should_alert:
                alerts.append(
                    {
                        **record,
                        "ebay_link": row["ebay_link"],
                        "amazon_link": row["amazon_link"],
                    }
                )

            if idx < len(batch):
                scraper.polite_delay(api_mode)

    # --- Sheet-i yenilə ---
    print(f"\nSheet yenilənir ({len(results)} sətir)...")
    sheets.write_results(ws, results)

    # --- Bildirişlər ---
    if alerts:
        print(f"Telegram-a {len(alerts)} bildiriş göndərilir...")
        notify.send(notify.format_alerts(alerts))

    if auto_actions:
        notify.send(notify.format_auto_actions(auto_actions, config.AUTO_DRY_RUN))
    else:
        print("Dəyişiklik yoxdur — Telegram bildirişi göndərilmir.")

    if block_reason:
        remaining = len(batch) - processed
        lost = sum(1 for r in results if r.get("status") == "BLOKLANDI")
        if lost > 0:
            # Yalnız məhsul həqiqətən oxuna bilməyəndə bildiriş göndəririk.
            notify.send(notify.format_blocked(processed, remaining, block_reason, lost))
        else:
            # Ehtiyat kanal hər şeyi əhatə edib — bu, gündəlik normal haldır,
            # Telegram-ı doldurmağa dəyməz. Yalnız loga yazılır.
            print("ℹ️  Amazon birbaşa girişi bloklandı, API kanalı ilə tamamlandı "
                  "(itki yoxdur — bildiriş göndərilmir).")

    if health_report:
        notify.send(notify.format_health(stats), silent=True)

    print("\n" + "=" * 60)
    print(f"Bitdi. {stats}")
    if api_mode or stats["blocked"]:
        used = processed + ebay_fetches
        print(f"API kredit istifadəsi (təxmini): {used} "
              f"({processed} Amazon + {ebay_fetches} eBay)")
    print("=" * 60)
    return 0


def _next_check(row, status: str, price_changed: bool) -> str:
    """Məhsulun növbəti yoxlama vaxtını hesablayır (sheet-in N sütunu)."""
    prev = sheets.previous_interval_days(row)
    days = pricing.next_interval_days(status, price_changed, prev)
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")


def _base(row):
    return {
        "row": row["row"],
        "product_name": row["product_name"],
        "ebay_price": row["ebay_price"],
        "ebay_qty": row.get("ebay_qty"),
        "amazon_old": row["amazon_old"],
        "amazon_new": None,
        "stock": "",
        "margin_usd": None,
        "margin_pct": None,
        "suggested_ebay": None,
        "ebay_fee": None,
        "auto": row.get("auto", ""),
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
    except Exception as exc:
        traceback.print_exc()
        try:
            notify.send(notify.format_run_error(exc))
        except Exception:
            pass
        sys.exit(1)
