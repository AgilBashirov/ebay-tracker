"""
AI judge — answers "are these two listings the SAME product?"

WHY AI: title comparison cannot separate "Shampoo 16 oz" from "Shampoo 16 oz
Refill Pouch", and no rule set covers every case. But the AI cannot be fully
trusted either, so every SAME verdict it returns is re-checked by
matching.guard_conflicts().

FREE PROVIDER CHAIN: when one provider hits its daily limit we move to the
next (Gemini -> Groq -> OpenRouter -> Ollama). Limit NUMBERS are deliberately
not hardcoded — providers change them often; we only react to the 429 signal
in the response.

ID SCHEME: the model is given short ids — my variants are M1..Mn, candidates
are C1..Cn and their variants C3.V2. Those ids are translated back to real
item_ids INSIDE this module, so callers never see the AI's scheme.
"""
import base64
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import config

# Models that hit their daily limit during this run — never asked again.
_exhausted: set[str] = set()

# Request counter per model (shown in the run report).
CALLS: dict[str, int] = {}

GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
              "{model}:generateContent")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# If a 429 body contains any of these, the limit is DAILY — waiting is
# pointless and we abandon the model for this run.
_DAILY_MARKERS = (
    "perday", "per day", "per-day", "daily", "rpd", "tokens per day",
    "requests per day", "quota exceeded", "exhausted your current quota",
)
# A retryDelay above this also counts as a daily limit (too long to wait).
_MAX_WAIT_SEC = 90


def reset() -> None:
    """Clear counters and the exhausted list at the start of a run."""
    _exhausted.clear()
    CALLS.clear()


# ---------------------------------------------------------------------------
# Provider chain
# ---------------------------------------------------------------------------

def chain() -> list[tuple[str, str]]:
    """
    (provider, model) pairs to try, in order.

    AI_CHAIN overrides everything:
    "gemini:gemini-flash-latest,groq:openai/gpt-oss-120b"
    """
    if config.AI_CHAIN.strip():
        out = []
        for part in config.AI_CHAIN.split(","):
            part = part.strip()
            if ":" in part:
                provider, _, model = part.partition(":")
                out.append((provider.strip().lower(), model.strip()))
        return out

    out = []
    if config.GEMINI_API_KEY:
        for model in config.GEMINI_MODELS.split(","):
            model = model.strip()
            if model:
                out.append(("gemini", model))
    if config.GROQ_API_KEY and config.GROQ_MODEL:
        out.append(("groq", config.GROQ_MODEL))
    if config.OPENROUTER_API_KEY and config.OPENROUTER_MODEL:
        out.append(("openrouter", config.OPENROUTER_MODEL))
    if config.OLLAMA_URL and config.OLLAMA_MODEL:
        out.append(("ollama", config.OLLAMA_MODEL))
    return out


def is_available() -> bool:
    """Can the AI be used at all? If not, the caller falls back to rules."""
    return bool(chain())


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class _Skip(Exception):
    """This model will not work (bad key, missing model) — move on."""


class _Exhausted(Exception):
    """Daily limit reached — never ask this model again."""


# Groq sits behind Cloudflare, which blocks urllib's default
# "Python-urllib/3.12" signature (HTTP 403, "error code: 1010"). That looks
# exactly like an invalid key but the key is fine — it just needs a
# User-Agent.
USER_AGENT = "ebay-tracker/1.0 (+https://github.com/AgilBashirov/ebay-tracker)"


def _post(url: str, payload: dict, headers: dict, timeout: int = 90) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        **headers})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def _retry_delay(text: str) -> float:
    """Extract `retryDelay: "57s"` from a response body."""
    found = re.search(r'"retryDelay"\s*:\s*"?(\d+(?:\.\d+)?)s', text)
    return float(found.group(1)) if found else 0.0


def _classify_http_error(err: urllib.error.HTTPError) -> Exception:
    """
    Turn an HTTP error into a decision: wait, abandon, or mark exhausted.

    A 429 comes in two flavours: a per-minute limit (waiting helps) and a
    daily limit (waiting is useless — move to the next model). We tell them
    apart from the response text.
    """
    try:
        text = err.read().decode("utf-8", errors="ignore")
    except Exception:
        text = ""
    low = text.lower()

    if err.code == 429:
        delay = _retry_delay(text)
        if any(m in low for m in _DAILY_MARKERS) or delay > _MAX_WAIT_SEC:
            return _Exhausted(f"daily limit: {text[:160]}")
        return TimeoutError(str(max(delay, 5.0)))      # wait and retry

    if err.code in (400, 401, 403, 404):
        return _Skip(f"HTTP {err.code}: {text[:160]}")
    return ConnectionError(f"HTTP {err.code}: {text[:160]}")  # 5xx — backoff


