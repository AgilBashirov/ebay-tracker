# ebay-tracker — technical handoff

Written for whoever (human or agent) picks this up next, in particular for
building a **broader web application** that does the same things: automatic
repricing and competitor discovery on eBay.

This repo is a **working prototype, not a product**. Read the "Hard-won facts"
section before designing anything — every item there cost real API calls to
discover and is not in eBay's documentation.

---

## 1. What exists

Two separate features share one repo and one Google Sheet.

### A. Price tracker — complete and running in production

Runs hourly on GitHub Actions. Reads a Google Sheet of eBay listings paired
with Amazon source links, scrapes/queries the Amazon price and stock, computes
true profit after all eBay fees, and optionally rewrites the eBay listing's
price and quantity via the Trading API.

| File | Role |
|---|---|
| `src/main.py` | orchestrator for one run |
| `src/scraper.py` | Amazon via Playwright or a scraping API |
| `src/ebay_api.py` | eBay Browse API: price + quantity (`_get_token`, `extract_item_id`, `fetch_item`) |
| `src/ebay_write.py` | eBay Trading API writes (`ReviseInventoryStatus`) |
| `src/pricing.py` | fee model, margin, repricing decisions |
| `src/sheets.py` | Google Sheets read/write/format |
| `src/notify.py` | Telegram, one message per run |
| `src/report.py` | daily summary (separate workflow job) |
| `config.py` | every setting, all from env vars |

Comments in this half are **Azerbaijani** — it is the original author's code and
was deliberately left alone.

### B. Competitor lookup — partially built

Goal: given one of my listings, find other sellers offering the **exact same
product variant**, rank them by sales velocity, and flag the fastest movers.
Precision is the hard requirement: **zero false positives**. Anything uncertain
must be reported as `CHECK`, never as `COMPETITOR`.

| File | Status |
|---|---|
| `src/matching.py` | **done** — deterministic rules, no AI, no network |
| `src/comp_store.py` | **done** — sales-velocity snapshots, `BaseStore` + `JsonStore` |
| `src/ai_judge.py` | **done** — free AI provider chain and the judge prompt |
| `src/comp_api.py` | **done** — local HTTP API (stdlib only), works in `--demo` |
| `src/ebay_search.py` | **missing** — Browse search + normalisation to one listing shape |
| `src/competitors.py` | **missing** — `process_product()` orchestrator + CLI |
| `src/comp_sheet.py` | **missing** — `SheetStore`, writes the `Competitors` worksheet |
| `test_competitors.py` | **missing** — 16 offline scenarios |
| `.github/workflows/competitors.yml` | **missing** |

Comments in this half are **English**.

Nothing in the price tracker imports the competitor modules, so the two cannot
break each other. `config.py` additions are purely additive.

---

## 2. Hard-won facts about the eBay Browse API

All verified with live production calls. **None of this is obvious from the
docs.**

### 2.1 `estimatedSoldQuantity` is per-variant

This is the single most important finding, because the whole "who sells fastest"
ranking depends on it. A five-flavour listing returned:

```
v1|173932969994|473233205235  Chocolate  $69.99  sold=1393  avail=0   OUT_OF_STOCK
v1|173932969994|473233205236  Vanilla    $69.99  sold=1455  avail=1   IN_STOCK
v1|173932969994|473233205237  Strawberry $69.99  sold=679   avail=0   OUT_OF_STOCK
v1|173932969994|473784301173  PB Choc    $69.99  sold=508   avail=56  IN_STOCK
v1|173932969994|476441619002  Cookies    $69.99  sold=162   avail=41  IN_STOCK
```

Same price everywhere, completely different sales. So ranking must happen at
**variant level**, and a "competitor" is a `(my variant, their variant)` pair,
not a listing pair.

### 2.2 Ended listings are still returned as `IN_STOCK`

A listing with `itemEndDate = 2026-10-13` (a month in the past) still came back
with `estimatedAvailabilityStatus: IN_STOCK` and `estimatedAvailableQuantity:
3`. **You must check `itemEndDate` yourself.** Active listings generally return
`itemEndDate: null`. Filtering only on status leaves dead listings in the
results.

### 2.3 Availability needs three checks, not one

A variant counts as inactive if **any** of these holds: `status ==
OUT_OF_STOCK`, `estimatedAvailableQuantity == 0`, `itemEndDate` in the past, or
no price. In the sample above 2 of 5 variants were inactive.

### 2.4 `ItemSummary` has no `localizedAspects`

