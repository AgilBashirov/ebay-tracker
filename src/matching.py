"""
Deterministic competitor-matching rules. No AI, no network calls.

This module is the precision core. It runs in two places:

  1. BEFORE the AI — hard_reject() and GTIN matching. Saves AI quota and
     settles the obvious cases for free.
  2. AFTER the AI — guard_conflicts(). Every pair the AI called SAME is
     re-checked here, because the AI does confuse 16 oz with 32 oz, a single
     unit with a 2-pack, and a product with its own lid. A conflict found
     here OVERRIDES the AI verdict.

GUIDING RULE: doubt counts against the competitor. Anything we are not sure
about becomes "CHECK", never "COMPETITOR" — a false positive is the most
expensive mistake this system can make.

Every function is unit-tested in test_competitors.py.
"""
import re

# ---------------------------------------------------------------------------
# GTIN (UPC / EAN)
# ---------------------------------------------------------------------------
# Junk values sellers type when a product has no barcode.
_GTIN_JUNK = {
    "does not apply", "doesnotapply", "doesn't apply", "not apply",
    "n/a", "na", "none", "null", "nil", "no", "nogtin", "unbranded",
    "unknown", "-", "--",
}


def normalize_gtin(raw) -> str | None:
    """
    Normalize a GTIN to 14 digits.

    WHY 14: the same product is listed as UPC-12 by one seller and EAN-13 by
    another. Left-padding both to 14 makes them compare equal — otherwise one
    product would look like two different GTINs.

    Returns None for junk text, wrong length, or all zeros.
    """
    text = str(raw or "").strip().lower()
    if not text or text in _GTIN_JUNK:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    # Valid GS1 formats: GTIN-8, UPC-12, EAN-13, GTIN-14
    if len(digits) not in (8, 12, 13, 14):
        return None
    if set(digits) == {"0"}:
        return None
    return digits.rjust(14, "0")


def gtins_match(a, b) -> bool:
    """True only when both GTINs are valid and equal."""
    ga, gb = normalize_gtin(a), normalize_gtin(b)
    return bool(ga and gb and ga == gb)


def gtins_conflict(a, b) -> bool:
    """Both sides have a valid GTIN and they differ."""
    ga, gb = normalize_gtin(a), normalize_gtin(b)
    return bool(ga and gb and ga != gb)


# ---------------------------------------------------------------------------
# Brand
# ---------------------------------------------------------------------------
# These are not brands — they mean "no brand given", so they must not take
# part in comparisons. Otherwise "Unbranded" would match "Unbranded".
GENERIC_BRANDS = {
    "unbranded", "generic", "does not apply", "doesnotapply", "none", "null",
    "no brand", "nobrand", "unknown", "n/a", "na", "oem", "unbranded/generic",
    "handmade", "-", "nobrandname",
}


def clean_brand(raw) -> str | None:
    """Comparable brand name. Generic or empty values return None."""
    text = re.sub(r"[^a-z0-9]+", " ", str(raw or "").lower()).strip()
    if not text or text in GENERIC_BRANDS:
        return None
    collapsed = text.replace(" ", "")
    if collapsed in {b.replace(" ", "").replace("/", "") for b in GENERIC_BRANDS}:
        return None
    return collapsed


def brands_conflict(a, b) -> bool:
    """
    Both brands known, neither generic, and they differ.

    Note: "HP" and "Hewlett Packard" count as different here, so the pair
    falls through to CHECK. That is deliberate — better than showing a wrong
    competitor.
    """
    ca, cb = clean_brand(a), clean_brand(b)
    return bool(ca and cb and ca != cb)


# ---------------------------------------------------------------------------
# Condition
# ---------------------------------------------------------------------------
CONDITION_GROUPS = {
    "new": {"1000", "1500", "1750"},
    "refurbished": {"2000", "2010", "2020", "2030", "2500"},
    "used": {"3000", "4000", "5000", "6000"},
}


def condition_group(condition_id) -> str | None:
    """Map an eBay condition id to a group. Unknown ids return None."""
    cid = str(condition_id or "").strip()
    for name, ids in CONDITION_GROUPS.items():
        if cid in ids:
            return name
    return None


def conditions_conflict(a, b) -> bool:
    ga, gb = condition_group(a), condition_group(b)
    return bool(ga and gb and ga != gb)


