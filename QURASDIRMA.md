# eBay Dropshipping — Qiymət İzləmə Sistemi

Amazon qiymətlərini avtomatik izləyir, marjanızı hesablayır və dəyişiklik olanda Telegram-a bildiriş göndərir. **Tam pulsuzdur**, kompüteriniz açıq olmasa da işləyir.

---

## Nə edir?

Hər saat GitHub-un serverində işə düşür və:

1. Google Sheet-dəki bütün məhsulları oxuyur (54 də olsa, 500 də — sətir sayı dinamikdir)
2. Neçə məhsul yoxlayacağını **özü hesablayır** və ən köhnə yoxlanılanları seçir
3. Amazon-dan qiymət və stok statusunu oxuyur
4. eBay listinginizdən satış qiymətinizi oxuyur
5. Marjanızı hesablayır və lazım olsa yeni eBay qiyməti təklif edir
6. Sheet-i yeniləyir və rəngləyir
7. **Yalnız dəyişiklik varsa** Telegram-a bildiriş göndərir

### Batch ölçüsü özü tənzimlənir

Hər işləmədə neçə məhsul yoxlanacağını sistem **məhsul sayına görə özü hesablayır** — siz heç nə etməli deyilsiniz. Yeni məhsul əlavə etdikcə avtomatik uyğunlaşır:

| Məhsul sayı | İşləmədə | Gündəlik tutum | Hər məhsul gündə |
|---|---|---|---|
| 54 | 3 | 72 | 1.3 dəfə |
| 100 | 5 | 120 | 1.2 dəfə |
| 300 | 13 | 312 | 1.0 dəfə |
| 500 | 21 | 504 | 1.0 dəfə |
| 1000 | 42 | 1008 | 1.0 dəfə |

Məntiq: hər məhsul gündə təxminən **bir dəfə** yoxlanılsın. Bu, həm kifayət qədər tez-tezdir, həm də Amazon-a lazımsız sorğu getmədiyi üçün bloklama riskini minimuma endirir.

`Run workflow` düyməsindəki sahə **boş/`auto` qalsa** avtomatik hesablanır. Ora rəqəm yazmaq yalnız test məqsədilə lazımdır (məs. `3` yazıb tez yoxlamaq üçün).

---

## Bildiriş nümunəsi

```
⚠️ Qiymət / stok dəyişikliyi

Granite Essential Amino Acids Powder
📈 Amazon: $10.00 → $12.00 (+2.00 / +20.0%)
🏷 Sizin eBay: $20.00
💰 Marja: $5.35 (26.8%)
💡 Tövsiyə: eBay qiymətini $22.99 edin (marjanı qorumaq üçün)
🔗 eBay · Amazon
```

---

## Quraşdırma (bir dəfəlik, ~25 dəqiqə)

### Addım 1 — GitHub repo yaradın

1. github.com → **New repository**
2. Ad: `ebay-tracker`
3. **Public** seçin ⚠️ *(vacibdir: public repolarda GitHub Actions dəqiqələri limitsizdir. Kodunuzda parol yoxdur — bütün açarlar ayrıca "Secrets"də saxlanılır və heç kim görə bilməz)*
4. **Create repository**
5. Bu qovluqdakı bütün faylları repoya yükləyin (sürüşdürüb buraxmaqla da olar)

### Addım 2 — Google Service Account (sheet-ə yazmaq üçün)

1. console.cloud.google.com → yeni layihə yaradın
2. Sol menyu → **APIs & Services** → **Library** → "Google Sheets API" axtarın → **Enable**
3. **APIs & Services** → **Credentials** → **Create Credentials** → **Service Account**
4. Ad verin (məs. `tracker`) → **Create and Continue** → **Done**
5. Yaradılan service account-a klikləyin → **Keys** → **Add Key** → **Create new key** → **JSON** → yüklənəcək
6. JSON faylı açın, `client_email` sətrindəki e-poçtu kopyalayın (məs. `tracker@layihe.iam.gserviceaccount.com`)
7. **Google Sheet-inizi açın** → **Share** → həmin e-poçtu əlavə edin → **Editor** icazəsi verin

### Addım 3 — Telegram chat ID-nizi tapın

Botunuz artıq hazırdır: `@ebay_daily_bot`

