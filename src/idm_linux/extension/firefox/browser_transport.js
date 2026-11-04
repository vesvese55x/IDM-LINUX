/* Vendor-independent, frame-bound network transport. Media never falls back to background fetch. */
"use strict";
globalThis.IdmBrowserTransport = (() => {
  const clients = new Map();
  const running = new Map();
  let busy = false;
  const post = (action, body) => callBridge(`/api/browser-transport/${action}`, "POST", body, null);
  function frameMessage(client, message) {
    return new Promise((resolve, reject) => {
      extApi.tabs.sendMessage(client.tab, message, { frameId: client.frame }, (result) => {
        const error = extApi.runtime.lastError;
        if (error || !result) reject(new Error("Kaynak sekmesi/çerçevesi kapandı."));
        else if (!result.ok) reject(new Error(result.error || "Tarayıcı isteği başarısız."));
        else resolve(result);
      });
    });
  }
  async function route(client) {
    if (!client.pin) return "";
    const result = await frameMessage(client, { type: "IDM_BROWSER_ROUTE" });
    if (!/^[a-f0-9]{64}$/.test(result.hash || "")) throw new Error("VPN çıkışı doğrulanamadı.");
    return result.hash;
  }
  async function close(token) {
    const client = clients.get(token);
    clients.delete(token);
    for (const [id, entry] of running) {
      if (entry.token === token) {
        frameMessage(entry.client, { type: "IDM_BROWSER_ABORT", id }).catch(() => {});
        running.delete(id);
      }
    }
    if (client) await post("revoke", { client: token }).catch(() => {});
  }
  async function prepare(tab, frame, referer, pin = true) {
    if (extensionDisabled) throw new Error("IDM yakalaması kapalı.");
    if (!Number.isInteger(tab) || tab < 0) throw new Error("Kaynak tarayıcı sekmesi gerekli.");
    try {
      const frames = await new Promise((resolve) => extApi.webNavigation.getAllFrames({ tabId: tab }, (all) => { void extApi.runtime.lastError; resolve(all || []); }));
      const exact = frames.find((f) => f.url === referer);
      const same = exact || frames.find((f) => { try { return new URL(f.url).origin === new URL(referer).origin; } catch (_) { return false; } });
      if (same) frame = same.frameId;
    } catch (_) {}
    const client = { tab, frame: Number.isInteger(frame) ? frame : 0, pin: Boolean(pin), hash: "" };
    client.hash = await route(client);
    const registered = await post("register", { routeHash: client.hash });
    if (!registered || !registered.ok || !registered.client) throw new Error((registered && registered.error) || "Tarayıcı aktarım köprüsü hazır değil.");
    clients.set(registered.client, client);
    tick();
    return registered.client;
  }
  async function tick() {
    if (busy || !clients.size) return;
    busy = true;
    try {
      if (extensionDisabled) {
        await Promise.all([...clients.keys()].map(close));
        return;
      }
      for (const [token, client] of [...clients]) {
        try {
          const hash = await route(client);
          if (client.hash && hash !== client.hash) throw new Error("VPN/tarayıcı çıkışı değişti.");
          const result = await post("poll", { client: token, routeHash: hash });
          if (!result || !result.ok) throw new Error("Tarayıcı aktarımı kapandı.");
          const active = new Set(result.active || []);
          for (const [id, entry] of running) {
            if (entry.token === token && !active.has(id)) {
              frameMessage(client, { type: "IDM_BROWSER_ABORT", id }).catch(() => {});
              running.delete(id);
            }
          }
          for (const req of result.pending || []) {
            const entry = { token, client, req, started: false };
            running.set(req.id, entry);
          }
        } catch (_) { await close(token); }
      }
      const slots = 4 - [...running.values()].filter((r) => r.started).length;
      for (const [id, entry] of [...running].filter(([, r]) => !r.started).slice(0, Math.max(0, slots))) {
        entry.started = true;
        frameMessage(entry.client, { type: "IDM_BROWSER_FETCH", client: entry.token, request: entry.req, routeHash: entry.client.hash })
          .catch(() => post("done", { client: entry.token, id, ok: false }))
          .finally(() => running.delete(id));
      }
    } finally { busy = false; }
  }
  extApi.runtime.onMessage.addListener((msg, sender, respond) => {
    if (!msg || msg.type !== "IDM_BROWSER_PIPE") return false;
    const client = clients.get(msg.client);
    const entry = running.get(msg.id);
    if (!client || !entry || entry.token !== msg.client || !sender.tab || sender.tab.id !== client.tab || sender.frameId !== client.frame) {
      respond({ ok: false }); return false;
    }
    if (!["meta", "chunk", "done"].includes(msg.action)) { respond({ ok: false }); return false; }
    post(msg.action, { ...msg.payload, client: msg.client, id: msg.id }).then(respond).catch(() => respond({ ok: false }));
    return true;
  });
  extApi.tabs.onRemoved.addListener((tab) => { for (const [token, client] of clients) if (client.tab === tab) close(token); });
  extApi.webNavigation.onCommitted.addListener((event) => {
    for (const [token, client] of clients) if (client.tab === event.tabId && (event.frameId === 0 || client.frame === event.frameId)) close(token);
  });
  setInterval(() => tick().catch(() => {}), 750);
  return { prepare, close };
})();
