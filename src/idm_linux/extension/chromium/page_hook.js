/* IDM Linux Hybrid Integration — Page-World Deep Stream & Disguised HLS (#EXTM3U / FirePlayer / Vidmoly) Hook */
(function () {
  "use strict";

  if (window.__IDM_LINUX_PAGE_HOOK__) return;
  window.__IDM_LINUX_PAGE_HOOK__ = true;

  window.__idmLinuxCaptureEnabled = () => Boolean(document.documentElement && document.documentElement.dataset.idmLinuxCaptureEnabled === "1");
  window.__idmLinuxCanTakeover = () => window.__idmLinuxCaptureEnabled() && document.documentElement.dataset.idmLinuxBlobReady === "1";
  const workspaceFetch = typeof window.fetch === "function" ? window.fetch.bind(window) : null;
  const reported = new Set();
  const seriesCount = new Map(); // v2.8.7: segment seli bastırma sayaçları

  // v2.9.8: abyss/iamcdn gibi korumalı CDN'lerde çıplak mp4 URL'i IDM'ye 403 olur -> emit etme
  function __idmAbyssGuard(url, opts) {
    try {
      if (!/abyssplayer\.com|abysscdn\.com|embedplayabyss\.top|iamcdn\.net|mediastor/.test(location.host)) return false;
      const u = (url || "").toLowerCase();
      if (u.indexOf("/sora/") >= 0) return false;
      if (/\.(m3u8|mpd)(\?|$)/.test(u) || (opts && opts.isHls)) return false;
      if (/\.(mp4|webm|mkv)(\?|$)/.test(u)) return true;
      return false;
    } catch (_e) { return false; }
  }

  function emitStream(url, opts) {
    if (!window.__idmLinuxCaptureEnabled()) return;
    if (!url || typeof url !== "string") return;
    if (__idmAbyssGuard(url, opts)) return;
    let absUrl = url.trim();
    if (!absUrl || absUrl.startsWith("blob:") || absUrl.startsWith("data:")) return;
    try {
      absUrl = new URL(absUrl, location.href).href;
    } catch (_e) {
      return;
    }
    if (!absUrl.startsWith("http")) return;

    const key = absUrl + "|" + (opts && opts.isHls ? "1" : "0");
    if (reported.has(key)) return;
    reported.add(key);
    if (reported.size > 1500) reported.clear(); // v2.8.7 bellek koruması: Set sınırsız büyüyemez
    // v2.8.7 SEGMENT SELİ BASTIRMA: aynı seriden en fazla 4 parça bildir (D-Smart GO donma fixi)
    if (/\.(dash|m4s|m4v|m4a|cmfv|cmfa|ts|chunk)(\?|#|$)/i.test(absUrl)) {
      const sk = absUrl.replace(/\d+/g, "#");
      const c = (seriesCount.get(sk) || 0) + 1;
      if (seriesCount.size > 200) seriesCount.clear();
      seriesCount.set(sk, c);
      if (c > 4) return;
    }

    try {
      window.postMessage(
        {
          __idmLinuxMediaHook: true,
          url: absUrl,
          isHls: Boolean(opts && opts.isHls),
          manifestText: (opts && opts.manifestText) || "",
          mime: (opts && opts.mime) || "",
          referer: location.href,
          origin: location.origin,
          isFileDownload: /gofile\.io\//i.test(absUrl) && /(wt=|\/download\/)/i.test(absUrl)
        },
        "*"
      );
    } catch (_e) {}
  }

  // v3.2.0: GENEL JSON video-anahtarı kazıyıcı — ok.ru (getVideoInfo), vk.com/vkvideo.ru
  // (al_video.php), rutube vb. API yanıtlarındaki doğrudan oynatma URL'lerini yakalar.
  const VIDEO_KEY_RX = /"(hlsManifestUrl|hlsManifest|dashUrl|dashManifest|manifestUrl|hlsUrl|hls|url1080|url720|url480|url360|url240|url144|mp4-1080|mp4-720|mp4-480|mp4-360|playUrl|play_url|progressive)"\s*:\s*"(http[^"\\]{10,700}?)"/g;

  // v3.12.0 OK.RU ANINDA MP4: ok.ru getVideoInfo JSON + sayfa data-options içindeki
  // vd*.okcdn.ru / mycdn.me progressive MP4 linkleri (uzantısız, type=33 mobile...)
  // genel kazıyıcının ".mp4 uzantısı" şartına takılıyordu -> yalnız HLS görünüyordu ve
  // IDM, HLS hazırlığı için bekliyordu. MP4'ler DOĞRUDAN emittedilirse IDM tıklamayla
  // ANINDA indirir (vk/YouTube hızı).
  const OKRU_URL_RX = /"url"\s*:\s*"([^"]*(?:okcdn\.ru|mycdn\.me)[^"]*)"/gi;

  function emitOkruUrls(text) {
    try {
      if (!text || (text.indexOf("okcdn.ru") < 0 && text.indexOf("mycdn.me") < 0)) return;
      OKRU_URL_RX.lastIndex = 0;
      let om;
      let og = 0;
      while ((om = OKRU_URL_RX.exec(text)) !== null && og < 14) {
        og += 1;
        let u = om[1].replace(/\\/g, "/").replace(/&amp;/g, "&");
        if (u.startsWith("//")) u = "https:" + u;
        if (!/^https?:\/\//i.test(u)) continue;
        const isHls = /\.m3u8(\?|#|$)/i.test(u);
        emitStream(u, { isHls, mime: isHls ? "application/vnd.apple.mpegurl" : "video/mp4" });
      }
    } catch (_e) {}
  }
  window.__idmEmitOkru = emitOkruUrls;

  function emitVideoKeyJson(text) {
    try {
      VIDEO_KEY_RX.lastIndex = 0;
      let mk;
      let guard = 0;
      while ((mk = VIDEO_KEY_RX.exec(text)) !== null && guard < 12) {
        guard += 1;
        let u = mk[2].replace(/\\\//g, "/");
        if (!/^https?:\/\//i.test(u)) continue;
        const keyName = mk[1];
        const isHls = /\.m3u8(\?|#|$)/i.test(u) || /manifest|playlist/i.test(u) || /hls/i.test(keyName);
        if (!isHls && !/\.(mp4|mkv|webm|mov|m4v)(\?|#|$)/i.test(u)) continue;
        emitStream(u, { isHls, mime: isHls ? "application/vnd.apple.mpegurl" : "video/mp4" });
      }
    } catch (_e) {}
    // v3.12.0: ok.ru progressive MP4 linkleri (okcdn.ru / mycdn.me, uzantısız) eklenir
    emitOkruUrls(text);
  }

  function inspectTextPayload(reqUrl, text, contentType) {
    // v2.9.5: abyss info JSON'unu (şifreli media) yakala -> daemon çözer
    try {
      if (text && text.length > 40 && text.length < 400000 && text.charCodeAt(0) === 123 &&
          text.indexOf('"media"') >= 0 && (text.indexOf('"md5_id"') >= 0 || text.indexOf('"md5Id"') >= 0)) {
        window.postMessage({ __idmLinuxAbyssMeta: true, payload: text }, "*");
      }
    } catch (_e) {}
    if (!text || typeof text !== "string") return;
    const trimmed = text.trimStart();

    // 1) Uzantısı .txt, .json, .png veya uzantısız olsa bile gerçek #EXTM3U HLS manifesti!
    if (trimmed.startsWith("#EXTM3U") || (trimmed.includes("#EXTINF:") && trimmed.includes("#EXT"))) {
      emitStream(reqUrl, {
        isHls: true,
        manifestText: trimmed.length <= 524288 ? trimmed : "",
        mime: "application/vnd.apple.mpegurl"
      });
      return;
    }

    // v2.8.9: DASH MPD manifesti — oynatıcının KENDİ çektiği gerçek manifest (geçerli sid/token ile!)
    if (trimmed.startsWith("<?xml") || trimmed.includes("<MPD")) {
      if (/\.mpd(\?|$)/i.test(reqUrl) || /\.smil(\/|\?|$)/i.test(reqUrl) || (contentType || "").includes("dash")) {
        emitStream(reqUrl, {
          isHls: false,
          mime: contentType || "application/dash+xml",
          manifestText: trimmed.length <= 524288 ? trimmed : ""
        });
      }
      return;
    }

    // 2) FirePlayer / Moly / HDPlayer / JWPlayer JSON API yanıtları (videoSource / securedLink / file)
    if (
      (trimmed.startsWith("{") || trimmed.startsWith("[")) &&
      trimmed.length < 200000 &&
      (trimmed.includes("videoSource") ||
        trimmed.includes("securedLink") ||
        trimmed.includes(".m3u8") ||
        trimmed.includes("master.txt"))
    ) {
      try {
        const obj = JSON.parse(trimmed);
        const candidates = [
          obj && obj.videoSource,
          obj && obj.securedLink,
          obj && obj.hls,
          obj && obj.file,
          obj && obj.source
        ];
        for (const c of candidates) {
          if (typeof c === "string" && c.startsWith("http")) {
            const looksHls = /\.m3u8(\?|$)/i.test(c) || /\/(hls|m3u8|manifests?|master|playlist)/i.test(c) || /\.txt(\?|$)/i.test(c);
            emitStream(c, { isHls: looksHls, mime: contentType || "" });
          }
        }
      } catch (_e) {}
    }

    // v3.2.0: ok.ru / vk.ru / vkvideo API JSON'ları — video-anahtarları buradan çıkar
    if ((trimmed.startsWith("{") || trimmed.startsWith("[")) && trimmed.length < 400000) {
      emitVideoKeyJson(trimmed, contentType);
    }

    // v3.11.0: GOFILE ANINDA DOSYA YAKALAYICI — api.gofile.io/contents yanıtı sayfa
    // açılır açılmaz ele geçirilir; her dosyanın GERÇEK store linki + adı + boyutu bara
    // (onay penceresi beklemeden) düşer. Kullanıcı şikâyeti "gofile'de algılama aşırı
    // geç başlıyordu" — çünkü eski akışta link yalnız Download düğmesine basılınca görülüyordu.
    if (trimmed.startsWith("{") && /gofile\.io/i.test(reqUrl || "") && trimmed.length < 400000) {
      try {
        const go = JSON.parse(trimmed);
        const dumpGofile = (node, depth) => {
          if (!node || typeof node !== "object" || depth > 4) return;
          if (Array.isArray(node)) {
            for (const n of node) dumpGofile(n, depth + 1);
            return;
          }
          if (node.link && node.name && (node.type === "file" || /\.[a-z0-9]{2,5}$/i.test(String(node.name)))) {
            try {
              window.postMessage(
                {
                  __idmLinuxMediaHook: true,
                  url: String(node.link),
                  isHls: false,
                  mime: "application/octet-stream",
                  fileName: String(node.name),
                  fileSize: Number(node.size) || 0,
                  isFileDownload: true,
                  referer: location.href,
                  origin: location.origin
                },
                "*"
              );
            } catch (_e) {}
          }
          if (node.children && typeof node.children === "object") {
            for (const c of Object.values(node.children)) dumpGofile(c, depth + 1);
          }
        };
        dumpGofile(go && go.data, 0);
      } catch (_e) {}
    }
  }

  // 1. window.fetch kancası
  if (typeof window.fetch === "function") {
    const origFetch = window.fetch;
    window.fetch = function (...args) {
      if (!window.__idmLinuxCaptureEnabled()) return origFetch.apply(this, args);
      const p = origFetch.apply(this, args);
      try {
        p.then((resp) => {
          try {
            if (!window.__idmLinuxCaptureEnabled() || !resp || !resp.ok) return;
            const rUrl = resp.url || (typeof args[0] === "string" ? args[0] : (args[0] && args[0].url)) || "";
            const ct = (resp.headers && resp.headers.get("content-type")) || "";
            const cl = parseInt((resp.headers && resp.headers.get("content-length")) || "0", 10) || 0;
            if (cl > 2 * 1024 * 1024) return;
            if (/^(video|audio|image|font)\//i.test(ct) && !/mpegurl/i.test(ct)) return;
            if (/\.(ts|m4s|mp4|webm|mkv|woff2?)(\?|$)/i.test(rUrl)) return;

            resp.clone().text().then((txt) => inspectTextPayload(rUrl, txt, ct)).catch(() => {});
          } catch (_e) {}
        }).catch(() => {});
      } catch (_e) {}
      return p;
    };
  }

  // 2. XMLHttpRequest kancası (hls.js, jwplayer, video.js, FirePlayer XHR kullanır!)
  if (typeof XMLHttpRequest !== "undefined") {
    const origOpen = XMLHttpRequest.prototype.open;
    const origSend = XMLHttpRequest.prototype.send;

    XMLHttpRequest.prototype.open = function (method, url, ...rest) {
      try {
        this.__idmUrl = typeof url === "string" ? url : String(url || "");
      } catch (_e) {}
      return origOpen.call(this, method, url, ...rest);
    };

    XMLHttpRequest.prototype.send = function (...args) {
      if (!window.__idmLinuxCaptureEnabled()) return origSend.apply(this, args);
      try {
        this.addEventListener("load", function () {
          try {
            if (!window.__idmLinuxCaptureEnabled() || this.status < 200 || this.status >= 400) return;
            const rUrl = this.responseURL || this.__idmUrl || "";
            if (/\.(ts|m4s|mp4|webm|mkv|woff2?)(\?|$)/i.test(rUrl)) return;
            const rType = this.responseType || "";
            if (rType === "" || rType === "text") {
              const txt = this.responseText;
              if (txt && txt.length <= 1048576) {
                inspectTextPayload(rUrl, txt, this.getResponseHeader("content-type") || "");
              }
            } else if (rType === "json" && this.response && typeof this.response === "object") {
              inspectTextPayload(rUrl, JSON.stringify(this.response), "application/json");
            }
          } catch (_e) {}
        });
      } catch (_e) {}
      return origSend.apply(this, args);
    };
  }

  // Normal file Blobs only. MediaSource/DRM streams are not file blobs.
  const blobStore = new Map();
  const pendingBlobCallbacks = new Map();
  const nativeCreateObjectURL = URL.createObjectURL.bind(URL);
  const nativeRevokeObjectURL = URL.revokeObjectURL.bind(URL);
  let trackedBlobBytes = 0;
  window.addEventListener("idm-linux-capture-state", () => {
    reported.clear(); seriesCount.clear();
    if (!window.__idmLinuxCaptureEnabled()) { blobStore.clear(); trackedBlobBytes = 0; }
  });
  function forgetBlob(url) {
    const value = blobStore.get(url);
    if (value) { trackedBlobBytes -= value.size; blobStore.delete(url); }
  }
  URL.createObjectURL = function (obj) {
    const url = nativeCreateObjectURL(obj);
    if (window.__idmLinuxCaptureEnabled() && typeof Blob !== "undefined" && obj instanceof Blob && obj.size > 0 && obj.size <= 1024 ** 3) {
      blobStore.set(url, obj); trackedBlobBytes += obj.size;
      while (blobStore.size > 8 || trackedBlobBytes > 1024 ** 3) forgetBlob(blobStore.keys().next().value);
    }
    return url;
  };
  URL.revokeObjectURL = function (url) { forgetBlob(url); return nativeRevokeObjectURL(url); };
  window.addEventListener("message", (ev) => {
    const d = ev && ev.data;
    if (ev.source !== window || !d || !d.__idmLinuxBlobResult) return;
    const cb = pendingBlobCallbacks.get(d.reqId);
    if (cb) { pendingBlobCallbacks.delete(d.reqId); cb(d); }
  });
  function blobRpc(action, payload) {
    return new Promise((resolve, reject) => {
      const reqId = `blob_${Date.now()}_${Math.random().toString(36).slice(2)}`;
      const timer = setTimeout(() => { pendingBlobCallbacks.delete(reqId); reject(new Error("Blob bridge timeout")); }, 45000);
      pendingBlobCallbacks.set(reqId, (reply) => { clearTimeout(timer); resolve(reply); });
      window.postMessage(Object.assign({}, payload, { __idmLinuxBlobRequest: true, action, reqId }), "*");
    });
  }
  function encodeBlobSlice(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
      reader.onerror = () => reject(new Error("Blob read failed"));
      reader.readAsDataURL(blob);
    });
  }
  function tryInterceptBlobAnchor(anchor, event) {
    if (!window.__idmLinuxCanTakeover() || !anchor || anchor.__idmBypassBlob || (event && event.altKey)) return false;
    const href = anchor.getAttribute("href") || anchor.href || "";
    const filename = anchor.getAttribute("download");
    const blob = blobStore.get(href);
    // No safe local Blob reference? Do not cancel the browser's original click.
    if (!href.startsWith("blob:") || filename === null || !blob) return false;
    if (event) { event.preventDefault(); event.stopImmediatePropagation(); }
    let fallbackDone = false;
    const fallback = () => {
      if (fallbackDone) return;
      fallbackDone = true;
      // React often revokes the original URL immediately after a.click().
      const fresh = nativeCreateObjectURL(blob);
      const copy = document.createElement("a");
      copy.__idmBypassBlob = true; copy.href = fresh; copy.download = filename || "download.bin"; copy.style.display = "none";
      (document.body || document.documentElement).appendChild(copy); copy.click(); copy.remove();
      setTimeout(() => nativeRevokeObjectURL(fresh), 60000);
    };
    (async () => {
      let transferId = "";
      try {
        const start = await blobRpc("begin", { filename: filename || "download.bin", mimeType: blob.type, size: blob.size });
        if (!start.ok || !start.transferId) { fallback(); return; }
        transferId = start.transferId;
        for (let offset = 0; offset < blob.size; offset += 384 * 1024) {
          if (!window.__idmLinuxCaptureEnabled()) throw new Error("Capture disabled");
          const part = blob.slice(offset, Math.min(blob.size, offset + 384 * 1024));
          const dataBase64 = await encodeBlobSlice(part);
          const reply = await blobRpc("chunk", { transferId, offset, dataBase64 });
          if (!reply.ok || reply.received !== offset + part.size) throw new Error("Blob chunk rejected");
        }
        const result = await blobRpc("finish", { transferId });
        if (!result.ok || !result.takeover) fallback();
      } catch (_e) {
        if (transferId) blobRpc("cancel", { transferId }).catch(() => {});
        fallback();
      } finally { forgetBlob(href); }
    })();
    return true;
  }
  // Workspace row links are authenticated HTTP downloads, unlike the viewer's
  // Blob anchors. Fetch in the authenticated page, then use the existing bounded
  // runtime-message upload; page -> localhost fetch is blocked by site CSP/PNA.
  function tryInterceptArenaWorkspaceAnchor(anchor, event) {
    if (!workspaceFetch || !window.__idmLinuxCanTakeover() || !anchor || anchor.__idmBypassWorkspace || (event && event.altKey)) return false;
    let url;
    try { url = new URL(anchor.getAttribute("href") || anchor.href || "", location.href); } catch (_e) { return false; }
    const justBeamIt = /(^|\.)justbeamit\.com$/.test(location.hostname) && /^\/[a-z0-9]{3,12}\/?$/i.test(new URL(location.href).pathname) && /(^|\.)justbeamit\.com$/.test(url.hostname) && url.pathname === "/download" && url.searchParams.get("token") === new URL(location.href).pathname.replace(/\//g, "");
    const arena = /(^|\.)arena\.ai$/.test(location.hostname) && url.origin === location.origin && /^\/api\/chat\/workspace\/cas\/user\/[^/]+$/.test(url.pathname);
    if (!arena && !justBeamIt) return false;
    if (event) { event.preventDefault(); event.stopImmediatePropagation(); }
    const fallback = () => {
      const copy = document.createElement("a"); copy.__idmBypassWorkspace = true;
      copy.href = url.href; copy.download = anchor.getAttribute("download") || "";
      (document.body || document.documentElement).appendChild(copy); copy.click(); copy.remove();
    };
    (async () => {
      let transferId = "", reader = null, response = null;
      try {
        // Reserve bounded disk staging BEFORE consuming a one-use transfer URL.
        if (justBeamIt) {
          const start = await blobRpc("begin", { filename: anchor.getAttribute("download") || "beam-download.bin", size: null, streaming: true, mimeType: "application/octet-stream" });
          if (!start.ok || !start.transferId) throw new Error("Transfer staging unavailable");
          transferId = start.transferId;
        }
        response = await workspaceFetch(url.href, { credentials: "include", redirect: "follow" });
        const headerSize = Number(response.headers.get("content-length"));
        const size = justBeamIt && headerSize === 0 ? null : headerSize;
        // Unknown/oversize bodies stay browser-owned; never buffer the full file.
        if (!response.ok || !response.body || (size !== null && (!Number.isSafeInteger(size) || size <= 0 || size > 1024 ** 3))) throw new Error("Unsupported workspace response");
        const disposition = response.headers.get("content-disposition") || "";
        const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
        const plain = disposition.match(/filename="([^"]+)"|filename=([^;]+)/i);
        let filename = anchor.getAttribute("download") || "";
        if (!filename && encoded) { try { filename = decodeURIComponent(encoded[1].trim()); } catch (_e) {} }
        filename = filename || (plain && (plain[1] || plain[2]).trim()) || "workspace-download.bin";
        if (!justBeamIt) {
          const start = await blobRpc("begin", { filename, size, mimeType: response.headers.get("content-type") || "application/octet-stream" });
          if (!start.ok || !start.transferId) throw new Error("Workspace transfer rejected");
          transferId = start.transferId;
        }
        reader = response.body.getReader(); let offset = 0;
        for (;;) {
          if (!window.__idmLinuxCaptureEnabled()) throw new Error("Capture disabled");
          const { done, value } = await reader.read(); if (done) break;
          if (offset + value.length > (size === null ? 1024 ** 3 : size)) throw new Error("Workspace size exceeded");
          for (let i = 0; i < value.length; i += 384 * 1024) {
            if (!window.__idmLinuxCaptureEnabled()) throw new Error("Capture disabled");
            const part = new Blob([value.subarray(i, i + 384 * 1024)]);
            const reply = await blobRpc("chunk", { transferId, offset, dataBase64: await encodeBlobSlice(part) });
            offset += part.size;
            if (!reply.ok || reply.received !== offset) throw new Error("Workspace chunk rejected");
          }
        }
        if (!offset || (size !== null && offset !== size)) throw new Error("Workspace response truncated");
        const finish = await blobRpc("finish", { transferId, size: offset });
        if (!finish.ok || !finish.takeover) throw new Error("Workspace handoff rejected");
        if (justBeamIt && anchor.__idmButton) anchor.__idmButton.textContent = "IDM: aktarım hazır";
      } catch (_e) {
        if (reader) { try { await reader.cancel(); } catch (_ignore) {} }
        else if (response && response.body && response.body.cancel) { try { await response.body.cancel(); } catch (_ignore) {} }
        if (transferId) { try { await blobRpc("cancel", { transferId }); } catch (_ignore) {} }
        if (justBeamIt) {
          // Never replay a consumed token or publish partial bytes as a complete file.
          if (anchor.__idmButton) anchor.__idmButton.textContent = "IDM: aktarım başarısız; yeni bağlantı gerekli";
        } else fallback();
      }
    })();
    return true;
  }
  window.addEventListener("click", (ev) => {
    if (!ev.isTrusted || ev.defaultPrevented || ev.button !== 0) return;
    const beamButton = /(^|\.)justbeamit\.com$/.test(location.hostname) && ev.target && ev.target.closest ? ev.target.closest("#dl-button") : null;
    if (beamButton && window.__idmLinuxCanTakeover() && !ev.altKey) {
      if (beamButton.__idmTransferActive) { ev.preventDefault(); ev.stopImmediatePropagation(); return; }
      const root = window.SERVER_ROOT || "https://eu.justbeamit.com:8443";
      const a = document.createElement("a");
      a.href = root + "/download?token=" + encodeURIComponent(new URL(location.href).pathname.replace(/\//g, ""));
      const label = document.getElementById("dl-filename-text");
      a.download = (label && label.textContent) || "beam-download.bin"; a.__idmButton = beamButton;
      if (tryInterceptArenaWorkspaceAnchor(a, ev)) { beamButton.__idmTransferActive = true; beamButton.textContent = "IDM: dosya alınıyor, göndereni açık tutun..."; return; }
    }
    const a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
    if (a && !tryInterceptArenaWorkspaceAnchor(a, ev)) tryInterceptBlobAnchor(a, ev);
  }, true);
  const nativeAnchorClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function (...args) {
    if (!tryInterceptArenaWorkspaceAnchor(this, null) && !tryInterceptBlobAnchor(this, null)) return nativeAnchorClick.apply(this, args);
  };

  // v3.14.3 FIX: emitStream, kazıyıcı modüllerin okuyabilmesi için burada (tanım kapsamından) global'e açılır
  window.__idmEmitStream = emitStream;
})();

// v2.9.0: programatik indirme tetikleyicilerini YUT (window.open / location.href)
// gofile & arena.ai gibi sitelerde tarayıcının kendi indirmesi/auth diyaloğu ASLA görünmez
(function () {
  const NAV_TAKEOVER = /gofile\.io\/(download\/|contents\/)|arena\.ai\/(api\/|chat\/)/i;
  try {
    const origOpen = window.open;
    window.open = function (u, ...rest) {
      try {
        if (window.__idmLinuxCanTakeover() && typeof u === "string" && NAV_TAKEOVER.test(u)) {
          window.postMessage({ __idmLinuxNavTakeover: true, url: u }, "*");
          return null;
        }
      } catch (_e) {}
      return origOpen.apply(this, [u, ...rest]);
    };
  } catch (_e) {}
  try {
    const desc = Object.getOwnPropertyDescriptor(Location.prototype, "href");
    if (desc && desc.set) {
      Object.defineProperty(Location.prototype, "href", {
        get: desc.get,
        set(v) {
          try {
            if (window.__idmLinuxCanTakeover() && typeof v === "string" && NAV_TAKEOVER.test(v)) {
              window.postMessage({ __idmLinuxNavTakeover: true, url: v }, "*");
              return;
            }
          } catch (_e) {}
          return desc.set.call(this, v);
        },
        configurable: true,
        enumerable: desc.enumerable,
      });
    }
  } catch (_e) {}
  // v3.13.0: location.assign() / location.replace() da yakalanır — gofile indirme
  // düğmesi href setter'ı DEĞİL assign()'ı kullanınca yakalama kaçıyordu.
  try {
    const origAssign = Location.prototype.assign;
    Location.prototype.assign = function (u, ...rest) {
      try {
        if (window.__idmLinuxCanTakeover() && typeof u === "string" && NAV_TAKEOVER.test(u)) {
          window.postMessage({ __idmLinuxNavTakeover: true, url: u }, "*");
          return undefined;
        }
      } catch (_e) {}
      return origAssign.call(this, u, ...rest);
    };
    const origReplace = Location.prototype.replace;
    Location.prototype.replace = function (u, ...rest) {
      try {
        if (window.__idmLinuxCanTakeover() && typeof u === "string" && NAV_TAKEOVER.test(u)) {
          window.postMessage({ __idmLinuxNavTakeover: true, url: u }, "*");
          return undefined;
        }
      } catch (_e) {}
      return origReplace.call(this, u, ...rest);
    };
  } catch (_e) {}
  // v3.13.0: gofile indirme ANCHOR'ları (a etiketi) yakalanır ve tarayıcıya
  // HİÇ gitmez — tıklama anında daemon'a gider (IDM otomatik devralır).
  try {
    const ANCHOR_SEL = "a[" + "href" + "]";
    const GO_RX = /gofile\.io\/(download\/|contents\/)|arena\.ai\/(api\/|chat\/)/i;
    const grabHref = (el) => {
      try {
        const h = el.getAttribute("href") || "";
        if (!h) return "";
        return new URL(h, location.href).href;
      } catch (_e) { return ""; }
    };
    window.addEventListener("click", (ev) => {
      try {
        if (!window.__idmLinuxCanTakeover() || !ev.isTrusted || ev.button !== 0 || ev.altKey) return;
        let a = ev.target && ev.target.closest ? ev.target.closest(ANCHOR_SEL) : null;
        if (!a && typeof ev.composedPath === "function") {
          for (const el of ev.composedPath()) {
            if (el && el.tagName === "A" && el.getAttribute) { a = el; break; }
          }
        }
        if (!a) return;
        const abs = grabHref(a);
        if (!abs || !GO_RX.test(abs)) return;
        ev.preventDefault();
        ev.stopImmediatePropagation();
        window.postMessage({ __idmLinuxNavTakeover: true, url: abs }, "*");
      } catch (_e) {}
    }, true);
  } catch (_e) {}
})();

// v3.14.3 FIX: yanlış IIFE'deki 'window.__idmEmitStream = emitStream;' ataması silindi —
// emitStream o kapsamda tanımsızdı; her frame'de ReferenceError üretiyor ve bilibili/ok.ru/vk
// kazıyıcılarını (window.__idmEmitStream'i okuyanlar) sessizce devre dışı bırakıyordu. Doğru atama ilk IIFE'nin sonuna eklendi.

// v2.9.4: bilibili __playinfo__ kazıyıcı — YENİDEN DENYENELİ (player geç açılabilir)
(function () {
  try {
    if (!/(^|\.)bilibili\.com$|(^|\.)b23\.tv$/.test(location.hostname)) return;
    let tries = 0, done = false;
    const emit = window.__idmEmitStream;
    if (!emit) return;
    const scrape = (txt) => {
      const i = txt.indexOf("__playinfo__");
      if (i < 0) return null;
      const j = txt.indexOf("{", i);
      if (j < 0) return null;
      let depth = 0, end = -1;
      for (let k = j; k < txt.length && k < j + 600000; k++) {
        const c = txt[k];
        if (c === "{") depth++;
        else if (c === "}") { depth--; if (depth === 0) { end = k + 1; break; } }
      }
      if (end < 0) return null;
      try { return JSON.parse(txt.slice(j, end)); } catch (_e) { return null; }
    };
    const tick = () => {
      if (!window.__idmLinuxCaptureEnabled() || done || ++tries > 40) return;
      let obj = window.__playinfo__ || null;
      if (!obj && document.documentElement) obj = scrape(document.documentElement.innerHTML || "");
      const dash = obj && obj.data && obj.data.dash;
      if (dash) {
        const vids = (dash.video || []).slice(0, 6);
        const auds = (dash.audio || []).slice(0, 2);
        if (vids.length) {
          done = true;
          vids.forEach((v) => emit(v.baseUrl || v.base_url, { mime: v.mimeType || "video/mp4" }));
          auds.forEach((a) => emit(a.baseUrl || a.base_url, { mime: a.mimeType || "audio/mp4" }));
        }
      }
    };
    tick();
    let iv = null;
    const startPolling = () => {
      if (iv) clearInterval(iv);
      done = false; tries = 0; tick();
      iv = setInterval(() => { tick(); if (done || tries > 40) { clearInterval(iv); iv = null; } }, 1500);
    };
    startPolling();
    window.addEventListener("idm-linux-capture-state", () => { if (window.__idmLinuxCaptureEnabled()) startPolling(); });
    window.addEventListener("popstate", startPolling);
  } catch (_e) {}
})();

// v2.9.4: abyss.to / abyssplayer iframe slug yakalama
(function () {
  try {
    if (!/abyssplayer\.com|abysscdn\.com|embedplayabyss\.top|abyss\.to/.test(location.host)) return;
    let slug = "";
    const mq = location.search.match(/[?&]v=([A-Za-z0-9_-]{4,})/);
    if (mq) slug = mq[1];
    if (!slug) {
      const mp = location.pathname.match(/^\/([A-Za-z0-9_-]{4,})\/?$/);
      if (mp) slug = mp[1];
    }
    if (slug) {
      window.postMessage({ __idmLinuxAbyss: true, slug: slug }, "*");
      const re = setInterval(() => window.postMessage({ __idmLinuxAbyss: true, slug: slug }, "*"), 5000);
      setTimeout(() => clearInterval(re), 60000);
    }
  } catch (_e) {}
})();

// v2.9.4: sayfa içi <track> altyazılarını bara taşı
(function () {
  try {
    const scan = () => {
      if (!window.__idmLinuxCaptureEnabled()) return;
      document.querySelectorAll("track[src]").forEach((tr) => {
        const kind = (tr.kind || "").toLowerCase();
        if (kind && kind !== "subtitles" && kind !== "captions") return;
        try {
          const abs = new URL(tr.getAttribute("src"), location.href).href;
          window.postMessage({ __idmLinuxSubtitle: true, url: abs, label: tr.label || tr.srclang || "altyazı" }, "*");
        } catch (_e) {}
      });
    };
    setTimeout(scan, 1500);

    // v3.2.1: ALTYAZI AĞ SNIFFER'I — JW/videojs/flowplayer gibi oyuncular .vtt/.srt dosyasını
    // çalışma zamanında fetch/XHR ile çeker; DOM'da <track> olmasa bile altyazı bar'a düşer.
    // v3.5.0: film sitelerinin çoğu altyazıyı /api/subtitles, /caption?lang=.., .ttml/.xml
    // gibi YOLLARLA çeker — desenler genişletildi (YouTube timedtext dahil).
    // v3.7.1: İSTEK URL'i yetmez — oyuncular altyazı adresini JSON konfigürasyonunda
    // taşır (rapidvid/fullhdfilmizlesene). Artık fetch/XHR YANIT GÖVDELERİ de taranır
    // (2 MB üstü ve text/json/xml dışı yanıtlar atlanır — performans korunur).
    const subExtRe = /\.(vtt|srt|ass|ssa|ttml|dfxp|smi|sami|sbv|sub)(\?|#|$)/i;
    const subNameRe = /(subtitle|subtitles|caption|captions|altyazi|altyaz|timedtext|\/subs\/)/i;
    const subSeen = new Set();
    // v3.9.0: DİL ADI TABLOSU — oyuncu konfigürasyonunda URL çevresindeki bağlamdan
    // ('label:"Türkçe Altyazı"', srclang:"tr", 'lang:"en"' vb.) dil tespiti.
    // Kullanıcı kararı: bar altyazının dilini YAZSIN. 'lang:<kod>' etiketi daemon'da
    // yerel dile çevrilir (sub_lang_name).
    const PH_LANG_WORDS = [
      ["türkçe", "tr"], ["turkce", "tr"], ["turkish", "tr"],
      ["ingilizce", "en"], ["english", "en"],
      ["almanca", "de"], ["deutsch", "de"], ["german", "de"],
      ["fransızca", "fr"], ["fransizca", "fr"], ["français", "fr"], ["french", "fr"],
      ["ispanyolca", "es"], ["español", "es"], ["spanish", "es"],
      ["italyanca", "it"], ["italiano", "it"], ["italian", "it"],
      ["rusça", "ru"], ["rusca", "ru"], ["russian", "ru"],
      ["arapça", "ar"], ["arapca", "ar"], ["arabic", "ar"],
      ["japonca", "ja"], ["japanese", "ja"],
      ["korece", "ko"], ["korean", "ko"],
      ["çince", "zh"], ["cincesi", "zh"], ["chinese", "zh"],
      ["farsça", "fa"], ["farsca", "fa"], ["persian", "fa"],
      ["azerice", "az"], ["azeri", "az"],
      ["yunanca", "el"], ["greek", "el"],
      ["portekizce", "pt"], ["português", "pt"], ["portuguese", "pt"],
      ["hintce", "hi"], ["hintçe", "hi"], ["hindi", "hi"],
    ];
    const detectSubLabelFromContext = (ctx) => {
      try {
        if (!ctx) return "";
        const lbl = ctx.match(/"label"\s*:\s*"([^"]{2,48})"/) || ctx.match(/'label'\s*:\s*'([^']{2,48})'/);
        if (lbl && lbl[1] && !/^(default|forced|none)$/i.test(lbl[1].trim())) {
          const t = lbl[1].trim();
          const low = t.toLowerCase();
          for (const [w, c] of PH_LANG_WORDS) {
            if (low.includes(w)) return "lang:" + c;
          }
          return t;
        }
        const sc = ctx.match(/(?:srclang|lang|language|sub_lang|sublang)"?\s*[:=]\s*["']?([a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?)["']?/i);
        if (sc && /^[a-z]{2,3}$/i.test(sc[1])) return "lang:" + sc[1].toLowerCase();
        const lowAll = ctx.toLowerCase();
        for (const [w, c] of PH_LANG_WORDS) {
          if (lowAll.includes(w)) return "lang:" + c;
        }
        return "";
      } catch (_e) { return ""; }
    };
    const emitSub = (u, hintLabel, declaredCaption = false, baseUrl = location.href) => {
      try {
        if (!window.__idmLinuxCaptureEnabled() || !u || typeof u !== "string" || u.length > 8192) return;
        if (!(declaredCaption || subExtRe.test(u) || subNameRe.test(u))) return;
        if (u.startsWith("blob:") || u.startsWith("data:")) return;
        let abs = u;
        try { abs = new URL(u, baseUrl).href; if (!/^https?:\/\//i.test(abs)) return; } catch (_e) { return; }
        if (subSeen.has(abs)) return;
        subSeen.add(abs);
        if (subSeen.size > 600) subSeen.delete(subSeen.values().next().value);
        window.postMessage({ __idmLinuxSubtitle: true, url: abs, label: hintLabel || "altyazı" }, "*");
      } catch (_e) {}
    };
    const scanSubUrls = (text, baseUrl = location.href) => {
      try {
        if (!window.__idmLinuxCaptureEnabled() || !text || typeof text !== "string" || text.length > 2000000) return;
        // Player JSON often stores relative, escaped, or extensionless caption
        // URLs. Parse data only; never evaluate page scripts/configuration.
        const captionKey = key => /^(subtitles?|captions?|subs|captionTracks|subtitleTracks|textTracks)$/i.test(key);
        const walk = (value, parentKey = "", depth = 0, budget = {left: 4000}, inherited = false, inheritedLabel = "") => {
          if (value == null || depth > 12 || --budget.left < 0) return;
          const declaredParent = inherited || captionKey(parentKey);
          if (typeof value === "string") {
            if (value.length > 2000000) return;
            if (/^[\s]*[\[{]/.test(value)) {
              try { walk(JSON.parse(value), parentKey, depth+1, budget, declaredParent, inheritedLabel); } catch (_json) {}
            } else if (declaredParent && (/^(?:https?:|\/\/|\/|\.{1,2}\/)|[/?]/i.test(value) || subExtRe.test(value))) emitSub(value, inheritedLabel, true, baseUrl);
            return;
          }
          if (typeof value !== "object") return;
          if (Array.isArray(value)) { for (const item of value.slice(0,300)) walk(item,parentKey,depth+1,budget,declaredParent,inheritedLabel); return; }
          const kind = String(value.kind || value.type || "").toLowerCase();
          if (/^(metadata|thumbnails?|chapters)$/.test(kind)) return;
          const declared = declaredParent || /^(subtitles?|captions?)$/.test(kind);
          const rawLabel = value.label || value.title || value.name;
          const label = (typeof rawLabel === "string" ? rawLabel : "") || (value.srclang || value.lang || value.language || value.languageCode ? "lang:" + (value.srclang || value.lang || value.language || value.languageCode) : inheritedLabel);
          for (const key of ["file","src","url","baseUrl","base_url","vtt_url","srt_url"]) {
            if (typeof value[key] === "string" && (declared || subExtRe.test(value[key]))) emitSub(value[key],String(label).slice(0,80),declared,baseUrl);
          }
          for (const [key,child] of Object.entries(value).slice(0,300)) {
            if (["file","src","url","baseUrl","base_url","vtt_url","srt_url","label","title","name","lang","language","kind","type"].includes(key)) continue;
            const langLabel = declared && /^[a-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?$/.test(key) ? "lang:"+key : label;
            if (child && (typeof child === "object" || (typeof child === "string" && (declared || /metadata|config|player|params/i.test(key))))) walk(child,key,depth+1,budget,declared,langLabel);
          }
        };
        try { walk(JSON.parse(text)); } catch (_json) {}
        text = text.replace(/\\\//g, "/").replace(/\\u0026/gi, "&");
        const relative = /["']([^"'\s\\<>]{1,1800}\.(?:vtt|srt|ass|ssa|ttml|dfxp|smi|sami|sbv|sub)(?:\?[^"'\s\\<>]*)?)["']/gi;
        let rm; let relativeCount = 0;
        while ((rm = relative.exec(text)) && relativeCount++ < 24) {
          const context = text.slice(Math.max(0,rm.index-160),relative.lastIndex+160);
          emitSub(rm[1],detectSubLabelFromContext(context),false,baseUrl);
        }
        const re = /https?:\/\/[^"'\s\\<>]{8,300}?\.(vtt|srt|ass|ssa|ttml|dfxp|smi|sami|sbv|sub)(\?[^"'\s\\<>]*)?/gi;
        let m; let guard = 0;
        while ((m = re.exec(text)) !== null && guard < 12) {
          guard += 1;
          // v3.9.0: eşleşmenin ÇEVRESİNDEKİ oyuncu konfigürasyonundan dil çıkarılır
          const ctx = text.slice(Math.max(0, m.index - 160), m.index + m[0].length + 160);
          emitSub(m[0], detectSubLabelFromContext(ctx));
        }
      } catch (_e) {}
    };
    const captureCaptionText = (text, sourceUrl) => {
      if (!window.__idmLinuxCaptureEnabled() || typeof text !== "string" || text.length > 2000000) return;
      let vtt = text.trimStart().replace(/^\uFEFF/, "");
      if (vtt.startsWith("{")) {
        try {
          const events = JSON.parse(vtt).events;
          if (!Array.isArray(events)) return;
          const stamp = ms => { ms=Math.round(ms); return `${String(Math.floor(ms/3600000)).padStart(2,"0")}:${String(Math.floor(ms/60000)%60).padStart(2,"0")}:${String(Math.floor(ms/1000)%60).padStart(2,"0")}.${String(ms%1000).padStart(3,"0")}`; };
          const cues=[];
          for (const ev of events.slice(0,30000)) {
            const body=(Array.isArray(ev.segs)?ev.segs:[]).map(seg=>typeof seg.utf8 === "string"?seg.utf8:"").join("").trim();
            if (Number.isFinite(ev.tStartMs) && ev.tStartMs>=0 && Number.isFinite(ev.dDurationMs) && ev.dDurationMs>0 && body) cues.push(`${stamp(ev.tStartMs)} --> ${stamp(ev.tStartMs+ev.dDurationMs)}\n${body}`);
          }
          if (!cues.length) return;
          vtt="WEBVTT\n\n"+cues.join("\n\n")+"\n";
        } catch (_json) { return; }
      }
      if (!vtt.startsWith("WEBVTT") || !/\d{2}:\d{2}(?::\d{2})?\.\d{3}\s+-->/.test(vtt) || vtt.length>2000000) return;
      let lang="";
      try { const u=new URL(sourceUrl,location.href); lang=u.searchParams.get("tlang")||u.searchParams.get("lang")||""; } catch (_url) {}
      window.postMessage({__idmLinuxSubtitleText:true,vtt,label:lang?"lang:"+lang:"altyazı",lang,sourceUrl},"*");
    };
    const scanPlayerConfigs = () => {
      if (!window.__idmLinuxCaptureEnabled()) return;
      let count = 0, total = 0;
      for (const script of document.querySelectorAll("script:not([src])")) {
        if (++count > 60) break;
        const text = script.textContent || "";
        total += text.length;
        if (total > 2000000) break;
        if (text.length < 2000000 && /tracks|subtitles|captions/i.test(text)) scanSubUrls(text);
      }
      try {
        if (typeof window.jwplayer === "function") {
          const player = window.jwplayer();
          if (player && typeof player.getPlaylist === "function") scanSubUrls(JSON.stringify(player.getPlaylist()));
        }
      } catch (_player) {}
    };
    setTimeout(scanPlayerConfigs, 1700);
    setTimeout(scanPlayerConfigs, 6500);
    window.addEventListener("idm-linux-capture-state", scanPlayerConfigs);
    let captionContextGeneration = 0;
    for (const event of ["idm-linux-capture-state", "yt-navigate-start", "popstate", "hashchange"]) {
      window.addEventListener(event, () => { captionContextGeneration += 1; });
    }
    try {
      const origFetch = window.fetch;
      if (origFetch) {
        window.fetch = function (input, init) {
          const requestPage = location.href, requestGeneration = captionContextGeneration;
          try { emitSub(typeof input === "string" ? input : (input && input.url) || ""); } catch (_e) {}
          const p = origFetch.apply(this, arguments);
          try {
            p.then((resp) => {
              try {
                if (!window.__idmLinuxCaptureEnabled() || (location.href !== requestPage || requestGeneration !== captionContextGeneration) || !resp || !resp.headers) return;
                const ct = String(resp.headers.get("content-type") || "");
                if (ct && !/text|json|xml|javascript/i.test(ct)) return; // video/ikili yanıtları atla
                if (Number(resp.headers.get("content-length") || 0) > 2000000) return;
                const copy = resp.clone();
                const readTextBounded = async () => {
                  if (!copy.body || !copy.body.getReader) { const text = await copy.text(); return text.length <= 2000000 ? text : ""; }
                  const reader = copy.body.getReader(), decoder = new TextDecoder();
                  let total = 0, text = "", timedOut = false;
                  const timer = setTimeout(() => { timedOut = true; try { reader.cancel().catch(() => {}); } catch (_cancel) {} }, 4000);
                  try {
                    while (window.__idmLinuxCaptureEnabled() && location.href === requestPage && requestGeneration === captionContextGeneration) {
                      const result = await reader.read();
                      if (result.done) return timedOut ? "" : text + decoder.decode();
                      total += result.value.byteLength;
                      if (total > 2000000) return "";
                      text += decoder.decode(result.value,{stream:true});
                    }
                    return "";
                  } finally { clearTimeout(timer); try { reader.cancel().catch(() => {}); } catch (_cancel) {} }
                };
                readTextBounded().then((txt) => { try { if (!window.__idmLinuxCaptureEnabled() || (location.href !== requestPage || requestGeneration !== captionContextGeneration)) return; scanSubUrls(txt, resp.url || location.href); captureCaptionText(txt,resp.url || location.href); } catch (_e2) {} }).catch(() => {});
              } catch (_e) {}
            }).catch(() => {});
          } catch (_e) {}
          return p;
        };
      }
      const origOpen = window.XMLHttpRequest.prototype.open;
      const origSend = window.XMLHttpRequest.prototype.send;
      window.XMLHttpRequest.prototype.open = function (method, url, ...rest) {
        try { this.__idmCaptionRequestPage = location.href; this.__idmCaptionGeneration = captionContextGeneration; emitSub(url); } catch (_e) {}
        return origOpen.call(this, method, url, ...rest);
      };
      window.XMLHttpRequest.prototype.send = function (...sargs) {
        try {
          this.addEventListener("load", () => {
            try {
              const rt = this.responseType;
              if (!window.__idmLinuxCaptureEnabled() || this.__idmCaptionRequestPage !== location.href || this.__idmCaptionGeneration !== captionContextGeneration || this.status < 200 || this.status >= 300) return;
              if (rt && rt !== "text" && rt !== "json") return;
              const txt = rt === "json" ? JSON.stringify(this.response) : this.responseText;
              if (txt && txt.length < 2000000) { scanSubUrls(txt, this.responseURL || location.href); captureCaptionText(txt,this.responseURL || location.href); }
            } catch (_e) {}
          });
        } catch (_e) {}
        return origSend.apply(this, sargs);
      };
    } catch (_e) {}
    // v3.2.1: sonradan eklenen <track> öğeleri de yakalansın (debounce'lu gözlemci)
    let subScanTimer = null;
    try {
      new MutationObserver(() => {
        if (subScanTimer) return; // throttle: continuous player mutations must not starve scanning
        subScanTimer = setTimeout(() => { subScanTimer = null; scan(); scanPlayerConfigs(); }, 1200);
      }).observe(document.documentElement, { childList: true, subtree: true });
    } catch (_e) {}
    setTimeout(scan, 6000);
  } catch (_e) {}
})();

// v3.5.0 → v3.11.0: YOUTUBE MOTORU (2 katman)
//  KATMAN 1 — ANINDA VİDEO KAYNAKLARI: ytInitialPlayerResponse.streamingData içindeki
//   ŞİFRESİZ (url alanı dolu, signatureCipher YOK) muxed formatlar (itag 18/22/59/78)
//   milisaniyeler içinde emit edilir → bara "⚡ Hazır" satırları yt-dlp BEKLETMEDEN düşer.
//   (Kullanıcı şikâyeti: "YouTube kaynakları aşırı geç bulunuyor / bazen hiç bulunamıyor."
//   Kök neden: eski sürümde googlevideo URL'leri hiç yakalanmıyordu, her şey yt-dlp'ye mahkûmdı.)
//  KATMAN 2 — DOWNSUB-YAKLAŞIMI ALTYAZI: captionTracks baseUrl sayfa bağlamında
//   (çerez + IP + POT bağlamı) fetch edilir; WEBVTT dönerse metin HAZİNESİNE yazılır
//   (IDM 0 bayt imkânsız); alınamazsa eski URL girişi bırakılır (sunucu tarafı 4
//   header-rotasyonu + yt-dlp yedeği hâlâ devrede).
(function () {
  try {
    if (!/(^|\.)youtube\.com$|(^|\.)youtube-nocookie\.com$|(^|\.)youtu\.be$/i.test(location.hostname)) return;
    const emitStream = window.__idmEmitStream;
    if (typeof emitStream !== "function") return;
    const seen = new Set();
    const seenSubText = new Set();
    const captionQueue = [], captionControllers = new Set();
    let captionGeneration = 0, navigating = false;
    const currentVideoId = () => {
      const url = new URL(location.href);
      return url.searchParams.get("v") || (url.pathname.match(/^\/(?:shorts|embed|live)\/([^/]+)/) || [])[1] || "";
    };
    const resetCaptionWork = () => {
      captionGeneration += 1; captionQueue.length = 0;
      for (const controller of captionControllers) controller.abort();
      seen.clear(); seenSubText.clear();
    };
    const pumpCaptions = () => {
      while (window.__idmLinuxCaptureEnabled() && !navigating && captionControllers.size < 4 && captionQueue.length) {
        const task = captionQueue.shift();
        if (task.generation !== captionGeneration || task.page !== location.href) continue;
        const controller = new AbortController(); captionControllers.add(controller);
        const valid = () => !controller.signal.aborted && task.generation === captionGeneration &&
          task.page === location.href && window.__idmLinuxCaptureEnabled() && !navigating;
        const timer = setTimeout(() => controller.abort(), 8000);
        Promise.resolve().then(() => {
          if (!valid()) throw new Error("Stale caption");
          return fetch(task.url, { credentials: "include", signal: controller.signal });
        }).then(async response => {
          if (!valid() || !response.ok || Number(response.headers.get("content-length") || 0) > 2000000) return;
          let text = "";
          if (response.body && response.body.getReader) {
            const reader = response.body.getReader(), decoder = new TextDecoder(); let bytes = 0;
            try {
              while (valid()) {
                const result = await reader.read();
                if (result.done) { text += decoder.decode(); break; }
                bytes += result.value.byteLength;
                if (bytes > 2000000) return;
                text += decoder.decode(result.value, {stream:true});
              }
            } finally { try { await reader.cancel(); } catch (_cancel) {} }
          } else { text = await response.text(); }
          if (!valid() || text.length > 2000000 || !/^\uFEFF?WEBVTT\b/.test(text) || !text.includes("-->")) return;
          if (!seenSubText.has(task.key)) {
            seenSubText.add(task.key);
            window.postMessage({__idmLinuxSubtitleText:true,vtt:text,label:task.label,lang:task.lang,sourceUrl:task.url},"*");
          }
        }).catch(() => {}).finally(() => {
          clearTimeout(timer); captionControllers.delete(controller); pumpCaptions();
        });
      }
    };


    // v3.11.0 KATMAN 1: şifresiz muxed formatları anında bara ışınla
    const mineStreamingData = (resp) => {
      try {
        const sd = resp && resp.streamingData;
        if (!sd) return;
        const fmts = (sd.formats || []).concat(sd.adaptiveFormats || []);
        for (const f of fmts) {
          try {
            if (!f || !f.url || f.signatureCipher || f.cipher) continue; // şifreliler oynatıcıdan yakalanır
            const itag = String(f.itag || "");
            if (itag !== "18" && itag !== "22" && itag !== "59" && itag !== "78") continue;
            emitStream(f.url, { mime: String(f.mimeType || "video/mp4").split(";")[0].trim() });
          } catch (_e) {}
        }
      } catch (_e) {}
    };

    const emitTracks = (resp) => {
      if (!window.__idmLinuxCaptureEnabled() || navigating) return;
      try {
        const expectedId = currentVideoId();
        if (expectedId && resp && resp.videoDetails && resp.videoDetails.videoId && resp.videoDetails.videoId !== expectedId) return;
        mineStreamingData(resp);
        const renderer = resp && resp.captions && resp.captions.playerCaptionsTracklistRenderer;
        if (!renderer) return;
        const tracks = renderer.captionTracks || [];
        tracks.slice(0,300).forEach((tr) => {
          try {
            let base = tr.baseUrl || "";
            if (!base) return;
            const captionUrl = new URL(base, location.href);
            captionUrl.searchParams.set("fmt", "vtt");
            base = captionUrl.href;
            const nm = (tr.name && (tr.name.simpleText || (tr.name.runs && tr.name.runs[0] && tr.name.runs[0].text))) || tr.languageCode || "altyazı";
            const isAuto = tr.kind === "asr";
            const label = isAuto ? `${nm} (Otomatik)` : nm;
            const lang = tr.languageCode || "";
            const videoId = (resp.videoDetails && resp.videoDetails.videoId) || new URL(location.href).searchParams.get("v") || location.pathname;
            const key = `${videoId}|${lang}|${isAuto}|${label}`;
            if (seen.has(key)) return;
            seen.add(key);
            // v3.11.0 KATMAN 2: sayfa bağlamında indir (downsub yaklaşımı)
            const emitUrlEntry = () => {
              try { window.postMessage({ __idmLinuxSubtitle: true, url: base, label: label }, "*"); } catch (_e) {}
            };
            emitUrlEntry();
            if (captionQueue.length < 300) {
              captionQueue.push({url:base,label,lang,key,page:location.href,generation:captionGeneration});
              pumpCaptions();
            }
          } catch (_e) {}
        });
      } catch (_e) {}
    };
    // 1) Sayfa ilk açılışındaki global player yanıtı (SPA gezinmelerinde yenilenmez — poll ile taze)
    const scanPlayerResponse = () => {
      if (!window.__idmLinuxCaptureEnabled()) return;
      try {
        let resp = window.ytInitialPlayerResponse || null;
        if (!resp && window.ytplayer && window.ytplayer.config) {
          resp = window.ytplayer.config.args && window.ytplayer.config.args.player_response;
          if (typeof resp === "string") { resp = JSON.parse(resp); }
        }
        if (resp) emitTracks(resp);
        // 2) SPA gezinmesi: ytplayer.config güncel değilse #movie_player verisinden dene
        const mp = document.getElementById("movie_player");
        if (mp && mp.getPlayerResponse) {
          const live = mp.getPlayerResponse();
          if (live) emitTracks(live);
        }
      } catch (_e) {}
    };
    scanPlayerResponse();
    const poll = setInterval(scanPlayerResponse, 2000);
    window.addEventListener("idm-linux-capture-state", () => {
      if (!window.__idmLinuxCaptureEnabled()) resetCaptionWork();
      else scanPlayerResponse();
    });
    window.addEventListener("yt-navigate-start", () => { navigating = true; resetCaptionWork(); }, true);
    window.addEventListener("yt-player-updated", scanPlayerResponse, true);
    window.addEventListener("yt-page-data-updated", scanPlayerResponse, true);
    // v3.6.0: poll ömrü 60 -> 180 sn (uzun videolarda/çalma listelerinde bar altyazı
    // görmeye devam etsin) + SPA gezinmelerinde ('yt-navigate-finish') anında tazele.
    setTimeout(() => clearInterval(poll), 180000);
    try {
      window.addEventListener("yt-navigate-finish", () => {
        try {
          navigating = false; resetCaptionWork();
          const mp = document.getElementById("movie_player");
          if (mp && mp.getPlayerResponse) {
            const live = mp.getPlayerResponse();
            if (live) emitTracks(live);
          } else if (window.ytInitialPlayerResponse) {
            emitTracks(window.ytInitialPlayerResponse);
          }
        } catch (_e2) {}
      }, true);
    } catch (_e) {}
  } catch (_e) {}
})();

// v2.9.6: WebRTC DataChannel sifonu — P2P baytları geldigi ANDA IDM'ye akar (justbeamit vb.)
(function () {
  try {
    if (typeof RTCPeerConnection === "undefined") return;
    if (!/(^|\.)justbeamit\.com$/.test(location.host)) return;
    const seen = new WeakSet();
    let active = false;
    const hookChannel = (ch) => {
      if (!ch || seen.has(ch)) return;
      seen.add(ch);
      let bytes = 0;
      ch.addEventListener("message", (ev) => {
        try {
          if (!window.__idmLinuxCaptureEnabled()) return;
          const d = ev.data;
          if (typeof d === "string") return;
          const buf = d instanceof ArrayBuffer ? d : (d && d.buffer instanceof ArrayBuffer ? d.buffer : null);
          if (!buf || !buf.byteLength) return;
          bytes += buf.byteLength;
          if (bytes > 1024 * 1024 * 1024) return;
          if (!active) { active = true; window.postMessage({ __idmLinuxSiphonStart: true }, "*"); }
          const u8 = new Uint8Array(buf);
          let bin = "";
          for (let i = 0; i < u8.length; i += 0x8000) bin += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
          window.postMessage({ __idmLinuxSiphonChunk: true, b64: btoa(bin) }, "*");
        } catch (_e) {}
      });
      ch.addEventListener("close", () => window.postMessage({ __idmLinuxSiphonEnd: true }, "*"));
    };
    const OrigPC = window.RTCPeerConnection;
    const Wrapped = function (...args) {
      const pc = new OrigPC(...args);
      pc.addEventListener("datachannel", (ev) => { try { hookChannel(ev.channel); } catch (_e) {} });
      return pc;
    };
    Wrapped.prototype = OrigPC.prototype;
    window.RTCPeerConnection = Wrapped;
    try {
      const desc = Object.getOwnPropertyDescriptor(OrigPC.prototype, "ondatachannel");
      if (desc && desc.set) {
        Object.defineProperty(OrigPC.prototype, "ondatachannel", {
          get: desc.get,
          set(fn) {
            desc.set.call(this, (ev) => { try { hookChannel(ev.channel); } catch (_e) {} return fn ? fn(ev) : undefined; });
          },
          configurable: true,
        });
      }
    } catch (_e) {}
    if (typeof URL !== "undefined" && typeof URL.createObjectURL === "function") {
      const oco = URL.createObjectURL.bind(URL);
      URL.createObjectURL = function (obj) {
        if (active && obj && typeof Blob !== "undefined" && obj instanceof Blob) {
          window.postMessage({ __idmLinuxSiphonEnd: true }, "*");
        }
        return oco(obj);
      };
    }
  } catch (_e) {}
})();

// v3.1.0: DRM (EME) algılama — dsmartgo gibi Widevine'lı canlı TV sitelerinde bar
// 'bulunamadı' yerine net 'DRM korumalı' mesajı göstersin.
(function () {
  try {
    if (window.__idmLinuxDrmHooked__) return;
    window.__idmLinuxDrmHooked__ = true;
    let reported = false;
    const report = (ks) => {
      if (reported) return;
      reported = true;
      try {
        window.postMessage({
          __idmLinuxDrmDetected: true,
          keySystem: String(ks || ""),
          pageUrl: location.href
        }, "*");
      } catch (_e) {}
    };
    if (navigator.requestMediaKeySystemAccess) {
      const orig = navigator.requestMediaKeySystemAccess.bind(navigator);
      navigator.requestMediaKeySystemAccess = function (keySystem, ...rest) {
        report(keySystem);
        return orig(keySystem, ...rest);
      };
    }
    // Shaka/dash.js bazı yollardan doğrudan MediaKeys'e gider — setMediaKeys'i de izle
    try {
      const dmd = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, "mediaKeys");
      if (dmd && dmd.set) {
        Object.defineProperty(HTMLMediaElement.prototype, "mediaKeys", {
          get: dmd.get,
          set(v) {
            if (v) report("mediakeys");
            return dmd.set.call(this, v);
          },
          configurable: true,
        });
      }
    } catch (_e) {}
  } catch (_e) {}
})();

// v3.1.0: abyss.to / short.icu gömülü iframe TARAMASI — parent sayfada (belgeselsemo vb.)
// iframe geç yüklenirse bile bar abyss kaynaklarını bulsun (content.js DOM taramasına ek).
(function () {
  try {
    if (/abyssplayer\.com|abysscdn\.com|embedplayabyss\.top|abyss\.to|short\.icu/.test(location.host)) return;
    const reported = new Set();
    let scans = 0;
    const scan = () => {
      scans += 1;
      if (scans > 30) return; // ~90 sn sonra sus
      try {
        for (const fr of document.querySelectorAll("iframe[src]")) {
          let abs = "";
          try { abs = new URL(fr.getAttribute("src"), location.href).href; } catch (_e) { continue; }
          let host = "";
          try { host = new URL(abs).hostname; } catch (_e) { continue; }
          if (!/(^|\.)(abyss\.to|abyssplayer\.com|abysscdn\.com|embedplayabyss\.top|short\.icu)$/i.test(host)) continue;
          if (reported.has(abs)) continue;
          reported.add(abs);
          window.postMessage({ __idmLinuxAbyssIframe: true, url: abs, pageUrl: location.href }, "*");
        }
      } catch (_e) {}
      if (scans < 30 && reported.size === 0) setTimeout(scan, 3000);
    };
    scan();
  } catch (_e) {}
})();

// v3.2.0: ok.ru / vk.ru / vkvideo.ru SAYFA GÖMÜLÜ JSON kazıyıcı — bu siteler video URL'lerini
// sayfa HTML'ine gömer (ok.ru data-options, vk playerParams). Oynatıcı ağ isteklerini kaçırsa
// bile bar kaynak bulur. SPA gezinmelerinde de yeniden taranır.
(function () {
  try {
    if (!/(^|\.)(ok\.ru|odnoklassniki\.ru|vk\.com|vk\.ru|vkvideo\.ru|vkontakte\.ru)$/i.test(location.host)) return;
    const emit = window.__idmEmitStream;
    if (!emit) return;
    const seen = new Set();
    let scans = 0;
    let lastLen = -1;
    const KEY_RX = /"(hlsManifestUrl|hlsManifest|dashUrl|dashManifest|manifestUrl|hlsUrl|hls|url1080|url720|url480|url360|url240|url144|mp4-1080|mp4-720|mp4-480|mp4-360|playUrl|play_url)"\s*:\s*"((?:https?:\\?\/\\?\/|\/\/)[^"]{10,700}?)"/g;
    const scan = () => {
      scans += 1;
      if (scans > 45) return; // ~90 sn sonra sus
      try {
        let html = (document.documentElement && document.documentElement.innerHTML) || "";
        if (!html || html.length === lastLen) {
          setTimeout(scan, 2000);
          return;
        }
        lastLen = html.length;
        if (html.length > 6000000) html = html.slice(0, 6000000);
        const texts = [html, html.replace(/&quot;/g, '"')];
        for (const txt of texts) {
          if (window.__idmEmitOkru) window.__idmEmitOkru(txt); // v3.12.0: ok.ru mp4
          KEY_RX.lastIndex = 0;
          let mk;
          let guard = 0;
          while ((mk = KEY_RX.exec(txt)) !== null && guard < 12) {
            guard += 1;
            let u = mk[2].replace(/\\\//g, "/");
            if (u.startsWith("//")) u = "https:" + u;
            if (!/^https?:\/\//i.test(u) || seen.has(u)) continue;
            const keyName = mk[1];
            const isHls = /\.m3u8(\?|#|$)/i.test(u) || /manifest|playlist/i.test(u) || /hls/i.test(keyName);
            if (!isHls && !/\.(mp4|mkv|webm|mov|m4v)(\?|#|$)/i.test(u)) continue;
            seen.add(u);
            emit(u, { isHls, mime: isHls ? "application/vnd.apple.mpegurl" : "video/mp4" });
          }
        }
      } catch (_e) {}
      setTimeout(scan, 2000);
    };
    scan();
  } catch (_e) {}
})();

// v3.10.0: OYNATICIYA GÖMÜLÜ ALTYAZILAR (kullanıcı raporu: "oynatıcıdaki altyazı
// bar'da hiç görünmüyor"). Birçok oyuncu altyazıyı <track> ile DEĞİL, MediaSource
// + TextTrack API ile belleğe ekler; böyle bir altyazının indirilebilir URL'si
// YOKTUR. Burada video.textTracks cue'ları WebVTT metnine serileştirilir; içerik
// betiği bunu daemon'a yollar (POST /api/subtitle/register) ve daemon yerel bir
// adres üretir — IDM gerçek bir .vtt/.srt indirir.
(function () {
  try {
    const sentKeys = new Set();
    const pad = (n, w) => String(Math.floor(n)).padStart(w, "0");
    const stamp = (t) => {
      const ms = Math.max(0, Math.round((t || 0) * 1000));
      return `${pad(ms / 3600000, 2)}:${pad((ms / 60000) % 60, 2)}:${pad((ms / 1000) % 60, 2)}.${pad(ms % 1000, 3)}`;
    };
    const cueText = (cue) => String(cue.text || "").replace(/\r/g, "").trim();
    const collect = () => {
      if (!window.__idmLinuxCaptureEnabled()) return;
      document.querySelectorAll("video").forEach((video) => {
        let tracks;
        try { tracks = video.textTracks; } catch (_e) { return; }
        if (!tracks) return;
        for (let i = 0; i < tracks.length; i += 1) {
          const tr = tracks[i];
          try {
            const kind = String(tr.kind || "").toLowerCase();
            if (kind && kind !== "subtitles" && kind !== "captions") continue;
            const cues = tr.cues;
            if (!cues || !cues.length || cues.length > 6000) continue;
            // External <track> has a complete source; do not create a second,
            // potentially partial TextTrack snapshot under an unrelated vault URL.
            const external = Array.from(video.querySelectorAll("track")).some(el =>
              el.track === tr && /^https?:\/\//i.test(el.src || ""));
            if (external) continue;
            const label = tr.label || tr.language || (kind === "captions" ? "Altyazı" : "altyazı");
            const lines = [];
            for (let c = 0; c < cues.length && c < 6000; c += 1) {
              const cue = cues[c];
              const body = cueText(cue);
              if (!body) continue;
              lines.push(`${stamp(cue.startTime)} --> ${stamp(cue.endTime)}\n${body}`);
            }
            if (!lines.length) continue;
            const vtt = "WEBVTT\n\n" + lines.join("\n\n") + "\n";
            const key = `${label}|${lines.length}|${vtt.length}|${vtt.slice(-40)}`;
            if (sentKeys.has(key)) continue;
            if (sentKeys.size > 300) sentKeys.clear();
            sentKeys.add(key);
            window.postMessage(
              { __idmLinuxSubtitleText: true, vtt, label: label.slice(0, 80), lang: tr.language || "" },
              "*"
            );
          } catch (_e) { /* kuyruk erişimi kısıtlı olabilir */ }
        }
      });
    };
    setTimeout(collect, 2200);
    const timer = setInterval(collect, 5000);
    setTimeout(() => clearInterval(timer), 180000);
  } catch (_e) {}
})();