# ---------------------------------------------------------------------------
# Title similarity
# ---------------------------------------------------------------------------
# Marketing noise. These words appear in every listing and would make
# everything look similar to everything, so they are dropped.
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "with", "in", "on", "to", "by",
    "new", "brand", "free", "fast", "ship", "shipping", "shipped", "usa", "us",
    "best", "top", "hot", "sale", "premium", "quality", "genuine", "original",
    "authentic", "sealed", "oem", "official", "set", "lot", "pack", "pcs",
    "piece", "pieces", "item", "items", "product", "day", "days", "same",
    "warranty", "returns", "deal", "deals", "bulk", "wholesale",
    "exp", "exp.", "fresh", "value", "size", "x",
}

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9.\-]*")


def tokens(title) -> set[str]:
    """Reduce a title to a comparable set of words."""
    raw = _WORD_RE.findall(str(title or "").lower())
    out = set()
    for word in raw:
        word = word.strip(".-")
        if not word or word in STOPWORDS or len(word) == 1:
            continue
        out.add(word)
    return out


def title_score(mine, theirs) -> float:
    """
    0.6 * Jaccard + 0.4 * coverage

    Jaccard  — overall similarity of the two titles.
    coverage — how much of MY title appears in theirs. This keeps sellers
               with long, keyword-stuffed titles from being penalised.
    """
    ta, tb = tokens(mine), tokens(theirs)
    if not ta or not tb:
        return 0.0
    shared = len(ta & tb)
    jaccard = shared / len(ta | tb)
    coverage = shared / len(ta)
    return round(0.6 * jaccard + 0.4 * coverage, 4)


def prefilter_score(my_title, cand_title, *, my_brand=None, my_mpn=None,
                    found_by="title", my_price=None, cand_price=None) -> float:
    """
    Is this candidate worth sending to the AI? (cheap filter, saves quota)

    Title similarity plus a bonus for how strong the evidence is: being found
    by GTIN/EPID is the strongest signal, being found by title the weakest.
    """
    score = title_score(my_title, cand_title)
    low = str(cand_title or "").lower()

    brand = clean_brand(my_brand)
    if brand and brand in re.sub(r"[^a-z0-9]+", "", low):
        score += 0.15

    mpn = re.sub(r"[^a-z0-9]+", "", str(my_mpn or "").lower())
    if len(mpn) >= 4 and mpn in re.sub(r"[^a-z0-9]+", "", low):
        score += 0.30

    if found_by in ("gtin", "epid"):
        score += 0.50
    elif found_by == "image":
        score += 0.20

    # A price more than ~3x apart is usually an accessory or a bulk lot.
    if my_price and cand_price:
        ratio = cand_price / my_price
        if ratio < 0.3 or ratio > 3.5:
            score -= 0.25

    return round(score, 4)


# ---------------------------------------------------------------------------
# Pack size
# ---------------------------------------------------------------------------
_PACK_PATTERNS = (
    re.compile(r"\b(?:pack|pk|lot|set|bundle|case|box)\s*of\s*(\d{1,3})\b"),
    re.compile(r"\b(\d{1,3})\s*[-–]?\s*(?:pack|packs|pk|pks)\b"),
    re.compile(r"\b(\d{1,3})\s*[xX*]\s*\d+(?:\.\d+)?\s*(?:oz|ml|l|g|kg|lb|ct|count|fl)\b"),
    re.compile(r"\b[xX]\s*(\d{1,3})\b"),
    re.compile(r"\b(?:qty|quantity|number\s+in\s+pack|package\s+quantity)\s*[:=]?\s*(\d{1,3})\b"),
)


def parse_pack(text, lot_size=None) -> int | None:
    """
    Units per pack. Returns None when not stated (which means "unknown",
    not 1).

    eBay's own `lotSize` field is the most reliable source, so it wins over
    anything parsed out of the title or aspects. Note it comes back as 0 when
    unset, which is why the range check starts above 1.
    """
    try:
        lot = int(lot_size)
        if 1 < lot <= 500:
            return lot
    except (TypeError, ValueError):
        pass

    low = str(text or "").lower()
    for pattern in _PACK_PATTERNS:
        for found in pattern.findall(low):
            try:
                n = int(found)
            except (TypeError, ValueError):
                continue
            if 1 < n <= 500:
                return n
    return None


