import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

// The service worker decides, on its own, where a same-origin GET comes from.
// These tests run the real static/app/sw.js inside a fake ServiceWorkerGlobalScope
// (self, caches, fetch) so the policy is observed rather than grepped: code
// (js/mjs/css) is network-first with the cache only as the offline fallback,
// the shell stays precached, and /v1, /api and /demo never reach the cache.

const SW_PATH = new URL("../../static/app/sw.js", import.meta.url);
const ORIGIN = "https://ocr.example";
const SW_SCRIPT = `${ORIGIN}/app/sw.js`;
// The cache name every phone installed on day one and is still reading from.
const POISONED = "fis-cek-shell-v1";

function urlOf(request) {
  return typeof request === "string" ? request : request.url;
}

async function startSW() {
  const source = await readFile(SW_PATH, "utf8");
  const stores = new Map(); // cache name -> Map(url -> body)
  const net = new Map(); // url -> body
  const networkCalls = [];
  let onlineNow = true;
  let cacheLookups = 0;

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
      cacheLookups += 1;
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

  async function lifecycle(type) {
    const pending = [];
    handlers[type]({ waitUntil: (promise) => pending.push(promise) });
    await Promise.all(pending.map((promise) => Promise.resolve(promise).catch(() => {})));
  }

  async function get(pathname) {
    // Let any cache write an earlier response left in flight land first, so a
    // second request really is facing the stale entry the old code would read.
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
    return response;
  }

  return {
    source,
    install: () => lifecycle("install"),
    activate: () => lifecycle("activate"),
    get,
    setNetwork: (pathname, body) => net.set(`${ORIGIN}${pathname}`, body),
    async seedCache(name, pathname, body) {
      (await cacheOf(name)).put({ url: `${ORIGIN}${pathname}` }, new Response(body));
    },
    goOffline: () => {
      onlineNow = false;
    },
    get cacheNames() {
      return [...stores.keys()];
    },
    get cacheLookups() {
      return cacheLookups;
    },
    get networkCalls() {
      return [...networkCalls];
    },
  };
}

const textOf = async (response) => (response ? response.text() : response);

async function installed() {
  const sw = await startSW();
  await sw.install();
  return sw;
}

// --- app code is network-first ---

test("a module request is answered from the network even when a stale copy is cached", async () => {
  const sw = await installed();
  await sw.get("/app/status.js");
  sw.setNetwork("/app/status.js", "STALE_AFTER_MS = 300000; // yeni");

  const response = await sw.get("/app/status.js");

  assert.equal(await textOf(response), "STALE_AFTER_MS = 300000; // yeni");
  assert.equal(sw.networkCalls.filter((url) => url.endsWith("/app/status.js")).length, 2);
});

test("scripts, modules and stylesheets are all code, and every one is refreshed", async () => {
  const sw = await installed();
  for (const path of ["/app/app.js", "/app/lib.mjs", "/app/style.css"]) {
    await sw.get(path);
    sw.setNetwork(path, "yeni");
    assert.equal(await textOf(await sw.get(path)), "yeni", path);
  }
});

test("the refreshed code lands in the cache, so the next offline load has it", async () => {
  const sw = await installed();
  sw.setNetwork("/app/api.js", "T63 Türkçe 413/422 metni");
  await sw.get("/app/api.js");
  sw.goOffline();

  assert.equal(await textOf(await sw.get("/app/api.js")), "T63 Türkçe 413/422 metni");
});

test("code that is neither cached nor reachable is an error, not a silent hang", async () => {
  const sw = await installed();
  sw.goOffline();

  assert.equal((await sw.get("/app/unknown.js")).type, "error");
});

// --- the offline story survives ---

test("opening /app with no network still draws the shell", async () => {
  const sw = await installed();
  sw.goOffline();

  assert.equal(await textOf(await sw.get("/app/index.html")), "network:/app/index.html");
});

// --- the poisoned cache name ---

test("the shell cache is no longer the v1 that poisoned every install", async () => {
  const sw = await installed();

  assert.ok(!sw.source.includes(POISONED), "sw.js still names the v1 cache");
  assert.ok(sw.cacheNames.length >= 1);
  assert.ok(!sw.cacheNames.includes(POISONED));
});

test("activate throws out the leftover v1 cache", async () => {
  const sw = await installed();
  await sw.seedCache(POISONED, "/app/status.js", "STALE_AFTER_MS = 60000; // bayat");

  await sw.activate();

  assert.ok(!sw.cacheNames.includes(POISONED));
});

// --- live data never touches the cache ---

test("/v1, /api and /demo never hit the cache", async () => {
  const sw = await installed();
  for (const path of ["/v1/jobs", "/api/me/jobs/job-1", "/demo/config.json"]) {
    await sw.seedCache(sw.cacheNames[0], path, "bayat");
  }

  const fetchedBefore = sw.networkCalls.length;
  for (const path of ["/v1/jobs", "/api/me/jobs/job-1", "/demo/config.json"]) {
    assert.equal(await sw.get(path), null, `${path} was answered from the service worker`);
  }
  assert.equal(sw.cacheLookups, 0);
  assert.equal(sw.networkCalls.length, fetchedBefore);
});
