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

### Kredit hesabı

Sistem krediti qorumaq üçün eBay səhifəsini **hər dəfə oxumur** — yalnız qərar ondan asılı olanda:

| eBay oxunur | eBay oxunmur (sheet-dən götürülür) |
|---|---|
| Məlumat yoxdur / 10 gündən köhnədir | Say 2-dən çoxdur **və** Amazon stokdadır |
| Qalıq say ≤ 2 (tez bitə bilər) | |
| Say 0 (bağlıdır — açılıbmı?) | |
| Amazon-da stok yoxdur | |

| Məhsul sayı | Aylıq kredit | Vəziyyət |
|---|---|---|
| 54 (indiki) | ~911 | ✅ 2,000 pulsuz limitə rahat sığır |
| 100 | ~1,687 | ✅ sığır |
| 150 | ~2,531 | ⚠️ limiti keçir |
| 500 | ~8,436 | ödənişli plan (~$30-50/ay) |

*(Uyğunlaşan yoxlama tezliyi sayəsində bu rəqəmlər əvvəlkindən təxminən 2 dəfə azdır — 54 məhsulda 1,911 yerinə 911.)*

**Limit dar gələndə pulsuz həll:** `MAX_INTERVAL_DAYS` dəyişənini `4` və ya `5` edin — sabit məhsullar daha seyrək yoxlanacaq.

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
| E | eBay Say | avtomatik / **əl ilə yaza bilərsiniz** |
| F | Amazon (əvvəlki) | avtomatik |
| G | Amazon (indiki) | avtomatik |
| H | Stok | avtomatik |
| I | eBay Haqqı | avtomatik (FVF + reklam + əməliyyat) |
| J | Marja $ | avtomatik |
| K | Marja % | avtomatik |
| L | Tövsiyə eBay | avtomatik |
| M | Son Yoxlama | avtomatik |
| N | Növbəti Yoxlama | avtomatik (kredit qənaəti) |
| O | Status | avtomatik |

### Marja necə hesablanır

ebayfeescalculator.com ilə eyni düsturla — sentinə qədər uyğun:

```
vergi       = (satış + göndərmə) × vergi%
haqq bazası = satış + göndərmə + vergi
FVF         = baza × 13.6%
reklam      = baza × reklam%
əməliyyat   = $0.40   (sifariş ≤ $10 olduqda $0.30)
marja       = satış − Amazon qiyməti − haqlar
```

⚠️ Satış vergisi sizə çatmır, amma **haqq bazasını artırır** — yəni vergi sizin xərcinizdir. Sadə "13.25% çıx" hesabı marjanı ~$4-5 şişirdirdi.

### Yoxlama tezliyi özü tənzimlənir (N sütunu)

| Vəziyyət | Növbəti yoxlama |
|---|---|
| Qiymət dəyişib | 1 gün |
| Diqqət tələb edir (az marja, az stok, stok yox) | 1 gün |
| Sabit qalır | 1 → 2 → 3 gün (tədricən uzanır) |
| Ölü link / xəta | 7 gün |
| Bloklanıb | ~2 saat (başqa IP ilə) |

Bu, API kreditini **təxminən 3 dəfə** azaldır: sabit məhsulları hər gün yox, 3 gündən bir yoxlayır.

### Stok bildirişi məntiqi

eBay listinginizdəki qalıq say nəzərə alınır ki, lazımsız bildiriş gəlməsin:

| eBay sayınız | Amazon | Bildiriş |
|---|---|---|
| 0 | stokda yoxdur | 🔕 gəlmir — listing onsuz da bağlıdır |
| 0 | **stoka gəlib** | ✅ "Listingi yenidən açın" + gözlənilən marja |
| >0 | stokda yoxdur | ✅ Təcili: listingi dayandırın |
| >0 | stokda var | qiymət/marja qaydası ilə |

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

## Cədvəlin görünüşü

Cədvəl hər işləmədə özü səliqəyə düşür — əl ilə heç nə etmək lazım deyil:

* **Linklər qısalır.** A və B sütunlarında uzun URL yerinə klikləyə biləcəyiniz
  "eBay" / "Amazon" yazısı görünür. URL itmir — `=HYPERLINK(...)` düsturunun
  içində qalır və sistem onu oradan oxuyur.
* **Rəqəmlər əsl rəqəmdir.** Qiymət və marja sütunları dollar formatında,
  Marja % faiz formatında, tarixlər `yyyy-mm-dd hh:mm` formatındadır — yəni
  sıralama, filtr və cəm düzgün işləyir (mətn kimi saxlansaydı işləməzdi).
* **Zolaqlı sətirlər.** Uzun siyahıda sətri itirməmək üçün açıq/ağ növbələşmə.
  Yoxlanılmış sətirlərdə status rəngi zolağın üstündə görünür.
