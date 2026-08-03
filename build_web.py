"""
Build the public web app: injects your last.fm API key into app_template.html
and writes the final index.html (the file you deploy to GitHub Pages).

The key is XOR-folded against a fixed pad and base64'd rather than written out
in the clear. That is obfuscation, not encryption: it keeps the key out of
view-source and away from the bots that scrape public repos for API keys, but
last.fm takes the key as a URL parameter, so anyone who opens their browser's
network tab can still read it. Hiding it properly needs a server-side proxy.

Run: python build_web.py
"""

import base64
import os
import sys

TEMPLATE = "app_template.html"
OUT = "index.html"
KEY_FILE = "lastfm_key.txt"
PLACEHOLDER = "__LASTFM_API_KEY__"
PAD = "listening-report"   # must match KEY_PAD in app_template.html


def fold(key):
    """XOR against a repeating pad, then base64 — mirrored by the page at load."""
    raw = bytes(ord(c) ^ ord(PAD[i % len(PAD)]) for i, c in enumerate(key))
    return base64.b64encode(raw).decode("ascii")


def main():
    if not os.path.exists(KEY_FILE):
        sys.exit(f"{KEY_FILE} not found — run fetch_scrobbles.py once first, "
                 "or create it containing just your API key.")
    with open(KEY_FILE, encoding="utf-8") as f:
        key = f.read().strip()
    if not key:
        sys.exit(f"{KEY_FILE} is empty.")

    with open(TEMPLATE, encoding="utf-8") as f:
        html = f.read()
    if PLACEHOLDER not in html:
        sys.exit(f"placeholder {PLACEHOLDER} not found in {TEMPLATE}")

    folded = fold(key)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html.replace(PLACEHOLDER, folded))
    if key in open(OUT, encoding="utf-8").read():
        sys.exit(f"refusing to ship: {OUT} still contains the key in the clear")
    print(f"Saved {OUT} (API key folded in from {KEY_FILE})")
    print("Note: the key is obfuscated, not hidden. It is still sent as a URL")
    print("parameter on every last.fm call, so anyone reading their own browser's")
    print("network tab can recover it. If it gets abused, make a new one at")
    print("https://www.last.fm/api/account/create and re-run this script.")


if __name__ == "__main__":
    main()
