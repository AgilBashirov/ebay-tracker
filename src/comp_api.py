"""
Local HTTP API — send a product id, get your competitors' links back.

RUN:
    python src/comp_api.py --port 8787

CALL:
    curl "http://127.0.0.1:8787/competitors?id=157968828656&format=links"
    curl "http://127.0.0.1:8787/competitors?id=https://www.ebay.com/itm/157968828656"

BEHAVIOUR — SYNCHRONOUS: the request runs the whole check and returns the full
result at the end. It takes 30-120 seconds, because one product needs dozens
of eBay calls plus AI batches. That is fine locally (nothing cuts a localhost
request short), but far too long for a remote host — hence the 127.0.0.1
default.

SECURITY: binds to 127.0.0.1 only, so it is not reachable from outside. With
--host 0.0.0.0 a COMP_API_TOKEN becomes MANDATORY; otherwise anyone could
burn your daily eBay (5000) and free AI quota.

ENGINE CONTRACT: this module only calls competitors.process_product(), which
must return:

    {"my_item": {...}, "competitors": [...], "unsure": [...],
     "stats": {...}, "checked_at": "..."}

or, on failure:

    {"error": {"code": 400|404|503, "message": "..."}}

So the API is not coupled to exception classes, which lets this shell be
tested on its own before the engine exists.
"""
import argparse
import csv
import hmac
import io
import json
import os
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

for _stream in (sys.stdout, sys.stderr):
    try:
        if (_stream.encoding or "").lower().replace("-", "") != "utf8":
            _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# This file is run DIRECTLY: `python src/comp_api.py`. We do not rely on
# PYTHONPATH because on Windows the separator is ";", so `PYTHONPATH=.:src`
# silently fails there and the imports break.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _path in (os.path.dirname(_HERE), _HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import config
import ebay_api

# The engine. Replaced by a fake in tests. While None, the competitors module
# is imported on first use (lazily) so /health can answer without loading it.
PROCESS = None

# Parallel requests for the same id: the second one does NOT start a second
# check, it waits for the first and reuses its result. Otherwise two browser
# tabs would burn the API budget twice.
#
# A lock alone does NOT achieve this — it only serialises the requests, each
# of which would still call the engine. Hence the short-lived result cache.
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_recent: dict[str, tuple[float, dict]] = {}

# Within this many seconds the same id is not recomputed. Kept short: the goal
# is to swallow duplicate requests, not to act as a cache.
SINGLE_FLIGHT_SEC = float(os.environ.get("COMP_API_DEDUP_SEC", "60"))

CSV_COLUMNS = ("status", "seller", "their_variant", "my_variant", "price",
               "shipping", "total", "diff", "sold", "sold_7d", "last_sale",
               "confidence", "found_by", "reason", "url")


def _process(item_id: str, variation_id=None, cache_only: bool = False) -> dict:
    global PROCESS
    if PROCESS is None:
        import competitors                      # heavy import, only on demand
        PROCESS = competitors.process_product
    return PROCESS(item_id, variation_id=variation_id, cache_only=cache_only)


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        if key not in _locks:
            _locks[key] = threading.Lock()
        return _locks[key]


# ---------------------------------------------------------------------------
# Request parsing
# ---------------------------------------------------------------------------

def parse_target(raw: str) -> tuple[str | None, str | None]:
    """
    Extract (legacy_id, variation_id) from the `id` parameter.

    Accepts both a bare number and a full eBay link. When the link carries
    `?var=123`, only THAT variant is the target — which answers "who competes
    with my 16 oz variant".
    """
    text = (raw or "").strip()
    if not text:
        return None, None

    variation = None
    if "://" in text or "ebay." in text:
        query = urllib.parse.urlparse(text).query
        values = urllib.parse.parse_qs(query).get("var")
        if values and str(values[0]).isdigit():
            variation = str(values[0])
        return ebay_api.extract_item_id(text), variation

    digits = "".join(ch for ch in text if ch.isdigit())
    if 9 <= len(digits) <= 15:
        return digits, None
    return None, None


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------

def _rows(result: dict, include_unsure: bool) -> list[dict]:
    rows = list(result.get("competitors") or [])
    if include_unsure:
        rows += list(result.get("unsure") or [])
    return rows


