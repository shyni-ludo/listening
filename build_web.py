"""
Build the public web app from app_template.html and write index.html (the file
GitHub Pages serves).

Two modes, chosen by whether proxy_url.txt exists:

  PROXY MODE (proxy_url.txt present)
      No key of any kind goes into index.html. The page calls the Cloudflare
      Worker in proxy/, which holds the key as a server-side secret. This is
      the only arrangement where a visitor genuinely cannot read the key.

  DIRECT MODE (no proxy_url.txt)
      The key is XOR-folded against a fixed pad and base64'd instead of written
      out in the clear. That is obfuscation, not secrecy: it keeps the key out
      of view-source and away from bots that scrape public repos for API keys,
      but last.fm takes the key as a URL parameter, so anyone who opens their
      browser's network tab can still read it.

Run: python build_web.py
"""

import base64
import os
import sys

TEMPLATE = "app_template.html"
OUT = "index.html"
KEY_FILE = "lastfm_key.txt"
PROXY_FILE = "proxy_url.txt"
KEY_PLACEHOLDER = "__LASTFM_API_KEY__"
PROXY_PLACEHOLDER = "__LASTFM_PROXY__"
PAD = "listening-report"   # must match KEY_PAD in app_template.html


def fold(key):
    """XOR against a repeating pad, then base64 - mirrored by the page at load."""
    raw = bytes(ord(c) ^ ord(PAD[i % len(PAD)]) for i, c in enumerate(key))
    return base64.b64encode(raw).decode("ascii")


def read_trimmed(path):
    with open(path, encoding="utf-8") as f:
        return f.read().strip()


def main():
    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    for ph in (KEY_PLACEHOLDER, PROXY_PLACEHOLDER):
        if ph not in html:
            sys.exit(f"placeholder {ph} not found in {TEMPLATE}")

    proxy = read_trimmed(PROXY_FILE) if os.path.exists(PROXY_FILE) else ""
    if proxy and not proxy.startswith("https://"):
        sys.exit(f"{PROXY_FILE} must hold an https:// URL (got: {proxy!r})")

    key = read_trimmed(KEY_FILE) if os.path.exists(KEY_FILE) else ""

    if proxy:
        html = html.replace(PROXY_PLACEHOLDER, proxy).replace(KEY_PLACEHOLDER, "")
    else:
        if not key:
            sys.exit(f"{KEY_FILE} not found or empty, and no {PROXY_FILE} either — "
                     "run fetch_scrobbles.py once, or set up proxy/ (see its README).")
        html = html.replace(PROXY_PLACEHOLDER, "").replace(KEY_PLACEHOLDER, fold(key))

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)

    # Never ship the plaintext key, in either mode.
    built = read_trimmed(OUT)
    if key and key in built:
        sys.exit(f"refusing to ship: {OUT} contains the key in the clear")
    if proxy:
        if key and fold(key) in built:
            sys.exit(f"refusing to ship: {OUT} still carries the key in proxy mode")
        print(f"Saved {OUT} - PROXY MODE via {proxy}")
        print("No API key of any kind is present in the built page.")
    else:
        print(f"Saved {OUT} - DIRECT MODE (key folded in from {KEY_FILE})")
        print("The key is obfuscated, not hidden: it is still sent as a URL")
        print("parameter on every last.fm call, so anyone reading their own")
        print("browser's network tab can recover it. To hide it properly, set up")
        print("the Cloudflare Worker in proxy/ - see proxy/README.md.")


if __name__ == "__main__":
    main()
