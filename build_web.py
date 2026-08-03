"""
Build the public web app: injects your last.fm API key into app_template.html
and writes the final index.html (the file you deploy to GitHub Pages).

Run: python build_web.py
"""

import os
import sys

TEMPLATE = "app_template.html"
OUT = "index.html"
KEY_FILE = "lastfm_key.txt"
PLACEHOLDER = "__LASTFM_API_KEY__"


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

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html.replace(PLACEHOLDER, key))
    print(f"Saved {OUT} (API key embedded from {KEY_FILE})")
    print("Note: index.html now contains your key. That's fine for a personal")
    print("site, but anyone viewing the page source can see it. If it ever gets")
    print("abused, regenerate it at https://www.last.fm/api/account/create")


if __name__ == "__main__":
    main()