Search results carry `itemId`, `title`, `price`, `seller`, `itemGroupHref`,
`itemCreationDate` — but **not** aspects. Since size/flavour/pack comparison
depends entirely on aspects, every serious candidate needs a **second call** to
fetch the full item. That is what sets the API budget (see §5).

### 2.5 Variation listings

`get_item_by_legacy_id` without a variation id returns **HTTP 400, errorId
11006** for a variation listing. Fall back to
`get_items_by_item_group?item_group_id=<legacy_id>`, which returns `items[]`
(each a full Item) plus `commonDescriptions[]`. In search results the same thing
is reachable through `itemGroupHref`.

### 2.6 Fields that are often missing

`mpn` and `epid` were absent on real listings; `gtin` was present. `lotSize`
comes back as **`0`** when unset, not `null` — treat `0` as "unknown". Plan for
every identifier to be missing and fall back gracefully.

### 2.7 Shipping requires a location context

Send `X-EBAY-C-ENDUSERCTX: contextualLocation=country=US,zip=10001`, otherwise
`shippingOptions[].shippingCost` is unreliable. Without a fixed destination the
"total price" column is not comparable between sellers.

### 2.8 Image search works

`POST /item_summary/search_by_image` returned HTTP 200 on a production
client-credentials token. It even accepted an obviously invalid base64 payload,
so do not treat a 200 as proof the image was understood.

---

## 3. Free AI providers

### 3.1 Groq needs a User-Agent or Cloudflare blocks you

`urllib` identifies itself as `Python-urllib/3.12`; Groq's Cloudflare rejects it
with **HTTP 403, "error code: 1010"**. That looks exactly like an invalid API
key and will send you chasing the wrong problem. Set any normal `User-Agent`
and it works.

### 3.2 Gemini keys are not always `AIza...`

Most documentation shows keys beginning `AIza` (39 chars), but a key that
worked fine here began with `AQ.` and was 53 chars long. **Do not validate key
format** — a shape check would have rejected a perfectly good key. Just attempt
the call and read the response.

### 3.3 The provider chain is not optional

In a single live test `gemini-flash-latest` returned **HTTP 503 "experiencing
high demand"** three times in a row, and the run only succeeded because it fell
through to `gemini-flash-lite-latest`. A single-model design would have failed.

Distinguish two kinds of 429:
- body mentions `PerDay` / `daily` / `RPD`, or `retryDelay > 90s` → **daily
  limit**, abandon that model for the whole run
- otherwise → per-minute limit, wait `retryDelay` and retry

### 3.4 Judge accuracy

On real listings the judge scored **4/4**: identical product → `SAME`, other
flavour → `DIFFERENT_VARIANT`, other size → `DIFFERENT_VARIANT`, measuring
scoop → `DIFFERENT`. Confidence 100 on all four.

Prompt rules that matter: ask for JSON only, strip Gemini `thought` parts, and
tell the model explicitly that a **variation listing's title proves nothing**
(it lists every size the seller offers). Require it to return the matching
`(Mi, Cx.Vj)` variant pairs; a `SAME` with no pair is only acceptable when both
sides have exactly one variant, otherwise downgrade to `UNSURE`.

---

## 4. Precision design — why each rule exists

`src/matching.py` is the core. It runs **before** the AI (to save quota) and
**again after** the AI, where a conflict **overrides** the AI's verdict.

| Rule | Why it is there |
|---|---|
| GTIN normalised to 14 digits | the same product is UPC-12 for one seller and EAN-13 for another; padding makes them equal |
| `"Does not apply"`, all-zeros → invalid | sellers type junk instead of leaving it blank |
| `Unbranded`/`Generic` is not a brand | otherwise "Unbranded" matches "Unbranded" |
| `oz` written into **both** mass and volume families | `oz` is ambiguous; this makes `16 oz == 1 lb` and `16 oz ~= 16 fl oz` work while `16 oz != 32 oz` still fails |
| unit conflict only when **both** sides have a value in that family | a value on one side only means unknown, not different |
| `3 in 1` / `5 in 1` excluded from length | "3 in 1 Shampoo" parsed as 3 inches and clashed with "5 in 1" |
| missing pack size reads as 1 | this is what catches the same product sold as a 2-pack at double the price |
| flavour/colour/scent compared separately | they are not measurements, so the unit logic cannot see them; a value containing the other ("Vanilla" in "French Vanilla") is not a conflict |
| accessory keyword list | "Whey Protein 2LB" vs "Whey Protein Scoop" have near-identical titles |
| `Item Weight` / `Dimensions` aspects **excluded** | sellers fill shipping fields in roughly, which made identical products look different |
| **title never used** for size on a variation listing | its title lists every size; using it made every variant compatible with every other |