def _call_with_retry(label: str, send) -> str:
    """
    Call one model: retry on per-minute 429 and 5xx, give up otherwise.
    Returns the model's raw text response.
    """
    delay = 2.0
    for attempt in range(3):
        try:
            CALLS[label] = CALLS.get(label, 0) + 1
            return send()
        except urllib.error.HTTPError as e:
            decided = _classify_http_error(e)
            if isinstance(decided, (_Exhausted, _Skip)):
                raise decided
            if attempt == 2:
                raise _Skip(f"{label}: out of retries ({decided})")
            wait = float(str(decided)) if isinstance(decided, TimeoutError) else delay
            print(f"[ai] {label}: retrying in {wait:.0f}s")
            time.sleep(min(wait, _MAX_WAIT_SEC))
            delay *= 2
        except Exception as e:
            if attempt == 2:
                raise _Skip(f"{label}: {e}")
            time.sleep(delay)
            delay *= 2
    raise _Skip(label)


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _gemini(model: str, system: str, user_text: str, images: list) -> str:
    parts = [{"text": user_text}]
    for mime, data in images:
        parts.append({"inlineData": {"mimeType": mime, "data": data}})

    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0,
                             "responseMimeType": "application/json"},
    }

    def send():
        data = _post(GEMINI_URL.format(model=model), payload,
                     {"x-goog-api-key": config.GEMINI_API_KEY})
        chunks = []
        for cand in data.get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts") or []:
                # Thought parts are not the answer and corrupt the JSON.
                if part.get("thought"):
                    continue
                if part.get("text"):
                    chunks.append(part["text"])
        return "".join(chunks)

    return _call_with_retry(f"gemini:{model}", send)


# ---------------------------------------------------------------------------
# OpenAI-compatible (Groq / OpenRouter / Ollama)
# ---------------------------------------------------------------------------

def _openai_compatible(provider: str, model: str, system: str,
                       user_text: str, images: list) -> str:
    if provider == "groq":
        url, key = GROQ_URL, config.GROQ_API_KEY
    elif provider == "openrouter":
        url, key = OPENROUTER_URL, config.OPENROUTER_API_KEY
    else:
        url = config.OLLAMA_URL.rstrip("/") + "/v1/chat/completions"
        key = ""

    content = [{"type": "text", "text": user_text}]
    if images and config.AI_IMAGES_OPENAI:
        for mime, data in images:
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{data}"}})
    user_msg = {"role": "user",
                "content": content if len(content) > 1 else user_text}

    base = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": system}, user_msg]}
    headers = {"Authorization": f"Bearer {key}"} if key else {}

    def send():
        try:
            data = _post(url, {**base, "response_format": {"type": "json_object"}},
                         headers)
        except urllib.error.HTTPError as e:
            # Some models reject response_format — retry without it.
            if e.code != 400:
                raise
            data = _post(url, base, headers)
        choices = data.get("choices") or []
        if not choices:
            return ""
        return (choices[0].get("message") or {}).get("content") or ""

    return _call_with_retry(f"{provider}:{model}", send)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You decide whether two eBay listings sell the EXACT SAME product variant.

Answer SAME only if ALL of these hold:
- same brand and same model / product line
- same size / volume / weight / capacity
- same count (pack size, number of units, capsules, sheets, servings)
- same colour / flavour / scent when that is what distinguishes the variants
- same condition group (new vs refurbished vs used)

Answer DIFFERENT when the candidate is an accessory, spare part, refill,
container, lid, cap, case, or anything described as "for X" / "compatible
with X" rather than being X itself.

Answer DIFFERENT_VARIANT when it is the same product family but a different
size, colour or count, or a bundle/lot whose contents differ.

Answer UNSURE when the evidence is incomplete. NEVER guess SAME.

Critical rule about multi-variation listings: their TITLE lists every size the
seller offers (e.g. "Shampoo 16oz 32oz 40oz") and therefore proves nothing.
Decide at VARIANT level and return every matching pair (Mi, Cx.Vj).

