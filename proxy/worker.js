/**
 * Cloudflare Worker that fronts the last.fm API so the key never reaches the
 * browser. The page calls this instead of ws.audioscrobbler.com; the key lives
 * here as a secret and is added server-side.
 *
 * Deploy: see README.md in this folder.
 */

const UPSTREAM = "https://ws.audioscrobbler.com/2.0/";

/* Only the reads the app actually makes. Anything else is refused, so this
   cannot be repurposed as somebody's free last.fm proxy. */
const ALLOWED_METHODS = new Set(["user.getrecenttracks", "artist.getTopTags"]);

/* Parameters forwarded upstream. Anything not listed here is dropped —
   notably api_key, so a caller cannot override the server's key. */
const FORWARD = ["method", "user", "limit", "page", "from", "to", "artist", "autocorrect"];

/* An artist's tags are the same for every visitor and barely change, so they
   are cached at the edge for a month: the second person to look up a given
   artist costs last.fm nothing.

   Nothing else is cached at all. Scrobbles are one person's listening history,
   and the 60s default this used to carry meant a visitor's pages sat in
   Cloudflare's cache after they left — which the site's own front page denied.
   A method absent from this table is fetched fresh and stored nowhere. */
const CACHE_TTL = { "artist.getTopTags": 2592000 };

const ALLOWED_ORIGINS = new Set([
  "https://shyni-ludo.github.io",
  "http://127.0.0.1:8765",   // local testing via `python -m http.server 8765`
  "http://localhost:8765",
]);

function corsHeaders(origin) {
  const h = {
    "Vary": "Origin",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Max-Age": "86400",
  };
  if (ALLOWED_ORIGINS.has(origin)) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

function fail(status, message, headers) {
  return new Response(JSON.stringify({ error: status, message }), {
    status,
    headers: { ...headers, "Content-Type": "application/json; charset=utf-8" },
  });
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const head = corsHeaders(origin);

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: head });
    if (request.method !== "GET") return fail(405, "GET only", head);

    /* A browser always sends Origin cross-origin, so this keeps other sites
       from pointing their app at this worker. It is not a security boundary —
       any script outside a browser can set whatever Origin it likes. The real
       protection is that the key stays server-side and Cloudflare caps the
       free plan at 100k requests/day. */
    if (origin && !ALLOWED_ORIGINS.has(origin)) return fail(403, "origin not allowed", head);

    if (!env.LASTFM_KEY) return fail(500, "worker is missing its LASTFM_KEY secret", head);

    const inUrl = new URL(request.url);
    const method = inUrl.searchParams.get("method") || "";
    if (!ALLOWED_METHODS.has(method)) return fail(400, `method "${method}" is not proxied`, head);

    const out = new URL(UPSTREAM);
    for (const k of FORWARD) {
      const v = inUrl.searchParams.get(k);
      if (v !== null) out.searchParams.set(k, v);
    }
    out.searchParams.set("format", "json");
    out.searchParams.set("api_key", env.LASTFM_KEY);

    const ttl = CACHE_TTL[method] || 0;
    let res;
    try {
      res = await fetch(out.toString(), {
        cf: ttl
          ? { cacheTtl: ttl, cacheEverything: true }
          : { cacheTtl: 0, cacheEverything: false },
        headers: { "User-Agent": "listening-report (github.com/shyni-ludo/listening)" },
      });
    } catch (e) {
      return fail(502, "could not reach last.fm", head);
    }

    /* Pass the upstream body through untouched — the app already understands
       last.fm's own error envelope. Never echo the outgoing URL: it has the key. */
    return new Response(res.body, {
      status: res.status,
      headers: {
        ...head,
        "Content-Type": "application/json; charset=utf-8",
        // and tell every cache between here and the visitor the same thing
        "Cache-Control": ttl ? `public, max-age=${ttl}` : "no-store",
      },
    });
  },
};