### 4.1 Decision order

1. hard reject — different real brand, or different condition group (no AI)
2. GTIN match → `SAME`, confidence 95 (no AI)
3. verdict cache — keyed by `(my legacy, their legacy)`, invalidated by a
   SHA-1 fingerprint of both titles plus both variant label sets
4. everything else → AI, in batches
5. guard: re-check every AI `SAME` pair; no clean pair left → `CHECK`

### 4.2 Measured accuracy without AI

Live run on a real product (GTIN + title searches, deterministic rules only):

```
5 COMPETITOR · 1 CHECK · 19 rejected · 29 eBay calls · 0 false positives
```

Rejection reasons were specific and correct: `flavor: vanilla != chocolate`,
`!= unflavored`, `!= strawberry`, `!= salted caramel`, `size mismatch
(weight)`, `different GTIN`. All five accepted competitors were manually
verified as genuine.

So **AI is not required for precision** — it buys *coverage*. Without it, a
competitor whose listing omits its size falls into `CHECK` rather than being
missed or wrongly accepted. `COMP_TITLE_PROOF_SCORE` (default `0` = off) is the
only path that could produce a false positive; leave it off unless coverage
matters more than precision.

---

## 5. API budget

The daily 5,000 Browse calls are **shared with the price tracker**.

Measured, one product: 1 call for my listing + 3-5 searches + 1 call per
candidate fully loaded. With the candidate cap at 25 that is **29-40 calls per
product**. At `COMP_PRODUCTS_PER_RUN = 10` a daily run costs 300-400 calls.

`src/ebay_search.py` must route every HTTP call through a single `_request()`
that increments a counter and raises when `COMP_MAX_API_CALLS` is reached, so a
run degrades cleanly instead of being cut off mid-write. That single chokepoint
is also the only thing the offline tests need to mock.

---

## 6. Engine contract

`comp_api.py` and the CLI both call one function, so there is exactly one code
path to verify:

```python
process_product(item_id, variation_id=None, cache_only=False) -> dict
```

Success:

```json
{
  "my_item":     {"legacy_id": "...", "title": "...", "url": "...", "variants": [...]},
  "competitors": [{"status": "TOP COMPETITOR|COMPETITOR", "url": "...?var=...",
                   "seller": "...", "price": 0.0, "shipping": 0.0, "total": 0.0,
                   "diff": 0.0, "my_variant": "...", "their_variant": "...",
                   "sold": 0, "sold_7d": 0, "last_sale": "YYYY-MM-DD",
                   "confidence": 0, "found_by": "gtin|epid|mpn|title|image|previous",
                   "reason": "..."}],
  "unsure":      [{"status": "CHECK", "...": "same shape"}],
  "stats":       {"searches": 0, "candidates_found": 0, "candidates_checked": 0,
                  "ebay_calls": 0, "ai_calls": 0, "rejected": 0, "out_of_stock": 0},
  "checked_at":  "ISO-8601"
}
```

Failure — deliberately **not** an exception, so the HTTP shell stays decoupled
and testable before the engine exists:

```json
{"error": {"code": 400, "message": "..."}}
```

`400` bad id · `404` listing gone · `503` budget exhausted.

---

## 7. Sales velocity

The Browse API gives **no sale date and no sale price** — only a running total.
So `comp_store.py` records that total **once per day** per
`myLegacy|myVariant|theirLegacy|theirVariant` key (60 points max) and derives:

- `sold_window(history, 7)` → `(growth, observed_days)`; a short history is
  reported over its real span, because "3 sales" means very different things
  over one day and over seven
- `last_sale` → the latest snapshot where the total increased
- `rate_per_day` → growth / observed days, **divisor floored at 1 day**
  (snapshots hours apart otherwise inflate the rate enormously)
- `lifetime_rate` → `sold / listing age`, the **only** ranking signal available
  on day one when the history is still empty

Two traps already handled: a second run on the same day **replaces** that day's
point (a cron firing twice would otherwise look like a sale), and a relisted
item whose counter resets clamps growth at 0 instead of going negative.

Resolution is **one day**, and that is a hard API limit. Say so in any UI.

---

## 8. Testing

`test_all.py` (129 checks) and `test_auto.py` (126 checks) must both stay green.
They make **zero** network calls: `sheets`, `notify`, `scraper`, `ebay_api`,
`ebay_write._call` and `ai_judge.ask` are all replaced with fakes.

