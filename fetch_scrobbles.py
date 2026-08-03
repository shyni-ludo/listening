"""
Fetch scrobbles directly from the Last.fm API — no third-party site needed.

Usage:
    python fetch_scrobbles.py                 # prompts for your username
    python fetch_scrobbles.py --user NAME     # direct

Needs a free Last.fm API key (get one in ~30 seconds at
https://www.last.fm/api/account/create). The key is read from the
LASTFM_API_KEY environment variable, or asked once and saved to
lastfm_key.txt (keep that file private).

Writes scrobbles.csv in the same format as the original export. If the CSV
already exists, only scrobbles newer than the latest one are downloaded
(incremental update), then build_site.py can be run to refresh index.html.
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

API_URL = "https://ws.audioscrobbler.com/2.0/"
KEY_FILE = "lastfm_key.txt"
CSV_FILE = "scrobbles.csv"
PAGE_SIZE = 200          # API maximum
PAGE_DELAY = 0.25        # seconds between requests (stay well under rate limit)
MAX_RETRIES = 4

CSV_HEADER = ["uts", "utc_time", "artist", "artist_mbid",
              "album", "album_mbid", "track", "track_mbid"]


def get_api_key():
    key = os.environ.get("LASTFM_API_KEY", "").strip()
    if key:
        return key
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key
    print("No API key found. Get a free one at "
          "https://www.last.fm/api/account/create")
    key = input("Paste your Last.fm API key: ").strip()
    if not key:
        sys.exit("An API key is required.")
    with open(KEY_FILE, "w", encoding="utf-8") as f:
        f.write(key)
    print(f"Saved to {KEY_FILE} (won't ask again).\n")
    return key


def api_get(params, retries=MAX_RETRIES):
    params = {**params, "format": "json"}
    url = API_URL + "?" + urllib.parse.urlencode(params)
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # last.fm puts the error JSON in the body (e.g. 403 + error 10)
            try:
                data = json.loads(e.read().decode("utf-8"))
            except Exception:
                data = {"error": e.code, "message": str(e)}
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == retries:
                raise
            wait = 2 ** attempt
            print(f"  network error ({e}); retrying in {wait}s...")
            time.sleep(wait)
            continue
        code = data.get("error")
        if code is None:
            return data
        msg = data.get("message", "")
        if code == 6:
            sys.exit("User not found — check the username spelling.")
        if code in (4, 10, 26):
            sys.exit("Invalid or suspended API key — delete lastfm_key.txt "
                     "and run again to re-enter it.")
        retryable = code in (8, 11, 16, 29) or (isinstance(code, int) and code >= 500)
        if retryable and attempt < retries:
            wait = 2 ** attempt
            print(f"  last.fm hiccup ({msg}); retrying in {wait}s...")
            time.sleep(wait)
            continue
        sys.exit(f"Last.fm API error {code}: {msg}")
    raise RuntimeError("unreachable")


def parse_tracks(payload):
    """Extract (uts, utc_time, artist, artist_mbid, album, album_mbid,
    track, track_mbid) rows from one API page, skipping now-playing."""
    rows = []
    for t in payload["recenttracks"].get("track", []):
        if "date" not in t:            # currently playing track has no date
            continue
        uts = int(t["date"]["uts"])
        utc_time = datetime.fromtimestamp(uts, tz=timezone.utc).strftime(
            "%d %b %Y, %H:%M")
        rows.append([
            uts, utc_time,
            t["artist"]["#text"], t["artist"].get("mbid", ""),
            t["album"]["#text"], t["album"].get("mbid", ""),
            t["name"], t.get("mbid", ""),
        ])
    return rows


def existing_max_uts(path):
    if not os.path.exists(path):
        return None
    max_uts = 0
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and row[0].isdigit():
                max_uts = max(max_uts, int(row[0]))
    return max_uts or None


def fetch_scrobbles(user, api_key, since=None):
    """Download scrobbles (newest first). If `since` is a unix timestamp,
    only fetch scrobbles after it."""
    params = {"method": "user.getrecenttracks", "user": user,
              "api_key": api_key, "limit": PAGE_SIZE, "page": 1}
    if since:
        params["from"] = since
    first = api_get(params)
    attr = first["recenttracks"]["@attr"]
    total_pages = int(attr["totalPages"])
    total = int(attr["total"])
    span = f" (only new ones)" if since else ""
    print(f"{total:,} scrobbles to download{span} — {total_pages:,} pages")

    rows = parse_tracks(first)
    for page in range(2, total_pages + 1):
        time.sleep(PAGE_DELAY)
        params["page"] = page
        rows.extend(parse_tracks(api_get(params)))
        if page % 20 == 0 or page == total_pages:
            print(f"  page {page:,}/{total_pages:,} "
                  f"({len(rows):,} scrobbles so far)")
    return rows


def main():
    ap = argparse.ArgumentParser(description="Download last.fm scrobbles to CSV")
    ap.add_argument("--user", help="last.fm username")
    ap.add_argument("--full", action="store_true",
                    help="re-download everything, even if a CSV exists")
    args = ap.parse_args()

    user = args.user or input("Your last.fm username: ").strip()
    if not user:
        sys.exit("A username is required.")
    api_key = get_api_key()

    since = None if args.full else existing_max_uts(CSV_FILE)
    if since:
        print(f"Found existing {CSV_FILE} — fetching scrobbles after "
              f"{datetime.fromtimestamp(since, tz=timezone.utc):%b %d, %Y %H:%M} UTC")

    new_rows = fetch_scrobbles(user, api_key, since=since + 1 if since else None)
    if not new_rows:
        print("No new scrobbles — your CSV is already up to date.")
        return

    # merge with existing rows, dedupe on (uts, track, artist)
    merged = {}
    if since:
        with open(CSV_FILE, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            for row in reader:
                if row:
                    merged[(row[0], row[6], row[2])] = row
    for row in new_rows:
        merged[(str(row[0]), row[6], row[2])] = [str(row[0])] + row[1:]

    out = sorted(merged.values(), key=lambda r: int(r[0]), reverse=True)
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(CSV_HEADER)
        writer.writerows(out)
    print(f"Wrote {len(out):,} scrobbles to {CSV_FILE} "
          f"({len(new_rows):,} new).")

    answer = input("\nRebuild index.html now? [Y/n] ").strip().lower()
    if answer in ("", "y", "yes"):
        subprocess.run([sys.executable, "build_site.py"], check=True)


if __name__ == "__main__":
    main()