1. Telegram-da **@ebay_daily_bot**-u açın və **Start** düyməsinə basın (və ya `/start` yazın)
2. Brauzerdə bu ünvanı açın:
   ```
   https://api.telegram.org/bot8877814507:AAG0_XgcOAIOoTMR5bzAOR_j1S3aHRvcUus/getUpdates
   ```
3. Açılan mətndə `"chat":{"id":123456789` hissəsini tapın — həmin rəqəm sizin chat ID-nizdir

> ⚠️ Bot tokeni parolunuz kimidir — heç kimlə paylaşmayın. Əgər kiməsə göstərilibsə, @BotFather-də `/revoke` ilə yenisini alın.

### Addım 4 — GitHub Secrets əlavə edin

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Bunları bir-bir əlavə edin:

| Secret adı | Dəyəri |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 2-ci addımdakı JSON faylının **bütün məzmunu** |
| `TELEGRAM_TOKEN` | `8877814507:AAG0_XgcOAIOoTMR5bzAOR_j1S3aHRvcUus` |
| `TELEGRAM_CHAT_ID` | 3-cü addımda tapdığınız rəqəm |
| `SHEET_ID` | `1h5DJGfwCYPSUyMhzMcxHC-5NJQhnS8qXPVD_nfOF7tE` |

**⚠️ MƏCBURİ — GitHub Actions üçün:**

Amazon GitHub-un server IP-lərini bloklayır (ilk sorğudan). Ona görə ən azı bir scraping API açarı lazımdır. Bunlar rezident proksi istifadə edirlər, Amazon bloklamır:

| Secret adı | Haradan | Pulsuz limit |
|---|---|---|
| `SCRAPERAPI_KEY` | scraperapi.com → qeydiyyat → Dashboard-da API Key | 1,000 kredit/ay |
| `SCRAPINGBEE_KEY` | scrapingbee.com → qeydiyyat → Dashboard-da API Key | 1,000 kredit/ay |

**İkisini də əlavə edin** — birincinin krediti bitəndə sistem avtomatik ikinciyə keçir. Cəmi 2,000 kredit/ay.

Kredit hesabı: hər məhsul gündə 1 dəfə yoxlanır.
- 54 məhsul → ayda ~1,620 kredit ✅ pulsuz limitə sığır
- 65 məhsul → ayda ~1,950 kredit ⚠️ limitin sərhədində
- 100+ məhsul → pulsuz limit çatmır, ödənişli plan lazımdır (~$30-50/ay)

### Addım 5 — İlk işləmə

Repo → **Actions** → **Qiymet Izleme** → **Run workflow**

İlk işləmə sheet-in başlıqlarını qurur və ilk 25 məhsulu yoxlayır. Loglara baxıb hər şeyin işlədiyinə əmin olun.

Bundan sonra hər saat özü işləyəcək.

---

## Sheet strukturu

| Sütun | Ad | Kim doldurur |
|---|---|---|
| A | eBay Link | **Siz** |
| B | Amazon Link | **Siz** |
| C | Məhsul Adı | avtomatik |
| D | eBay Qiymətim | avtomatik (eBay linkindən) |
| E | Amazon (əvvəlki) | avtomatik |
| F | Amazon (indiki) | avtomatik |
| G | Stok | avtomatik |
| H | Marja $ | avtomatik |
| I | Marja % | avtomatik |
| J | Tövsiyə eBay | avtomatik |
| K | Son Yoxlama | avtomatik |
| L | Status | avtomatik |

**Yeni məhsul əlavə etmək:** sadəcə A və B sütunlarına linkləri yazın. Qalanını sistem özü dolduracaq — heç bir ayar dəyişikliyi lazım deyil.

### Sətir rəngləri

| Rəng | Mənası |
|---|---|
| 🟢 Yaşıl | Hər şey qaydasındadır |
| 🟠 Narıncı | Amazon qiyməti artıb |
| 🟡 Sarı | Marja həddin altına düşüb |
| 🔴 Qırmızı | Amazon-da stok bitib |
| ⚪ Boz | Xəta (link ölüdür və s.) |
| 🟣 Bənövşəyi | Bloklama — növbəti işləmədə təkrar cəhd olunacaq |

---

## Ayarlar

Repo → **Settings** → **Secrets and variables** → **Actions** → **Variables** bölməsi