def as_links(result: dict, include_unsure: bool) -> str:
    """One link per line — the simplest way to consume this."""
    seen, out = set(), []
    for row in _rows(result, include_unsure):
        url = (row.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return "\n".join(out) + ("\n" if out else "")


def as_csv(result: dict, include_unsure: bool) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    for row in _rows(result, include_unsure):
        writer.writerow({key: row.get(key, "") for key in CSV_COLUMNS})
    return buf.getvalue()


def health() -> dict:
    """Keys and limits, without loading the engine."""
    import ai_judge
    return {
        "ok": True,
        "ebay_keys": ebay_api.is_configured(),
        "ai_available": ai_judge.is_available(),
        "ai_chain": [f"{p}:{m}" for p, m in ai_judge.chain()],
        "ai_calls": dict(ai_judge.CALLS),
        "budget_per_run": config.COMP_MAX_API_CALLS,
        "min_confidence": config.COMP_MIN_CONFIDENCE,
        "top_n": config.COMP_TOP_N,
    }


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "ebay-competitors/1.0"
    require_token = False
    loopback_only = True
    expected_port = 0

    def _host_allowed(self) -> bool:
        """
        Reject DNS-rebinding requests.

        A malicious page can point attacker.com at 127.0.0.1 and then read our
        replies, because to the browser it is same-origin. Binding to loopback
        does NOT stop that — only checking the Host header does. We also refuse
        anything carrying an Origin header: no browser page is meant to call
        this API, so an Origin means a cross-site request, which would at the
        very least burn the eBay and AI budget.
        """
        if self.headers.get("Origin"):
            return False
        if not self.loopback_only:
            return True          # public mode is guarded by the token instead
        host = (self.headers.get("Host") or "").strip()
        if host.startswith("["):                      # [::1]:8787
            hostname = host[1:host.find("]")] if "]" in host else host
        else:
            hostname = host.split(":")[0]
        return hostname.lower() in ("127.0.0.1", "localhost", "::1", "")

    def _send(self, code: int, body: str, content_type: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False, indent=1),
                   "application/json")

    def _error(self, code: int, message: str) -> None:
        self._json(code, {"error": {"code": code, "message": message}})

    def log_message(self, fmt, *args):
        # The default log prints the full request line, which here may hold a
        # listing link, and the token sits in a header. We log our own
        # short line instead.
        return

    def _authorized(self) -> bool:
        if not self.require_token:
            return True
        token = config.COMP_API_TOKEN
        given = (self.headers.get("Authorization") or "").strip()
        if given.lower().startswith("bearer "):
            given = given[7:].strip()
        if not token:
            return False
        # Constant-time compare so the response time cannot leak the token
        # one character at a time.
        return hmac.compare_digest(given.encode("utf-8"),
                                   token.encode("utf-8"))

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        route = parsed.path.rstrip("/") or "/"

        if not self._host_allowed():
            self._error(403, "request rejected: unexpected Host or Origin "
                             "header (DNS-rebinding protection)")
            return

        if not self._authorized():
            self._error(401, "Authorization: Bearer <COMP_API_TOKEN> required")
            return

        if route in ("/", "/health"):
            self._json(200, health())
            return

        if route != "/competitors":
            self._error(404, f"unknown path: {parsed.path}")
            return

        item_id, variation = parse_target(params.get("id", ""))
        if not item_id:
            self._error(400, "the id parameter is required: a listing number "
                             "(e.g. 157968828656) or a full eBay link")
            return
        if params.get("var", "").isdigit():
            variation = params["var"]

        fmt = (params.get("format") or "json").lower()
        include_unsure = (params.get("include") or "").lower() == "unsure"
        cache_only = params.get("cache") in ("1", "true", "yes")

        started = time.time()
        key = f"{item_id}|{variation or ''}|{int(cache_only)}"
        force = params.get("fresh") in ("1", "true", "yes")
        reused = False

        # Single flight: the second request waits on the lock and then takes
        # the FIRST one's result instead of running another check.
        with _lock_for(key):
            cached = _recent.get(key)
            if cached and not force and time.time() - cached[0] < SINGLE_FLIGHT_SEC:
                result, reused = cached[1], True
            else:
                try:
                    result = _process(item_id, variation, cache_only)
                except Exception as exc:                  # engine crashed
                    print(f"[api] {item_id} ERROR: "
                          f"{exc.__class__.__name__}: {exc}")
                    self._error(500, f"{exc.__class__.__name__}: {exc}")
                    return
                if isinstance(result, dict) and not result.get("error"):
                    _recent[key] = (time.time(), result)
        took = time.time() - started

        if not isinstance(result, dict):
            self._error(500, "the engine returned an unexpected response")
            return

        failed = result.get("error")
        if failed:
            code = int(failed.get("code") or 500)
            print(f"[api] {item_id} -> {code} ({took:.1f}s)")
            self._error(code, str(failed.get("message") or "error"))
            return

        found = len(result.get("competitors") or [])
        unsure = len(result.get("unsure") or [])
        source = "reused from memory" if reused else (
            f"{(result.get('stats') or {}).get('ebay_calls', '?')} eBay calls")
        print(f"[api] {item_id} -> {found} competitors, {unsure} to check "
              f"({took:.1f}s, {source})")

        if fmt == "links":
            self._send(200, as_links(result, include_unsure), "text/plain")
        elif fmt == "csv":
            self._send(200, as_csv(result, include_unsure), "text/csv")
        else:
            payload = dict(result)
            payload["took_seconds"] = round(took, 1)
            payload["reused"] = reused
            if not include_unsure:
                payload.pop("unsure", None)
            self._json(200, payload)


