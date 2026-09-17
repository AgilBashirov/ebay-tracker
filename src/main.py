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
import sys
import traceback
from datetime import datetime, timedelta

# Windows-da konsol cp1252-dir və Azərbaycan hərflərini çap edə bilmir.
# GitHub Actions-da UTF-8-dir, amma öz kompüterinizdə işlətsəniz çökərdi.
for _stream in (sys.stdout, sys.stderr):
    try:
        if (_stream.encoding or "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config
import ebay_api
import ebay_write
import notify
import pricing
import scraper
import sheets


# Hesabata düşməməli olan "normal" səbəblər — bunlar problem deyil.
NOISE_SKIPS = {"dəyişiklik lazım deyil"}


class _NoBrowser:
    """API rejimi üçün boş brauzer — Chromium açılmır."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_html(self, url):
        raise RuntimeError("Birbaşa brauzer rejimi aktiv deyil (API rejimindəyik)")


def run() -> int:
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
    low_profit = []
    could_lower = []

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
            # Qiymət bu işləmədə eBay-dən oxundumu? Köhnə sheet dəyəri ilə
            # avtomatik qiymət dəyişikliyi etmək təhlükəlidir.
            ebay_price_fresh = False

            # --- eBay Browse API (varsa) — ən etibarlı və pulsuz mənbə ---
            if ebay_api.is_configured():
                info = ebay_api.fetch_item(row["ebay_link"])
                if info:
                    if info["price"]:
                        ebay_price = info["price"]
                        ebay_price_fresh = True
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
                        ebay_price_fresh = True
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
                    ebay_price_fresh = True
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
                ebay_qty, data.qty, margin_usd=m_usd
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

            # --- AVTOMATİK İDARƏETMƏ (say + qiymət) ---
            # Bütün məhsullara tətbiq olunur — sheet-də icazə sütunu yoxdur.
            if ebay_write.is_configured():
                item_id = ebay_api.extract_item_id(row["ebay_link"])

                # 1) Say planı
                want_qty = None
                if config.AUTO_QTY:
                    want_qty = pricing.desired_qty(data.in_stock, data.qty)
                elif config.AUTO_ZERO_QTY and not data.in_stock:
                    want_qty = 0   # köhnə rejim: yalnız sıfırlama

                # 2) Qiymət planı
                plan = None
                want_price = None
                if config.AUTO_PRICE:
                    if not ebay_price_fresh:
                        # Sheet-dəki qiymət köhnəlmiş ola bilər — əlinizlə
                        # dəyişdiyiniz qiyməti səhvən geri qaytarmayaq.
                        print("    💲 Qiymətə toxunulmadı: eBay qiyməti bu "
                              "işləmədə oxunmayıb")
                    else:
                        plan = pricing.plan_price_change(
                            ebay_price, amazon_new, data.in_stock)
                        want_price = plan["new_price"]
                        if want_price is None and plan["reason"]:
                            print(f"    💲 Qiymət toxunulmadı: {plan['reason']}")

                if want_qty is not None or want_price is not None:
                    res = ebay_write.apply_changes(
                        item_id, ebay_qty, ebay_price,
                        want_qty, want_price, config.AUTO_DRY_RUN)

                    if res["done"]:
                        print(f"    ✅ eBay yeniləndi: {res['message']}")
                        if res["qty_after"] is not None:
                            ebay_qty = res["qty_after"]
                            record["ebay_qty"] = ebay_qty
                        if res["price_after"] is not None:
                            ebay_price = res["price_after"]
                            record["ebay_price"] = ebay_price
                            # Qiymət dəyişdi — marja və haqları yenidən hesabla
                            m_usd, m_pct = pricing.margin(ebay_price, amazon_new)
                            record["margin_usd"] = m_usd
                            record["margin_pct"] = m_pct
                            record["ebay_fee"] = pricing.total_fees(ebay_price)
                        # Bot vəziyyəti düzəltdi — status da yenilənməlidir,
                        # əks halda sheet-də "AZ QAZANC" qalır, halbuki həll olunub.
                        status, should_alert, reason = pricing.classify(
                            ebay_price, amazon_old, amazon_new, data.in_stock,
                            m_pct, ebay_qty, data.qty, margin_usd=m_usd)
                        record["status"] = status
                        record["reason"] = reason
                        record["next_check"] = _next_check(
                            row, status, price_changed)
                    elif res["skipped"] and res["skipped"] not in NOISE_SKIPS:
                        print(f"    ⏭  Toxunulmadı: {res['skipped']}")
                    elif res["message"]:
                        print(f"    🧪 {res['message']}")

                    # Hesabata YALNIZ real hadisə düşür:
                    #   • dəyişiklik edildi
                    #   • quru rejimdə ediləcəkdi
                    #   • qoruyucu maneə oldu (izah lazımdır)
                    # "dəyişiklik lazım deyil" normal haldır — Telegram-ı
                    # hər işləmədə onlarla belə sətirlə doldurmaq olmaz.
                    if res["done"] or res["message"] or (
                            res["skipped"] and res["skipped"] not in NOISE_SKIPS):
                        auto_actions.append({
                            "name": record["product_name"], "item_id": item_id,
                            "plan": plan, **res,
                        })

                # Qazanc həddən xeyli çoxdursa — məcburiyyət yoxdur, amma
                # istəsəniz ucuzlaşdırıb rəqabəti artıra bilərsiniz.
                if plan and plan.get("could_lower") and not plan.get("new_price"):
                    could_lower.append({
                        "name": record["product_name"],
                        "current_price": ebay_price,
                        "current_profit": plan.get("current_profit"),
                        "suggested": plan["could_lower"],
                        "floor": plan.get("target_profit"),
                        "amazon_price": amazon_new,
                        "ebay_link": row["ebay_link"],
                    })

                # Hədəf qazanca çatılmırsa xəbər verək
                # (qiymət dəyişsə də, dəyişməsə də)
                if plan and plan.get("below_min"):
                    low_profit.append({
                        "name": record["product_name"],
                        "new_price": plan.get("new_price"),
                        "new_profit": plan.get("new_profit"),
                        "current_price": ebay_price,
                        "current_profit": plan.get("current_profit"),
                        "amazon_price": amazon_new,
                        "target": plan["target_profit"],
                        "reason": plan.get("reason", ""),
                        "ebay_link": row["ebay_link"],
                        "amazon_link": row["amazon_link"],
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

    # --- TƏK BİLDİRİŞ ---
    # Əvvəllər bir işləmədə 4-5 ayrı mesaj gedirdi. İndi hamısı bir qısa
    # xülasədə birləşir; dəyişiklik və diqqət tələb edən hal yoxdursa
    # ümumiyyətlə mesaj göndərilmir.
    lost = sum(1 for r in results if r.get("status") == "BLOKLANDI")
    summary = notify.format_run_summary(
        checked=len(results),
        total=stats["total"],
        actions=auto_actions,
        alerts=alerts,
        low_profit=low_profit,
        dry_run=config.AUTO_DRY_RUN,
        blocked=lost,
        block_reason=block_reason if lost else None,
    )
    if summary:
        notify.send(summary)
    else:
        print("Dəyişiklik yoxdur — Telegram bildirişi göndərilmir.")

    if could_lower:
        # Bu siyahı gündəlik hesabatda gedir (src/report.py) — hər işləmədə
        # təkrarlamaq spam olardı.
        print(f"💡 {len(could_lower)} məhsul ucuzlaşdırıla bilər "
              f"(gündəlik hesabatda göstəriləcək)")

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
    }


def _m(v):
    return "—" if v is None else f"${v:,.2f}"


if __name__ == "__main__":
    try:
        sys.exit(run())
    except Exception as exc:
        traceback.print_exc()
        try:
            notify.send(notify.format_run_error(exc))
        except Exception:
            pass
        sys.exit(1)