def packs_conflict(a_pack, b_pack) -> bool:
    """
    Do the pack sizes contradict each other?

    "Unknown" (None) reads as 1: a listing that mentions no pack size in its
    title or aspects is almost always selling a single unit. That is what
    makes "single unit" vs "2 Pack" a conflict — exactly the case where the
    same product is sold at double the price.
    """
    return (a_pack or 1) != (b_pack or 1)


# ---------------------------------------------------------------------------
# Size / volume / weight / capacity
# ---------------------------------------------------------------------------
# Each family converts to its own base unit, then families are compared
# one by one. NOTE: mAh, W and V are SEPARATE families — 1000 mAh is not
# the same thing as 1000 W.
UNIT_FAMILIES = {
    "mass": {"mg": 0.001, "g": 1.0, "gram": 1.0, "grams": 1.0, "kg": 1000.0,
             "lb": 453.592, "lbs": 453.592, "pound": 453.592, "pounds": 453.592,
             "oz": 28.3495, "ounce": 28.3495, "ounces": 28.3495},
    "volume": {"ml": 1.0, "l": 1000.0, "lt": 1000.0, "liter": 1000.0,
               "liters": 1000.0, "litre": 1000.0, "fl oz": 29.5735,
               "floz": 29.5735, "fluid ounce": 29.5735, "gal": 3785.41,
               "gallon": 3785.41, "qt": 946.353, "quart": 946.353,
               "pt": 473.176, "pint": 473.176},
    "length": {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "inch": 25.4,
               "inches": 25.4, '"': 25.4, "ft": 304.8, "foot": 304.8,
               "feet": 304.8},
    "storage": {"gb": 1.0, "tb": 1024.0, "mb": 0.001},
    "capacity_mah": {"mah": 1.0, "ah": 1000.0},
    "power": {"w": 1.0, "kw": 1000.0, "watt": 1.0, "watts": 1.0},
    "voltage": {"v": 1.0, "volt": 1.0, "volts": 1.0},
    "count": {"count": 1.0, "ct": 1.0, "capsule": 1.0, "capsules": 1.0,
              "tablet": 1.0, "tablets": 1.0, "softgel": 1.0, "softgels": 1.0,
              "pcs": 1.0, "pieces": 1.0, "sheet": 1.0, "sheets": 1.0,
              "roll": 1.0, "rolls": 1.0, "pod": 1.0, "pods": 1.0,
              "serving": 1.0, "servings": 1.0, "wipes": 1.0, "bags": 1.0},
}

# "oz" IS AMBIGUOUS: it means both weight (28.35 g) and fluid volume
# (29.57 ml), and the title never says which. So an oz value is written into
# BOTH families. As a result "16 oz" matches "1 lb" through the mass family
# and "16 fl oz" through the volume family — whichever family the other side
# actually has is the one that gets compared.
_OZ_AS_VOLUME = 29.5735

# Longest unit first, so "fl oz" is matched before "oz".
_ALL_UNITS = sorted(
    {u for units in UNIT_FAMILIES.values() for u in units} | {"fl oz", "floz"},
    key=len, reverse=True,
)
_UNIT_ALT = "|".join(re.escape(u) for u in _ALL_UNITS)
_MEASURE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(" + _UNIT_ALT + r")(?![a-z0-9])", re.I)

# Is the unit followed by a digit? Used to spot phrases like "3 in 1".
_DIGIT_AFTER_RE = re.compile(r"\s*\d")

TOLERANCE = 0.03   # +/- 3%


def parse_measures(text) -> dict[str, set[float]]:
    """
    Pull measurements out of text: {family: {values in base unit}}

    "16 oz"  -> {"mass": {453.59}, "volume": {473.18}}  (ambiguous unit)
    "500 ml" -> {"volume": {500.0}}
    """
    text = str(text or "")
    out: dict[str, set[float]] = {}
    for found in _MEASURE_RE.finditer(text):
        raw_value, raw_unit = found.group(1), found.group(2)
        try:
            value = float(raw_value.replace(",", "."))
        except ValueError:
            continue
        if value <= 0:
            continue
        unit = raw_unit.lower().replace(" ", "") if raw_unit.lower() != '"' else '"'

        # "3 in 1", "5 in 1" — marketing phrasing, not a measurement.
        # Without this guard "3 in 1 Shampoo" parsed as 3 inches and clashed
        # with a competitor selling "5 in 1".
        if unit == "in" and _DIGIT_AFTER_RE.match(text, found.end()):
            continue

        for family, units in UNIT_FAMILIES.items():
            factor = units.get(unit) or units.get(raw_unit.lower())
            if factor:
                out.setdefault(family, set()).add(round(value * factor, 4))

        # "oz" also reads as a volume
        if unit in ("oz", "ounce", "ounces"):
            out.setdefault("volume", set()).add(round(value * _OZ_AS_VOLUME, 4))

    return out