def demo_process(item_id: str, variation_id=None, cache_only=False) -> dict:
    """
    --demo mode: shows the response shape without eBay keys.

    The data is FAKE and the response is flagged with `"demo": true` so it can
    never be mistaken for a real result. For checking the interface only.
    """
    link = f"https://www.ebay.com/itm/{item_id}"
    return {
        "demo": True,
        "my_item": {"legacy_id": item_id, "title": "DEMO - Acme Shampoo 16 oz",
                    "url": link + (f"?var={variation_id}" if variation_id else ""),
                    "variants": [{"label": "Size: 16 oz"}]},
        "competitors": [
            {"status": "TOP COMPETITOR",
             "url": "https://www.ebay.com/itm/222000000001?var=11",
             "seller": "demo_fastshop", "price": 13.49, "shipping": 0.0,
             "total": 13.49, "diff": -2.50, "my_variant": "Size: 16 oz",
             "their_variant": "Size: 16 oz", "sold": 46, "sold_7d": 6,
             "last_sale": "2026-11-09", "confidence": 95, "found_by": "gtin",
             "reason": "same GTIN"},
            {"status": "COMPETITOR",
             "url": "https://www.ebay.com/itm/333000000002",
             "seller": "demo_bigbox", "price": 16.99, "shipping": 2.00,
             "total": 18.99, "diff": 2.99, "my_variant": "Size: 16 oz",
             "their_variant": "16 oz", "sold": 3, "sold_7d": 0,
             "last_sale": None, "confidence": 88, "found_by": "title",
             "reason": "same brand and size"},
        ],
        "unsure": [
            {"status": "CHECK",
             "url": "https://www.ebay.com/itm/444000000003",
             "seller": "demo_maybe", "price": 11.00, "shipping": 0.0,
             "total": 11.00, "diff": -4.99, "my_variant": "Size: 16 oz",
             "their_variant": "16 oz 2 Pack", "sold": 12, "sold_7d": 1,
             "last_sale": "2026-11-08", "confidence": 60, "found_by": "title",
             "reason": "different pack size (1 vs 2)"},
        ],
        "stats": {"searches": 7, "candidates_found": 142,
                  "candidates_checked": 28, "ebay_calls": 0, "ai_calls": 0,
                  "rejected": 110, "out_of_stock": 4},
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def build_server(host: str, port: int) -> ThreadingHTTPServer:
    """
    Build the server. A token is MANDATORY when opening to the network.

    The check deliberately happens BEFORE the server starts: binding 0.0.0.0
    without a token would expose your API quota to everyone.
    """
    public = host not in ("127.0.0.1", "localhost", "::1")
    if public and not config.COMP_API_TOKEN:
        raise SystemExit(
            f"'{host}' is reachable from the network but COMP_API_TOKEN is not "
            "set.\nTo protect your API keys, add COMP_API_TOKEN=... to .env or "
            "use --host 127.0.0.1.")

    handler = type("BoundHandler", (Handler,), {
        "require_token": public,
        "loopback_only": not public,
        "expected_port": port,
    })
    return ThreadingHTTPServer((host, port), handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Local HTTP API for competitor lookup")
    parser.add_argument("--host", default="127.0.0.1",
                        help="default 127.0.0.1 (this machine only)")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--demo", action="store_true",
                        help="answer with FAKE data and no eBay keys "
                             "(for checking the interface only)")
    args = parser.parse_args(argv)

    global PROCESS
    if args.demo:
        PROCESS = demo_process

    server = build_server(args.host, args.port)
    base = f"http://{args.host}:{args.port}"
    print(f"Competitor API listening on {base}")
    print(f"  {base}/competitors?id=157968828656&format=links")
    print(f"  {base}/health")
    if args.demo:
        print("DEMO MODE - data is fake, no eBay requests are made.")
    elif not ebay_api.is_configured():
        print("WARNING: no eBay keys - requests will return an error.\n"
              "    Add EBAY_CLIENT_ID / EBAY_CLIENT_SECRET to .env,\n"
              "    or start with --demo to inspect the interface.")
    print("Stop with Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