* **Avtomatik filtr.** Başlıq sətrindəki oxlarla istənilən sütuna görə
  süzə və ya sırala bilərsiniz (məsələn yalnız "STOK YOX" olanlar).
* **Artıq yer kəsilir.** Məhsullardan sonrakı minlərlə boş sətir və O-dan
  sonrakı sütunlar silinir; yeni məhsul yazmaq üçün 20 boş sətir saxlanılır.

Bunları GitHub → Settings → Variables-dan söndürə bilərsiniz:

| Dəyişən | Defolt | Nə edir |
|---|---|---|
| `SHEET_SHORT_LINKS` | `1` | Linkləri qısaldır |
| `SHEET_TRIM_GRID` | `1` | Artıq sətir/sütunları silir |
| `SHEET_SPARE_ROWS` | `20` | Sonda saxlanılan boş sətir sayı |
| `SHEET_AUTO_SORT` | `0` | Hər işləmədə statusa görə sıralayır |

`SHEET_AUTO_SORT` defolt bağlıdır: açıq olanda məhsullar hər işləmədə yerini
dəyişir. Filtr onsuz da qoyulduğu üçün bir kliklə özünüz sıralaya bilərsiniz.

**Sütunları ƏL İLƏ silməyin və yerini dəyişməyin** — sistem onlara nömrə ilə
müraciət edir. Lazımsız görünən I, K və N sütunları elə bu səbəbdən silinmir,
sadəcə gizlədilir.

## Avtomatik idarəetmə (say + qiymət)

Sistem eBay listinqlərinizi özü tənzimləyə bilər. **Hər şey defolt BAĞLIDIR** —
açmaq üçün həm ümumi açar, həm də hər sətir üçün icazə lazımdır.

### Necə işə salınır

GitHub Variables: `AUTO_QTY=1` və `AUTO_PRICE=1`

Bundan sonra **bütün məhsullar avtomatik idarə olunur**. Sheet-də icazə sütunu
yoxdur — heç nə yazmaq lazım deyil. Sistemi dayandırmaq üçün eyni dəyişənləri
`0` edirsiniz.

`AUTO_DRY_RUN=1` olduqda sistem heç nəyi dəyişmir, yalnız nə edəcəyini yazır.

Üstəlik `AUTO_DRY_RUN=1` (defolt) olduqda sistem **heç nəyi dəyişmir**, yalnız
nə edəcəyini Telegram-a yazır. Bir neçə gün baxıb əmin olandan sonra `0` edin.

### Say necə tənzimlənir

| Amazon vəziyyəti | eBay sayınız |
|---|---|
| Stok yoxdur | **0** — listinq bağlanmır, tarixçə qalır |
| 10-dan az qalıb | **1** — çatdıra bilməyəcəyiniz sifariş gəlməsin |
| 10+ və ya say bilinmir | **3** |

Amazon qalıq sayı yalnız azaldıqda ("Only N left in stock") göstərir.
Göstərmirsə ehtiyat kifayətdir sayılır.

Stok bərpa olunanda say avtomatik 0-dan 3-ə qayıdır.

> ⚠️ Sayın 0 edilməsi üçün eBay-də **"Multi-quantity listings — Listings stay
> active when you're out of stock"** ayarı AÇIQ olmalıdır. Bağlıdırsa sistem
> saya toxunmur (əks halda listinq bağlanar və satış tarixçəniz itər).

### Qiymət necə tənzimlənir

Meyar faiz marjası deyil, **hər satışdan əlinizə keçən təmiz dollar**.
Bu rəqəm **HƏDD-dir (minimum), hədəf deyil**:

| Amazon qiyməti | Minimum təmiz qazanc |
|---|---|
| $20-a qədər | $5 |
| $20 – $50 | $7 |
| $50-dən yuxarı | $10 |

```
qazanc həddən AZDIRSA   →  qiymət qaldırılır
qazanc həddən ÇOXDURSA  →  toxunulmur ✅
```

**Niyə çox qazanc "düzəldilmir":** hədd dollarladır. Əgər sistem qazancı hədd
səviyyəsinə "endirsəydi", $395-lıq məhsuldan $136 qazanan listinq $11-ə enərdi.
Real mağazada ölçdük — 22 məhsulun qiyməti enirdi, ümumi qazanc **$508 → $294**
düşürdü. İndi isə eyni mağazada 19 məhsulun qiyməti qalxır, qazanc **+$63** artır.

Qazancınız həddən xeyli çoxdursa sistem sizə **sakit bildiriş** göndərir:
"istəsəniz $X-ə endirib daha rəqabətli ola bilərsiniz". Qərar sizindir.
Avtomatik endirmə istəyirsinizsə: `AUTO_PRICE_ALLOW_DOWN=1`

`PROFIT_TIERS` dəyişəni ilə hədləri dəyişə bilərsiniz: `20:5,50:7,1000000:10`

