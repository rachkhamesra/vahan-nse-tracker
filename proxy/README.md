# Live data proxy (Cloudflare Worker)

The dashboard can read registrations from vahan.ms live in the browser, but vahan.ms sends its CORS header twice and
browsers reject that. `worker.js` fetches the same data server-side and sends the header once.

## Set up (about five minutes, free)

1. Create a free account at https://dash.cloudflare.com and open Workers & Pages, then Create, then Create Worker.
2. Name it (for example `vahan-proxy`), click Deploy, then Edit code.
3. Replace the code with the contents of `worker.js`, click Deploy.
4. Copy the worker URL (it looks like `https://vahan-proxy.<your-subdomain>.workers.dev`).
5. In `index.html`, set `const LIVE_API="https://vahan-proxy.<your-subdomain>.workers.dev/api/";` and push.

Check it works by opening `<worker URL>/api/meta` in a browser. It should return JSON with `rebuilt_at`.
