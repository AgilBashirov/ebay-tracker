"""
Competitor sales history and AI verdict cache.

WHY A HISTORY IS NEEDED:
The eBay Browse API does not expose the DATE or PRICE of the last sale — only
a running total (`estimatedSoldQuantity`). So "who sold most recently" cannot
be answered directly.

The workaround: record that total once a day (a snapshot). The difference
between two days is that day's sales. From there we derive "units sold in the
last 7 days" and "date of the most recent sale". Resolution is one DAY — the
API offers nothing finer.

The backend is swappable: JsonStore for local testing, SheetStore for real
runs (src/comp_sheet.py). Both implement BaseStore.
"""
import hashlib
import json
import os
from datetime import datetime, timedelta

MAX_SNAPSHOTS = 60          # ~2 months; more is neither useful nor cheap
DEFAULT_WINDOW_DAYS = 7


# ---------------------------------------------------------------------------
# Keys and fingerprints
# ---------------------------------------------------------------------------

def snapshot_key(my_legacy, my_variation, their_legacy, their_variation) -> str:
    """
    Stable key for one competitor pair.

    It is variant-level: a competitor's 16 oz and 32 oz variants are separate
    rows with separate histories.
    """
    return "|".join(str(p or "") for p in
                    (my_legacy, my_variation, their_legacy, their_variation))


def fingerprint(my_listing: dict, their_listing: dict) -> str:
    """
    Validity stamp for a cached verdict.

    If a listing's title or variant set changed, the old AI verdict is no
    longer trustworthy — the seller may have swapped the product. When the
    fingerprint changes the cache is bypassed and the AI is asked again.
    """
    def part(listing):
        labels = "~".join(sorted(
            str(v.get("label") or "") for v in (listing.get("variants") or [])))
        return f"{listing.get('title') or ''}#{labels}"

    raw = f"{part(my_listing)}||{part(their_listing)}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def _dt(raw) -> datetime | None:
    text = str(raw or "").strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:len(fmt) + 2].strip(), fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def parse_history(raw) -> list[tuple[str, int]]:
    """Normalize a history. It arrives from the Sheet as a JSON string."""
    if not raw:
        return []
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
    out = []
    for item in data or []:
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        stamp, sold = item[0], item[1]
        if _dt(stamp) is None:
            continue
        try:
            out.append((str(stamp), int(float(sold))))
        except (TypeError, ValueError):
            continue
    return sorted(out, key=lambda pair: _dt(pair[0]))


def dump_history(history) -> str:
    return json.dumps([[s, n] for s, n in history], separators=(",", ":"))


def add_snapshot(history, sold, now: datetime | None = None) -> list:
    """
    Record today's total.

    Exactly ONE point per day is kept: a second run on the same day replaces
    the earlier point. Otherwise a cron that fires twice would look like a
    sale had happened.
    """
    if sold is None:
        return parse_history(history)

    now = now or datetime.utcnow()
    stamp = now.strftime("%Y-%m-%dT%H:%M:%S")
    hist = parse_history(history)

    try:
        sold = int(sold)
    except (TypeError, ValueError):
        return hist

    today = now.strftime("%Y-%m-%d")
    if hist and str(hist[-1][0])[:10] == today:
        hist[-1] = (stamp, sold)
    else:
        hist.append((stamp, sold))
    return hist[-MAX_SNAPSHOTS:]


def sold_window(history, days: int = DEFAULT_WINDOW_DAYS) -> tuple[int, float]:
    """
    (units sold over the last `days`, days actually observed)

    When the history is shorter than `days` we use whatever exists and report
    the observed span separately — "3 sales" means something very different
    over one day than over seven.
    """
    hist = parse_history(history)
    if len(hist) < 2:
        return 0, 0.0

    latest_stamp, latest_sold = hist[-1]
    latest = _dt(latest_stamp)
    cutoff = latest - timedelta(days=days)

    base = hist[0]
    for stamp, sold in hist:
        if _dt(stamp) <= cutoff:
            base = (stamp, sold)     # last point before the window opens
        else:
            break

    growth = latest_sold - base[1]
    if growth < 0:
        growth = 0                   # relisted, counter reset
    observed = (latest - _dt(base[0])).total_seconds() / 86400
    return growth, round(max(observed, 0.0), 2)