**Trap worth knowing.** `test_all.py` does not mock `ebay_api`, and for months
it passed only because no eBay keys were in the environment. The moment a
`.env` file appeared, `ebay_api.is_configured()` became true, the suite started
making **real** Browse calls against fake listing ids, they 404'd, and four
status assertions changed. The suite now blanks the eBay keys at import time.
Any new test file must be hermetic the same way — never rely on the ambient
environment.

Second trap: on Windows `PYTHONPATH=.:src` **silently does nothing**, because
the separator is `;`. The test files insert `sys.path` themselves, and
`comp_api.py` bootstraps its own path for the same reason. Any new directly
executable entry point must do likewise.

---

## 9. Security findings — read this before building the web app

Three issues were found and fixed in the local API and the AI image fetch. All
three will be **worse in an internet-facing application**.

**SSRF via an unvalidated URL.** The image url comes from the Browse API, i.e.
it is ultimately seller-supplied content relayed by a third party, and whatever
is downloaded gets forwarded to an AI provider. `urllib` opens any scheme, so a
url of `file:///.../.env` would have read a local file and shipped it to Gemini
as a base64 "image"; `http://169.254.169.254/` would have reached cloud
metadata. Fixed with an allowlist: `https` only, host must end in
`ebayimg.com` / `ebaystatic.com`. Note `i.ebayimg.com.evil.com` must also be
rejected — anchor the host pattern at the end.

**Binding to localhost is not access control.** A page the user visits can
point `attacker.com` at `127.0.0.1` (DNS rebinding) and read the replies as
same-origin. Fixed by validating the `Host` header and rejecting any request
that carries an `Origin` header. In a real web app this becomes ordinary CORS
plus CSRF tokens — do not skip it because an endpoint is "internal".

**Secret comparison must be constant time** — `hmac.compare_digest`, never `==`.

One more, specific to this domain: an unauthenticated endpoint that triggers a
competitor check is a **quota amplification** vector. One request costs ~35 eBay
calls out of 5,000/day plus AI tokens. Authentication, per-user rate limits and
a shared budget counter are functional requirements, not hardening.

---

## 10. Advice for the new web application

**Reusable as-is.** `matching.py` and `comp_store.py` are pure functions with no
network, Sheets or eBay dependency — copy them over directly. They encode the
expensive knowledge in §4 and §7. `ai_judge.py` only depends on `config`.

**Replace.** `comp_api.py` is `http.server` and synchronous. Keep the
`process_product` contract from §6, but a real app needs the opposite
execution model: a product check takes **30-120 seconds**, far longer than any
sane HTTP timeout. Use a job queue — `POST /checks` returns a job id, a worker
runs it, the client polls or gets a webhook. The synchronous design here only
works because it is localhost.

**Do not reuse** the Google Sheet as a datastore. It was the right call for a
prototype (free, and the owner can edit rows by hand) but it forces
`USER_ENTERED` quoting, formula-vs-value read modes, hidden columns for
bookkeeping, and row-number addressing that breaks if anything is sorted. A
real app wants Postgres with a `competitor_pairs` table and a `sales_snapshots`
table — the snapshot design in §7 maps onto it directly.

**Keep two things that look like over-engineering but are not:** the dual
evaluation (deterministic rules → AI → deterministic guard), and the rule that
uncertainty becomes `CHECK` rather than a competitor. Both exist because a
wrong competitor silently drives wrong repricing decisions, which costs real
money.

---

## 11. Open items

- `estimatedSoldQuantity` was verified per-variant on one listing. Confirm on a
  few more before relying on it across categories.
- The title-only acceptance path (`COMP_TITLE_PROOF_SCORE`) is untested at
  scale and is off by default.
- GTIN check digits are not validated — a mistyped GTIN that happens to match
  another product's would be accepted.
- Brand comparison is literal, so `HP` vs `Hewlett Packard` becomes `CHECK`.
- No category-specific tuning. The live measurements above come from one
  supplements listing; electronics and apparel will behave differently.

### Credentials

Every secret comes from the environment: GitHub Secrets in Actions, and a
gitignored `.env` locally (loaded by `config._load_dotenv()`, which never
overwrites an existing variable so Actions always wins).

**The Telegram bot token was committed in plain text to this public repo and
is still in git history.** It was removed from `QURASDIRMA.md`, but that is not
sufficient — it must be revoked in BotFather. Treat the eBay, Gemini and Groq
keys as exposed too and rotate all of them.