def _any_close(values_a, values_b) -> bool:
    for a in values_a:
        for b in values_b:
            if a <= 0 or b <= 0:
                continue
            if abs(a - b) / max(a, b) <= TOLERANCE:
                return True
    return False


def measures_conflict(text_a, text_b) -> str | None:
    """
    Return the name of the conflicting family, or None.

    Rule: if BOTH sides have a value in some family and no pair of those
    values agrees within 3%, that is a conflict. A value present on only one
    side means "unknown", not a conflict.
    """
    ma, mb = parse_measures(text_a), parse_measures(text_b)
    for family in UNIT_FAMILIES:
        va, vb = ma.get(family), mb.get(family)
        if va and vb and not _any_close(va, vb):
            return family
    return None


# ---------------------------------------------------------------------------
# Accessory / spare-part detection (no AI needed)
# ---------------------------------------------------------------------------
# The single most valuable thing the AI does: "Whey Protein 2LB" and "Whey
# Protein Scoop" have near-identical titles, but one is the product and the
# other is its measuring scoop. This list catches that without the AI.
ACCESSORY_MARKERS = (
    "lid", "cap only", "caps only", "scoop", "shaker", "bottle only",
    "box only", "empty", "case", "cover", "sleeve", "sticker", "label",
    "decal", "manual", "guide", "sample", "samples", "packet", "sachet",
    "trial size", "travel size", "refill", "replacement", "spare", "spare part",
    "accessory", "accessories", "holder", "stand", "mount", "adapter",
    "for use with", "compatible with", "fits ", "replacement for",
)


def accessory_conflict(my_text, their_text) -> str | None:
    """
    Is the candidate an accessory or part while I sell the product itself?

    Only a marker on ONE side counts. If we are both selling lids, that is
    normal competition, so markers present on both sides are ignored.
    """
    mine = str(my_text or "").lower()
    theirs = str(their_text or "").lower()
    for marker in ACCESSORY_MARKERS:
        if marker in theirs and marker not in mine:
            return marker.strip()
    return None


# ---------------------------------------------------------------------------
# Categorical aspects (flavour, colour, scent) — not measurements
# ---------------------------------------------------------------------------
# Vanilla and Chocolate sell at the same price in the same size, so the
# measurement guard cannot separate them. The live probe showed one listing
# with five flavours whose sold counts were completely different — meaning
# they are genuinely separate competitors.
CATEGORICAL_ASPECTS = ("flavor", "flavour", "color", "colour", "scent",
                       "style", "type", "material", "model")


def _norm_value(raw) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(raw or "").lower()).strip()


def categorical_conflict(my_aspects, their_aspects) -> str | None:
    """
    Both sides declare the same categorical aspect but with different values.

    If one value contains the other it is not a conflict ("Vanilla" inside
    "French Vanilla") — sellers write the same flavour at different lengths.
    """
    mine = {str(k).strip().lower(): _norm_value(v)
            for k, v in (my_aspects or {}).items()}
    theirs = {str(k).strip().lower(): _norm_value(v)
              for k, v in (their_aspects or {}).items()}

    for name in CATEGORICAL_ASPECTS:
        a, b = mine.get(name), theirs.get(name)
        if not a or not b or a == b:
            continue
        if a in b or b in a:
            continue
        return f"{name}: {a} != {b}"
    return None


# ---------------------------------------------------------------------------
# Where the comparison text comes from — the biggest source of mistakes
# ---------------------------------------------------------------------------
# Only aspects that identify the product. Shipping fields (Item Weight,
# Dimensions) are DELIBERATELY absent: sellers fill them in roughly, which
# made identical products look like different sizes.
ASPECT_ALLOWLIST = {
    "size", "volume", "capacity", "storage capacity", "net weight",
    "number in pack", "unit quantity", "pack size", "package quantity",
    "quantity", "count", "model", "color", "colour", "flavor", "flavour",
    "scent", "style", "type", "bundle description", "size type", "liquid volume",
}