Qoruyucular:

- Bir işləmədə qiymət maksimum **+50%** qalxır
- $0.50-dən kiçik fərqə görə dəyişiklik edilmir
- **Heç vaxt zərərinə satış olmur** — həddə çatmaq üçün qiymət təhlükəsizlik
  həddindən çox qaldırılmalıdırsa dəyişiklik edilmir, Telegram-a xəbərdarlıq gedir

### Telegram — bir işləmə, bir mesaj

Hər işləmədən sonra Telegram-a **yalnız bir qısa mesaj** gəlir:

```
eBay yoxlaması · 12/54 məhsul

📈 Qiymət (2)
• Granite Amino Acids — $52.99 ↑ $66.99 · qazanc $7.39
• Country Farms Greens — $39.99 ↑ $49.99 · qazanc $7.55

📦 Say (2)
• Mifoci Toothbrushes — 8 → 3
• Tart Cherry Powder — 0 → 3 (satışa qayıtdı)

⚠️ Diqqət (1)
• Micro Ingredients — qazanc $1.01, hədəf $7.00 tutmur
```

Dəyişiklik və diqqət tələb edən hal yoxdursa **heç bir mesaj gəlmir**.

---

## Azərbaycan satıcısı üçün haqlar

eBay-in rəsmi cədvəlinə görə (International fees for eBay global sellers)
Azərbaycan **"Europe Unsited (excl. EU)"** qrupundadır:

| Haqq | Dərəcə | Nə vaxt |
|---|---|---|
| Final Value Fee | 13.6% + $0.40 | hər satışda |
| Promoted Listings | sizin dərəcəniz | reklam işlədirsinizsə |
| **Beynəlxalq haqq** | **1.30%** | alıcı Azərbaycandan kənardadırsa (yəni həmişə) |
| Valyuta çevrilişi | 3.0% | ödəniş USD-dən başqa valyutaya çevrilirsə |
| **ƏDV** | **18%** | **yuxarıdakı haqların CƏMİNƏ əlavə olunur** |

İki fərqli vergi var, qarışdırmayın:

1. **Alıcıdan alınan satış vergisi** (ABŞ ştatı, ~8%) — sizə çatmır, amma eBay
   haqqını məhz vergi daxil məbləğdən hesablayır, ona görə xərcinizi artırır.
2. **ƏDV (18%)** — Azərbaycan dərəcəsidir və eBay-in **öz xidmət haqqının**
   üstünə gəlir: `(FVF + reklam + beynəlxalq + əməliyyat) × 1.18`

$60.99-luq satışda bu belə görünür:

```
FVF            $8.96
reklam         $2.63
beynəlxalq     $0.86
əməliyyat      $0.40
             ───────
haqlar cəmi   $12.85
ƏDV 18%        $2.31
             ───────
CƏMİ          $15.16
```

> Biznes satıcısısınızsa və eBay-ə ƏDV nömrənizi vermisinizsə ƏDV 0 ola bilər.
> Dəqiq rəqəmi eBay hesab-fakturanızdan yoxlayın: **Payments → Reports**.
> `EBAY_FEE_VAT_PCT` dəyişəni ilə tənzimlənir.

---

## Ayarlar

Repo → **Settings** → **Secrets and variables** → **Actions** → **Variables** bölməsi

| Dəyişən | Defolt | İzah |
|---|---|---|
| `BATCH_SIZE` | auto | Hər işləmədə neçə məhsul — **toxunmayın**, özü hesablayır |
| `MAX_INTERVAL_DAYS` | 3 | Sabit məhsul ən çox neçə gündən bir yoxlansın |
| `ERROR_INTERVAL_DAYS` | 7 | Ölü link neçə gündən bir təkrar yoxlansın |
| `MARGIN_ALERT_PCT` | 15 | Marja bu %-in altına düşəndə xəbərdarlıq |
| `PRICE_RISE_MIN_USD` | 0.50 | Bu qədər $ artımdan sonra bildiriş |
| `PRICE_RISE_MIN_PCT` | 2.0 | Bu qədər % artımdan sonra bildiriş |
| `EBAY_FVF_PCT` | 13.6 | Final Value Fee (kateqoriyanıza uyğun) |
| `EBAY_AD_RATE_PCT` | 0 | Promoted Listings reklam dərəcəsi — **işlədirsinizsə mütləq yazın** |
| `SALES_TAX_PCT` | 10 | Alıcıdan alınan satış vergisi (haqq bazasını artırır) |
| `EBAY_ORDER_FEE` | 0.40 | Sifariş başına haqq ($10-dan aşağıda 0.30) |
| `EBAY_INTERNATIONAL_PCT` | 0 | Xaricə satırsınızsa 1.65 |
| `SHIPPING_CHARGED` / `SHIPPING_COST` | 0 / 0 | Göndərmə haqqı və xərci |
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