def last_sale(history) -> str | None:
    """Date (YYYY-MM-DD) of the most recent snapshot where the total rose."""
    hist = parse_history(history)
    found = None
    for prev, cur in zip(hist, hist[1:]):
        if cur[1] > prev[1]:
            found = cur[0]
    return found[:10] if found else None


def rate_per_day(history, days: int = DEFAULT_WINDOW_DAYS) -> float:
    """
    Average daily sales over the observed window.

    The divisor is at least one day: when snapshots land only hours apart,
    dividing by the real gap inflated the rate many times over.
    """
    growth, observed = sold_window(history, days)
    if not growth:
        return 0.0
    return round(growth / max(observed, 1.0), 2)


def listing_age_days(created, now: datetime | None = None) -> float:
    """Listing age in days, from `itemCreationDate`."""
    start = _dt(created)
    if start is None:
        return 0.0
    delta = (now or datetime.utcnow()) - start
    return round(max(delta.total_seconds() / 86400, 0.0), 1)


def lifetime_rate(sold, created, now: datetime | None = None) -> float:
    """
    Lifetime average sales per day.

    ESSENTIAL ON DAY ONE: the history is still empty, so sold_window() returns
    0 and nothing would ever rank as a TOP COMPETITOR. This gives a rough rate
    from the listing's age and makes the first ranking possible.
    """
    try:
        sold = int(sold or 0)
    except (TypeError, ValueError):
        return 0.0
    age = listing_age_days(created, now)
    if sold <= 0 or age <= 0:
        return 0.0
    return round(sold / max(age, 1.0), 3)


# ---------------------------------------------------------------------------
# Storage interface
# ---------------------------------------------------------------------------

class BaseStore:
    """
    Competitor rows + AI verdict cache + per-product "last checked" stamps.

    rows:  {key: row dict} — the history lives inside the row
    cache: {"myLegacy|theirLegacy": {fingerprint, verdict, pairs, ...}}
    runs:  {myLegacy: iso} — when each product was last checked
    """

    def load_rows(self) -> dict:
        raise NotImplementedError

    def save_rows(self, rows: dict, touched_products=()) -> None:
        raise NotImplementedError

    def load_cache(self) -> dict:
        raise NotImplementedError

    def save_cache(self, cache: dict) -> None:
        raise NotImplementedError

    def get_run(self, legacy_id) -> str | None:
        raise NotImplementedError

    def set_run(self, legacy_id, stamp=None) -> None:
        raise NotImplementedError


class JsonStore(BaseStore):
    """Local file, used via `--store history.json`. No network."""

    def __init__(self, path: str):
        self.path = path
        self._data = {"rows": {}, "cache": {}, "runs": {}}
        self._read()

    def _read(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            for key in ("rows", "cache", "runs"):
                if isinstance(loaded.get(key), dict):
                    self._data[key] = loaded[key]
        except (OSError, ValueError) as e:
            print(f"[store] could not read {self.path} ({e}) — starting empty")

    def _write(self) -> None:
        folder = os.path.dirname(os.path.abspath(self.path))
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, ensure_ascii=False, indent=1)

    def load_rows(self) -> dict:
        return dict(self._data["rows"])

    def save_rows(self, rows: dict, touched_products=()) -> None:
        self._data["rows"] = dict(rows)
        self._write()

    def load_cache(self) -> dict:
        return dict(self._data["cache"])

    def save_cache(self, cache: dict) -> None:
        self._data["cache"] = dict(cache)
        self._write()

    def get_run(self, legacy_id) -> str | None:
        return self._data["runs"].get(str(legacy_id))

    def set_run(self, legacy_id, stamp=None) -> None:
        self._data["runs"][str(legacy_id)] = (
            stamp or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"))
        self._write()