ASPECT_DENYLIST = {
    "item weight", "item dimensions", "dimensions", "package dimensions",
    "shipping weight", "package weight", "item length", "item width",
    "item height",
}


def _aspect_text(aspects: dict, extra_names=()) -> str:
    """"name: value" text for the allowed aspects only."""
    allowed = ASPECT_ALLOWLIST | {str(n).strip().lower() for n in extra_names}
    parts = []
    for name, value in (aspects or {}).items():
        key = str(name).strip().lower()
        if key in ASPECT_DENYLIST:
            continue
        if key in allowed:
            parts.append(f"{name}: {value}")
    return " | ".join(parts)


def variant_measure_text(listing: dict, variant: dict) -> str:
    """
    Build the text used for size and pack comparison.

    IMPORTANT RULE: for a multi-variation listing the TITLE IS NOT USED. Such
    a title lists every size the seller offers ("Shampoo 16oz 32oz 40oz"). If
    we read the title, every variant would look compatible with every other
    variant, and a competitor selling just one size would clash falsely. The
    variant's OWN aspects name exactly one size.

    For a simple single-variant listing the title is the only source, so it
    is used.
    """
    extra = listing.get("variation_aspects") or ()
    parts = [
        _aspect_text(variant.get("aspects"), extra),
        _aspect_text(listing.get("common_aspects"), extra),
        str(variant.get("label") or ""),
    ]
    if not listing.get("is_group"):
        parts.insert(0, str(listing.get("title") or ""))
    return " | ".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def hard_reject(mine: dict, theirs: dict) -> tuple[bool, str]:
    """
    Reject WITHOUT asking the AI: the plainly different cases.
    Saves quota and keeps the prompt clean.
    """
    if brands_conflict(mine.get("brand"), theirs.get("brand")):
        return True, (f"different brand ({mine.get('brand')} != "
                      f"{theirs.get('brand')})")
    if conditions_conflict(mine.get("condition_id"), theirs.get("condition_id")):
        return True, "different item condition"
    return False, ""


_FAMILY_LABEL = {
    "mass": "weight", "volume": "volume", "length": "length",
    "storage": "storage", "capacity_mah": "battery", "power": "power",
    "voltage": "voltage", "count": "unit count",
}


def guard_conflicts(my_listing: dict, my_variant: dict,
                    their_listing: dict, their_variant: dict) -> list[str]:
    """
    Final check on every pair the AI called SAME.

    An empty list means the pair is clean. Any conflict drops the pair, and a
    candidate left with no clean pair becomes CHECK. This is where an AI
    mistake gets caught.
    """
    issues = []

    my_gtin = my_variant.get("gtin") or my_listing.get("gtin")
    their_gtin = their_variant.get("gtin") or their_listing.get("gtin")
    if gtins_conflict(my_gtin, their_gtin):
        issues.append("different GTIN")

    if brands_conflict(my_listing.get("brand"), their_listing.get("brand")):
        issues.append("different brand")

    if conditions_conflict(my_listing.get("condition_id"),
                           their_listing.get("condition_id")):
        issues.append("different condition")

    my_text = variant_measure_text(my_listing, my_variant)
    their_text = variant_measure_text(their_listing, their_variant)

    my_pack = parse_pack(my_text, my_listing.get("lot_size"))
    their_pack = parse_pack(their_text, their_listing.get("lot_size"))
    if packs_conflict(my_pack, their_pack):
        issues.append(f"different pack size ({my_pack or 1} vs "
                      f"{their_pack or 1})")

    family = measures_conflict(my_text, their_text)
    if family:
        issues.append(f"size mismatch ({_FAMILY_LABEL.get(family, family)})")

    # Flavour/colour/scent are not measurements, so they get their own check.
    # Variant aspects win over the listing-wide ones.
    mine_aspects = {**(my_listing.get("common_aspects") or {}),
                    **(my_variant.get("aspects") or {})}
    their_aspects = {**(their_listing.get("common_aspects") or {}),
                     **(their_variant.get("aspects") or {})}
    categorical = categorical_conflict(mine_aspects, their_aspects)
    if categorical:
        issues.append(f"different attribute ({categorical})")

    # Accessory/part — checked on the title, since aspects rarely say so.
    marker = accessory_conflict(my_listing.get("title"),
                                their_listing.get("title"))
    if marker:
        issues.append(f"accessory/part wording ('{marker}')")

    return issues
