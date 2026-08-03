# last.fm key proxy

A Cloudflare Worker that holds the last.fm API key server-side so it never
reaches a visitor's browser. Free tier is 100,000 requests/day; one full-history
load of a 170k-scrobble account is roughly 850 requests, so that is about 115
full loads a day.

## Deploy

You need a Cloudflare account (free, no card) and Node installed.

> **On Windows PowerShell, use `npx.cmd` rather than `npx`.** Plain `npx`
> resolves to `npx.ps1`, which PowerShell refuses to run under its default
> execution policy (`npx.ps1 cannot be loaded because running scripts is
> disabled on this system`). The `.cmd` shim does the same job and is not
> subject to that policy, so there is no need to change any system setting.
> The commands below use `npx.cmd`; drop the `.cmd` on macOS and Linux.

**1. Rotate the key first.** The current one has been public in this repo's git
history since the first commit, so proxying the *old* key protects nothing. Get
a fresh one at <https://www.last.fm/api/account/create>.

**2. Log in and publish** — from inside this `proxy/` folder:

```bash
npx.cmd wrangler login
```

```bash
npx.cmd wrangler deploy
```

**3. Give it the key.** This stores the key encrypted at Cloudflare; it is never
written to disk in this repo:

```bash
npx.cmd wrangler secret put LASTFM_KEY
```

Paste the new key when prompted.

**4. Point the site at it.** `wrangler deploy` prints a URL like
`https://listening-lastfm.<your-subdomain>.workers.dev`. Write it to
`proxy_url.txt` in the repo root, then rebuild:

```bash
echo https://listening-lastfm.YOUR-SUBDOMAIN.workers.dev > ../proxy_url.txt
```

```bash
cd .. && python build_web.py
```

`build_web.py` prints `PROXY MODE` and ships **no key at all** in `index.html`.
Commit and push as usual.

## Checking it worked

After deploying, `index.html` should contain no key in any form:

```bash
grep -c "api_key" index.html
```

And in the browser, requests should go to `workers.dev`, not to
`ws.audioscrobbler.com`.

## Going back

Delete `proxy_url.txt` and re-run `python build_web.py`. The build falls back to
embedding the (obfuscated) key and calling last.fm directly.

## Notes

- Visitors who enter their own key under *advanced* bypass the proxy entirely
  and call last.fm directly with it. That is intended — their key, their call.
- `ALLOWED_ORIGINS` in `worker.js` lists the sites allowed to use the worker.
  Add any new domain you host the page on. This stops other *websites* using
  your worker; it is not a hard security boundary, since anything outside a
  browser can spoof an `Origin` header. The point of the worker is that the key
  is not in the client, not that the endpoint is unguessable.
- Only `user.getrecenttracks` is forwarded, and `api_key` is stripped from
  incoming requests, so a caller cannot substitute their own.
