// Cloudflare Worker: lets the dashboard read vahan.ms live from the browser.
//
// vahan.ms sends the Access-Control-Allow-Origin header twice, and browsers refuse a response with a duplicated
// CORS header. This worker fetches the same data server-side and sends the header once. It forwards only
// GET /api/share and /api/meta, and caches each answer for five minutes so many visitors cost vahan.ms one request.

const ORIGIN = "https://vahan.ms";
const ALLOWED = new Set(["/api/share", "/api/meta"]);

export default {
  async fetch(request, env, ctx) {
    if (request.method !== "GET") return new Response("Method not allowed", { status: 405 });
    const url = new URL(request.url);
    if (!ALLOWED.has(url.pathname)) return new Response("Not found", { status: 404 });

    const cache = caches.default;
    const cacheKey = new Request(url.toString(), { method: "GET" });
    let res = await cache.match(cacheKey);
    if (res) return res;

    const upstream = await fetch(ORIGIN + url.pathname + url.search, {
      headers: { "User-Agent": "vahan-nse-tracker (dashboard proxy)", Accept: "application/json" },
    });
    const headers = new Headers(upstream.headers);
    headers.delete("Access-Control-Allow-Origin");          // removes every copy
    headers.set("Access-Control-Allow-Origin", "*");        // one copy
    headers.set("Cache-Control", "public, max-age=300");
    res = new Response(upstream.body, { status: upstream.status, headers });
    if (upstream.ok) ctx.waitUntil(cache.put(cacheKey, res.clone()));
    return res;
  },
};
