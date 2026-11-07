import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// The shell document decides which modules load and which element ids exist,
// so a frozen install-day copy breaks the phone alone. These tests run the
// real static/app/sw.js in a fake ServiceWorkerGlobalScope and watch the
// precached index.html: a changed one on the network wins, the cache answers
// when the network is down, and the refreshed document is what the next
// offline open reads.

const SW_PATH = new URL("../../static/app/sw.js", import.meta.url);
const ORIGIN = "https://ocr.example";
const SW_SCRIPT = `${ORIGIN}/app/sw.js`;
const INDEX = "/app/index.html";
const SHELL_DIR = "/app/";

function urlOf(request) {
  return typeof request === "string" ? request : request.url;
}

async function startSW() {
  const source = await readFile(SW_PATH, "utf8");
  const stores = new Map(); // cache name -> Map(url -> body)
  const net = new Map(); // url -> body
  const networkCalls = [];
  let onlineNow = true;

  function cacheOf(name) {
    if (!stores.has(name)) stores.set(name, new Map());
    const entries = stores.get(name);
    return {
      async addAll(requests) {
        for (const request of requests) {
          const url = new URL(request, SW_SCRIPT).href;
          entries.set(url, await (await fetchFn(url)).text());
        }
      },
      async match(request) {
        const body = entries.get(urlOf(request));
        return body === undefined ? undefined : new Response(body, { status: 200 });
      },
      async put(request, response) {
        entries.set(urlOf(request), await response.text());
      },
    };
  }

  const caches = {
    open: async (name) => cacheOf(name),
    async match(request) {
      for (const entries of stores.values()) {
        const body = entries.get(urlOf(request));
        if (body !== undefined) return new Response(body, { status: 200 });
      }
      return undefined;
    },
    keys: async () => [...stores.keys()],
    delete: async (name) => stores.delete(name),
  };

  async function fetchFn(request) {
    const url = urlOf(request);
    networkCalls.push(url);
    if (!onlineNow) throw new TypeError("Failed to fetch");
    const body = net.has(url) ? net.get(url) : `network:${new URL(url).pathname}`;
    return new Response(body, { status: 200 });
  }

  const handlers = {};
  const self = {
    location: { origin: ORIGIN },
    addEventListener: (type, handler) => {
      handlers[type] = handler;
    },
    skipWaiting: () => Promise.resolve(),
    clients: { claim: () => Promise.resolve() },
  };
  new Function("self", "caches", "fetch", source)(self, caches, fetchFn);

  async function install() {
    const pending = [];
    handlers.install({ waitUntil: (promise) => pending.push(promise) });
    await Promise.all(pending.map((promise) => Promise.resolve(promise).catch(() => {})));
  }

  async function get(pathname) {
    // Let a cache write the last response left in flight land first.
    await new Promise((resolve) => setTimeout(resolve, 0));
    const responded = [];
    const waited = [];
    handlers.fetch({
      request: { url: `${ORIGIN}${pathname}`, method: "GET" },
      respondWith: (promise) => responded.push(Promise.resolve(promise)),
      waitUntil: (promise) => waited.push(Promise.resolve(promise).catch(() => {})),
    });
    const response = responded.length ? await responded[0] : null;
    await Promise.all(waited);
    return response ? response.text() : response;
  }

  return {
    install,
    get,
    setNetwork: (pathname, body) => net.set(`${ORIGIN}${pathname}`, body),
    goOffline: () => {
      onlineNow = false;
    },
    networkCallsTo: (pathname) =>
      networkCalls.filter((url) => url === `${ORIGIN}${pathname}`).length,
  };
}

// A phone that installed on day one: the index.html it fetched then is what
// sits in the shell cache from now on.
async function installedOn(indexBody) {
  const sw = await startSW();
  sw.setNetwork(INDEX, indexBody);
  await sw.install();
  return sw;
}

test("a changed index.html is served from the network, not the cached copy", async () => {
  const sw = await installedOn("<html>install günü</html>");
  sw.setNetwork(INDEX, "<html>yenilenmiş işareti</html>");

  assert.equal(await sw.get(INDEX), "<html>yenilenmiş işareti</html>");
  assert.equal(sw.networkCallsTo(INDEX), 2);
});

test("the directory document is served fresh too", async () => {
  const sw = await startSW();
  sw.setNetwork(SHELL_DIR, "<html>install günü</html>");
  await sw.install();
  sw.setNetwork(SHELL_DIR, "<html>yenilenmiş işareti</html>");

  assert.equal(await sw.get(SHELL_DIR), "<html>yenilenmiş işareti</html>");
});

test("the same request with the network down comes from the cache", async () => {
  const sw = await installedOn("<html>install günü</html>");
  sw.goOffline();

  assert.equal(await sw.get(INDEX), "<html>install günü</html>");
});

test("the refreshed document is in the cache for the next offline open", async () => {
  const sw = await installedOn("<html>install günü</html>");
  sw.setNetwork(INDEX, "<html>yenilenmiş işareti</html>");

  assert.equal(await sw.get(INDEX), "<html>yenilenmiş işareti</html>");

  sw.goOffline();
  assert.equal(await sw.get(INDEX), "<html>yenilenmiş işareti</html>");
});