GTIN equality is strong evidence of a match. A very different price is a hint,
never proof.

Reply with JSON only, no prose:
{"results":[{"id":"C1","verdict":"SAME|DIFFERENT_VARIANT|DIFFERENT|UNSURE",
  "matches":[{"mine":"M1","theirs":"C1.V2"}],"confidence":0-100,
  "reason":"short reason in English, max 20 words"}]}"""

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _plain(html, limit: int) -> str:
    """Flatten an HTML description to plain text and truncate it."""
    text = _TAG_RE.sub(" ", str(html or ""))
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = _WS_RE.sub(" ", text).strip()
    return text[:limit]


def _variant_lines(prefix: str, listing: dict, is_mine: bool = False) -> list[str]:
    """
    Variant lines.

    My variants are named "M1", "M2"; a candidate's variants are "C3.V2", so
    the id itself says which candidate they belong to.
    """
    lines = []
    for idx, var in enumerate(listing.get("variants") or [], start=1):
        bits = [f"M{idx}" if is_mine else f"{prefix}.V{idx}"]
        if var.get("label"):
            bits.append(str(var["label"]))
        if var.get("aspects"):
            bits.append(" ".join(f"{k}={v}" for k, v in var["aspects"].items()))
        if var.get("price") is not None:
            bits.append(f"price=${var['price']}")
        if var.get("gtin"):
            bits.append(f"gtin={var['gtin']}")
        lines.append("  " + " | ".join(bits))
    return lines


def _describe(label: str, listing: dict, desc_chars: int,
              variant_prefix: str, is_mine: bool = False) -> str:
    head = [
        f"{label}: {listing.get('title') or ''}",
        f"  brand={listing.get('brand') or '-'} mpn={listing.get('mpn') or '-'} "
        f"gtin={listing.get('gtin') or '-'} condition={listing.get('condition') or '-'}"
        f" lot_size={listing.get('lot_size') or '-'}",
    ]
    desc = _plain(listing.get("description"), desc_chars)
    if desc:
        head.append(f"  description: {desc}")
    return "\n".join(head + _variant_lines(variant_prefix, listing, is_mine))


def build_prompt(mine: dict, candidates: list[dict]) -> str:
    """The user message. My variants are M1.., candidates are C1.."""
    blocks = [_describe("MY LISTING", mine, config.AI_DESC_CHARS_MINE,
                        "M", is_mine=True)]

    for idx, cand in enumerate(candidates, start=1):
        blocks.append(_describe(f"CANDIDATE C{idx}", cand,
                                config.AI_DESC_CHARS, f"C{idx}"))
    blocks.append("For every candidate return one result object.")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Images
# ---------------------------------------------------------------------------
MAX_IMAGE_BYTES = 1_500_000


def _fetch_image(url: str):
    """
    Download an image and base64-encode it. eBay images are requested at
    s-l500 — the s-l1600 version fills the request limit and adds nothing.
    """
    if not url:
        return None
    small = re.sub(r"s-l\d+", "s-l500", url)
    try:
        with urllib.request.urlopen(small, timeout=20) as resp:
            raw = resp.read(MAX_IMAGE_BYTES + 1)
    except Exception:
        return None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return None
    return ("image/jpeg", base64.b64encode(raw).decode())


def _collect_images(mine: dict, candidates: list[dict]) -> list:
    if not config.AI_USE_IMAGES:
        return []
    out = []
    for listing in [mine] + list(candidates):
        got = _fetch_image(listing.get("image"))
        if got:
            out.append(got)
    return out


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)


def parse_response(raw: str) -> list[dict]:
    """
    Extract the `results` list from the model's reply.

    Models often wrap the JSON in a ```json block or prefix it with a
    sentence, so we try the fence first, then the outermost {...}.
    """
    text = str(raw or "").strip()
    if not text:
        return []

    found = _FENCE_RE.search(text)
    if found:
        text = found.group(1).strip()

    data = None
    try:
        data = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start:end + 1])
            except ValueError:
                data = None
    if not isinstance(data, dict):
        return []

    results = data.get("results")
    return results if isinstance(results, list) else []


_VERDICTS = {"SAME", "DIFFERENT_VARIANT", "DIFFERENT", "UNSURE"}


def _resolve_pairs(matches, mine: dict, cand: dict, cand_index: int):
    """
    Translate the AI's ids into real variant item_ids.

    Ids that do not exist are dropped — models sometimes invent them, and an
    invented pair is no basis for calling two listings identical.
    """
    my_vars = mine.get("variants") or []
    their_vars = cand.get("variants") or []
    out = []
    for item in matches or []:
        if not isinstance(item, dict):
            continue
        mine_id = str(item.get("mine") or "").upper().strip()
        theirs_id = str(item.get("theirs") or "").upper().strip()

        m = re.fullmatch(r"M(\d+)", mine_id)
        t = re.fullmatch(rf"C{cand_index}\.V(\d+)", theirs_id)
        if not m or not t:
            continue
        mi, ti = int(m.group(1)) - 1, int(t.group(1)) - 1
        if not (0 <= mi < len(my_vars)) or not (0 <= ti < len(their_vars)):
            continue
        pair = (my_vars[mi].get("item_id"), their_vars[ti].get("item_id"))
        if pair not in out:
            out.append(pair)
    return out


def normalize_results(raw_results: list, mine: dict,
                      candidates: list[dict], model: str) -> dict:
    """
    Convert raw AI results into a dict keyed by the candidate's legacy_id.

    Callers see neither "C3" nor "V2" — only real item_ids.
    """
    by_index = {}
    for item in raw_results or []:
        if not isinstance(item, dict):
            continue
        found = re.fullmatch(r"C(\d+)", str(item.get("id") or "").upper().strip())
        if found:
            by_index[int(found.group(1))] = item

    out = {}
    for idx, cand in enumerate(candidates, start=1):
        item = by_index.get(idx)
        if not item:
            continue

        verdict = str(item.get("verdict") or "").upper().strip()
        if verdict not in _VERDICTS:
            verdict = "UNSURE"

        try:
            confidence = float(item.get("confidence") or 0)
        except (TypeError, ValueError):
            confidence = 0.0

        pairs = _resolve_pairs(item.get("matches"), mine, cand, idx)

        # SAME but no pairs given. If both sides have exactly one variant the
        # intent is clear; otherwise we do not know WHICH size matched, so
        # SAME cannot be accepted.
        if verdict == "SAME" and not pairs:
            my_vars = mine.get("variants") or []
            their_vars = cand.get("variants") or []
            if len(my_vars) == 1 and len(their_vars) == 1:
                pairs = [(my_vars[0].get("item_id"), their_vars[0].get("item_id"))]
            else:
                verdict = "UNSURE"
                item = {**item, "reason": "AI did not say which variant matched"}

        out[str(cand.get("legacy_id"))] = {
            "verdict": verdict,
            "pairs": pairs,
            "confidence": confidence,
            "reason": str(item.get("reason") or "")[:200],
            "model": model,
        }
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def ask(mine: dict, candidates: list[dict]) -> dict:
    """
    Ask the AI about the candidates, in batches.

    Returns {candidate legacy_id: {verdict, pairs, confidence, reason, model}}

    A candidate with NO answer is left OUT of the result — the caller reads
    that as "the AI did not answer", does not cache it, and asks again the
    next day.
    """
    if not candidates or not is_available():
        return {}

    size = max(1, config.AI_BATCH_SIZE)
    answers = {}
    for start in range(0, len(candidates), size):
        batch = candidates[start:start + size]
        answers.update(_ask_batch(mine, batch))
    return answers


def _ask_batch(mine: dict, batch: list[dict]) -> dict:
    system = SYSTEM_PROMPT
    user_text = build_prompt(mine, batch)
    images = _collect_images(mine, batch)

    for provider, model in chain():
        label = f"{provider}:{model}"
        if label in _exhausted:
            continue
        try:
            if provider == "gemini":
                raw = _gemini(model, system, user_text, images)
            else:
                raw = _openai_compatible(provider, model, system,
                                         user_text, images)
        except _Exhausted:
            print(f"[ai] {label} hit its daily limit — moving to next model")
            _exhausted.add(label)
            continue
        except _Skip as e:
            print(f"[ai] {label} skipped: {e}")
            continue

        results = parse_response(raw)
        if results:
            return normalize_results(results, mine, batch, label)
        print(f"[ai] {label}: unreadable reply, moving to next model")

    print("[ai] no model answered — this batch falls back to the rules")
    return {}