| Dəyişən | Defolt | İzah |
|---|---|---|
| `BATCH_SIZE` | auto | Hər işləmədə neçə məhsul — **toxunmayın**, özü hesablayır |
| `MARGIN_ALERT_PCT` | 15 | Marja bu %-in altına düşəndə xəbərdarlıq |
| `PRICE_RISE_MIN_USD` | 0.50 | Bu qədər $ artımdan sonra bildiriş |
| `PRICE_RISE_MIN_PCT` | 2.0 | Bu qədər % artımdan sonra bildiriş |
| `EBAY_FEE_PCT` | 13.25 | eBay komissiyanız |
| `TARGET_MARGIN_PCT` | 0 | 0 = mövcud marjanı qoru. 25 yazsanız hər məhsulda 25% hədəflənər |
| `ALERT_ON_PRICE_DROP` | 0 | 1 edin ki, qiymət düşəndə də xəbər gəlsin |
| `EBAY_PRICE_SOURCE` | scrape | `sheet` edin ki, D sütununu özünüz doldurasınız |
| `DELAY_MIN_SEC` / `DELAY_MAX_SEC` | 8 / 22 | Məhsullar arası gecikmə — **azaltmayın**, bloklamanın əsas səbəbidir |

---

## Məhsul sayı artdıqca

| Məhsul sayı | Nə etməli |
|---|---|
| 54 → 300 | **Heç nə.** Sadəcə sheet-ə yeni sətir əlavə edin, sistem özü uyğunlaşır |
| 300-500 | Heç nə. İstəsəniz ehtiyat API açarlarını (Addım 4) əlavə edin |
| 500+ | Bloklama tezləşə bilər — ya ödənişli API-yə (~$20/ay), ya da Oracle Cloud pulsuz VM-ə keçmək lazımdır. Kod hər ikisinə hazırdır, yalnız konfiqurasiya dəyişikliyidir |

---

## Bloklama olsa nə olur?

Amazon CAPTCHA verirsə:

1. Script dərhal dayanır (IP-ni daha da yandırmamaq üçün)
2. Telegram-a xəbərdarlıq gəlir: neçə məhsul yoxlanıldı, neçəsi qaldı
3. Ehtiyat API açarları varsa, avtomatik onlarla cəhd edir
4. Yoxlanılmayan məhsullar **növbəti saatın növbəsinə düşür**

CAPTCHA müvəqqətidir — adətən 15 dəqiqə ilə bir neçə saat arasında özü açılır. Üstəlik GitHub Actions hər işləmədə fərqli serverdən (fərqli IP) işə düşür, ona görə növbəti saatdakı işləmə demək olar ki, təmiz IP-dən başlayır. **Heç bir məlumat itmir.**

---

## Nəyi bilmək faydalıdır

- Sistem `git` tarixçəsində heç bir həssas məlumat saxlamır — hər şey GitHub Secrets-dədir
- Sheet-in özü "yaddaş"dır: əvvəlki qiymət F sütunundan E sütununa keçir, ayrıca baza lazım deyil
- Script eyni anda iki dəfə işləməz (`concurrency` qorunması var)
- Telegram bildirişi **yalnız dəyişiklik olanda** gəlir — hər saat spam olmaz
- Gündə bir dəfə (UTC 17:00) qısa sağlamlıq hesabatı gəlir: neçə uğurlu, neçə xəta

---

## Problem olsa

| Simptom | Səbəb / həll |
|---|---|
| Sheet yenilənmir | Service account e-poçtuna sheet-də **Editor** icazəsi verilməyib |
| Telegram bildirişi gəlmir | Bota `/start` yazmamısınız, və ya `TELEGRAM_CHAT_ID` səhvdir |
| Bütün məhsullarda "BLOKLANDI" | `DELAY_MIN/MAX_SEC` artırın, `BATCH_SIZE` azaldın |
| Qiymət boş qalır | Amazon səhifə formatını dəyişib — `PRICE_PATTERNS` yenilənməlidir |
| "36 saatdır yoxlanılmayıb" xəbərdarlığı | Məhsul sayı tutumu keçib — `BATCH_SIZE` artırın |

Actions loglarında hər məhsul üçün ətraflı sətir yazılır — problemin harada olduğu dərhal görünür.
