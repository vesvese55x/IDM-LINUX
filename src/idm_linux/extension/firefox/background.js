/* IDM Linux Hybrid Integration — Background Service Worker / Event Script v2.3 */
"use strict";

const extApi = typeof browser !== "undefined" ? browser : chrome;
// Fail open until persisted state is loaded. Disabling must not intercept browser downloads.
let extensionDisabled = true;
function setCaptureDisabled(value) {
  const wasDisabled = extensionDisabled;
  extensionDisabled = Boolean(value);
  if (wasDisabled && !extensionDisabled) refreshDaemonState().catch(() => {});
  callBridge("/api/ext-state", "POST", { disabled: extensionDisabled }, null).catch(() => {});
  if (extensionDisabled) {
    interceptedDownloadIds.clear();
    blobUploadOwners.clear();
    _takeoverUrls.clear();
    _gofileTakeoverUntil = 0;
  }
}
extApi.storage.local.get(["extDisabled"], (r) => setCaptureDisabled(r && r.extDisabled));
extApi.storage.onChanged.addListener((changes, area) => {
  if (area === "local" && changes.extDisabled) setCaptureDisabled(changes.extDisabled.newValue);
});

const BRIDGE_HTTP = "http://127.0.0.1:17802";
const NATIVE_HOSTS = ["com.idmlinux.companion", "com.tonec.idm"];

const DEFAULT_EXTENSIONS = new Set([
  "3GP", "7Z", "AAC", "ACE", "AIF", "APK", "APPIMAGE", "ARJ", "ASF", "AVI",
  "BIN", "BZ2", "DEB", "DMG", "DOC", "DOCX", "EXE", "F4V", "FLAC", "FLV",
  "GZ", "IMG", "ISO", "LZH", "M4A", "M4V", "MKV", "MOV", "MP3", "MP4",
  "MPA", "MPE", "MPEG", "MPG", "MSI", "MSU", "OGG", "OGV", "OPUS", "PDF",
  "PLJ", "PPS", "PPT", "PPTX", "QT", "RAR", "RM", "RMVB", "RPM", "SEA",
  "SIT", "SITX", "TAR", "TBZ2", "TGZ", "TIF", "TIFF", "TORRENT", "TS",
  "VOB", "WAV", "WEBM", "WMA", "WMV", "XLS", "XLSX", "XZ", "Z", "ZIP", "ZST"
]);

const BINARY_MIMES = new Set([
  "application/octet-stream",
  "application/x-msdownload",
  "application/x-msi",
  "application/x-7z-compressed",
  "application/zip",
  "application/x-rar-compressed",
  "application/vnd.rar",
  "application/x-tar",
  "application/gzip",
  "application/x-bzip2",
  "application/x-xz",
  "application/zstd",
  "application/vnd.debian.binary-package",
  "application/x-rpm",
  "application/x-iso9660-image",
  "application/x-bittorrent"
]);

const MEDIA_MIME_PATTERNS = [
  /^video\//i,
  /^audio\//i,
  /application\/(vnd\.apple\.mpegurl|x-mpegurl|dash\+xml)/i
];

const MEDIA_EXT_REGEX = /\.(mp4|webm|mkv|flv|mov|m4v|m3u8|mpd|mp3|m4a|flac|ogg)(\?|$)/i;

// Sekme bazlı yakalanan medya akışları: tabId -> Map<url, {url, mime, size, referer, origin, detectedAt}>
const tabStreams = new Map();
const blobUploadOwners = new Map();
// v3.11.0: YouTube videoplayback segment-seri sayacı (tabId -> Map(seriesKey -> count))
const ytSeriesCount = new Map();
// İstek bazlı gerçek Referer / Origin önbelleği: requestId -> {referer, origin}
const reqHeadersMap = new Map();

// Klavye kısayol durumları (Alt = atla, Insert = zorla yakala)
let bypassCaptureUntil = 0;
let forceCaptureUntil = 0;
// v3.14.2: 'Hayır' denen torrent URL'leri (url -> son kullanım ts) — popup döngü koruması
const torrentDeclineUrls = new Map();

// Köprü yapılandırma önbelleği (senkron 0ms indirme yakalama için her zaman sıcak tutulur)
let cachedState = {
  capture_downloads: true,
  video_bar_enabled: true,
  official_extension_connected: false,
  idm_installed: true,
  excluded_domains: [],
  file_extensions: Array.from(DEFAULT_EXTENSIONS),
  online: false
};

function sendNativePromise(hostName, payload) {
  // v3.6.0: native messaging yanıt vermezse 12 sn'de iptal — asılı promise barı dondurmaz
  return Promise.race([
    new Promise((resolve, reject) => {
      try {
        if (typeof browser !== "undefined" && browser.runtime && browser.runtime.sendNativeMessage) {
          browser.runtime.sendNativeMessage(hostName, payload).then(resolve, reject);
        } else {
          chrome.runtime.sendNativeMessage(hostName, payload, (resp) => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message));
            } else {
              resolve(resp);
            }
          });
        }
      } catch (err) {
        reject(err);
      }
    }),
    new Promise((_resolve, reject) => setTimeout(() => reject(new Error("native timeout")), 12000)),
  ]);
}

// v2.9.7: KÖPRÜ BEKÇİSİ — bridge yoksa native host ile UYANDIR, sonra yeniden dene
let lastWakeAt = 0;
async function wakeDaemon(force = false) {
  if (extensionDisabled) return false;
  const now = Date.now();
  if (!force && now - lastWakeAt < 15000) return false;
  lastWakeAt = now;
  for (const host of NATIVE_HOSTS) {
    try {
      await sendNativePromise(host, { action: "status" });
      return true;
    } catch (_e) {}
  }
  return false;
}

setInterval(async () => {
  if (extensionDisabled) return;
  try {
    await fetch(`${BRIDGE_HTTP}/api/status`, { method: "GET", headers: { "X-IDM-Linux": "1" } });
    cachedState.online = true;
  } catch (_e) {
    cachedState.online = false;
    await wakeDaemon();
  }
}, 20000);

// v3.6.0: HTTP çağrıları zaman aşımıyla SARILIR — daemon yavaşsa/askıda kalırsa fetch SONSUZA
// dek açıkta kalmaz ve bar 'Kaliteler hazırlanıyor...' da SONSUZA dek takılıp kalmaz.
const BRIDGE_TIMEOUT_MS = 45000; // probe/video: yt-dlp arka planda döner, 45 sn üst sınırdır

function fetchWithTimeout(url, opts, timeoutMs = BRIDGE_TIMEOUT_MS) {
  const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
  const t = setTimeout(() => { try { if (ctrl) ctrl.abort(); } catch (_e) {} }, timeoutMs);
  const merged = Object.assign({}, opts, ctrl ? { signal: ctrl.signal } : {});
  return fetch(url, merged).finally(() => clearTimeout(t));
}

async function callBridge(endpoint, method = "POST", body = null, nativeAction = null) {
  const opts = {
    method,
    headers: { "Content-Type": "application/json", "X-IDM-Linux": "1" }
  };
  if (body && method !== "GET") {
    opts.body = JSON.stringify(body);
  }
  try {
    const resp = await fetchWithTimeout(`${BRIDGE_HTTP}${endpoint}`, opts);
    if (resp.ok) {
      const data = await resp.json();
      cachedState.online = true;
      return data;
    }
    // v3.6.0: 4xx/5xx yanıtlarını KAYBETME — köprü çalışıyor demektir, hata metni kullanıcıya gitsin
    let errPayload = null;
    try { errPayload = await resp.json(); } catch (_j) {}
    if (errPayload && typeof errPayload === "object") {
      cachedState.online = true;
      return Object.assign({ _httpStatus: resp.status }, errPayload);
    }
  } catch (_httpErr) {
    // v2.9.7: yerel daemon uyuyorsa/cökmediyse native host ile uyandır ve BİR kez daha dene
    await wakeDaemon(true);
    try {
      await new Promise((r) => setTimeout(r, 1200));
      const resp2 = await fetchWithTimeout(`${BRIDGE_HTTP}${endpoint}`, opts);
      if (resp2.ok) {
        const data2 = await resp2.json();
        cachedState.online = true;
        return data2;
      }
      let errPayload2 = null;
      try { errPayload2 = await resp2.json(); } catch (_j) {}
      if (errPayload2 && typeof errPayload2 === "object") {
        cachedState.online = true;
        return Object.assign({ _httpStatus: resp2.status }, errPayload2);
      }
    } catch (_e2) {}
  }

  if (nativeAction) {
    const nativePayload = Object.assign({ action: nativeAction }, body || {});
    for (const host of NATIVE_HOSTS) {
      try {
        const res = await sendNativePromise(host, nativePayload);
        if (res && typeof res === "object") {
          cachedState.online = true;
          return res;
        }
      } catch (_natErr) {}
    }
  }

  cachedState.online = false;
  return { ok: false, offline: true };
}

let lastAutoReloadCheckTs = 0;

async function refreshDaemonState() {
  if (extensionDisabled) return cachedState;
  const st = await callBridge("/api/status", "GET", null, "status");
  if (st && st.ok) {
    cachedState = {
      capture_downloads: st.capture_downloads !== false,
      video_bar_enabled: st.video_bar_enabled !== false,
      official_extension_connected: Boolean(st.official_extension_connected),
      excluded_domains: Array.isArray(st.excluded_domains) ? st.excluded_domains : [],
      file_extensions: Array.isArray(st.file_extensions) ? st.file_extensions : Array.from(DEFAULT_EXTENSIONS),
      idm_installed: Boolean(st.idm_installed),
      idm_running: Boolean(st.idm_running),
      downloads_dispatched: st.downloads_dispatched || 0,
      version: st.version || "",
      online: true
    };

    // Paket güncellendiğinde (örn. v2.1.0 -> v2.2.0) unpacked eklentiyi otomatik yenile!
    try {
      const localVer = (extApi.runtime.getManifest && extApi.runtime.getManifest().version) || "";
      if (st.version && localVer && st.version !== localVer && Date.now() - lastAutoReloadCheckTs > 120000) {
        lastAutoReloadCheckTs = Date.now();
        extApi.storage.local.get(["lastReloadedForVer"], (items) => {
          void extApi.runtime.lastError;
          if (!items || items.lastReloadedForVer !== st.version) {
            extApi.storage.local.set({ lastReloadedForVer: st.version }, () => {
              void extApi.runtime.lastError;
              extApi.runtime.reload();
            });
          }
        });
      }
    } catch (_e) {}
  }
  return cachedState;
}

// Önbelleği düzenli sıcak tut (0ms senkron yakalamanın her zaman güncel kalması için)
setInterval(() => {
  refreshDaemonState().catch(() => {});
}, 15000);

const urlAuthCache = new Map();
const hostAuthCache = new Map();
const hostSyncTs = new Map();

function mergeCookieStrings(...cookieLists) {
  const seen = new Map();
  for (const raw of cookieLists) {
    if (!raw || typeof raw !== "string") continue;
    for (const part of raw.split(";")) {
      const p = part.trim();
      if (!p) continue;
      const eq = p.indexOf("=");
      if (eq > 0) {
        const k = p.slice(0, eq).trim();
        const v = p.slice(eq + 1).trim();
        if (k && v && !seen.has(k)) {
          seen.set(k, v);
        }
      }
    }
  }
  return Array.from(seen.entries()).map(([k, v]) => `${k}=${v}`).join("; ");
}

function getBaseDomain(hostname) {
  const h = (hostname || "").toLowerCase().replace(/^\.+|\.+$/g, "");
  const parts = h.split(".");
  return parts.length >= 2 ? parts.slice(-2).join(".") : h;
}

function queryCookiesPromise(details) {
  return new Promise((resolve) => {
    try {
      extApi.cookies.getAll(details, (list) => {
        void extApi.runtime.lastError;
        if (!Array.isArray(list) || !list.length) {
          resolve("");
          return;
        }
        resolve(list.map((c) => `${c.name}=${c.value}`).join("; "));
      });
    } catch (_e) {
      resolve("");
    }
  });
}

async function getCookiesHeader(targetUrl, topSiteUrl) {
  if (!targetUrl || !targetUrl.startsWith("http")) return "";
  let host = "";
  let originSite = "";
  try {
    const u = new URL(targetUrl);
    host = u.hostname.toLowerCase();
    originSite = `${u.protocol}//${u.hostname}`;
  } catch (_e) {
    return "";
  }

  const cachedUrl = urlAuthCache.get(targetUrl);
  const cachedHost = hostAuthCache.get(host) || hostAuthCache.get(getBaseDomain(host));

  const queries = [queryCookiesPromise({ url: targetUrl })];
  const baseDom = getBaseDomain(host);
  if (baseDom && baseDom.includes(".")) {
    queries.push(queryCookiesPromise({ domain: baseDom }));
  }

  // CHIPS Partitioned çerezleri (cf_clearance, modern Clerk/Next.js oturumları vb.)
  const partOrigin = (() => {
    try {
      if (topSiteUrl && topSiteUrl.startsWith("http")) {
        const tu = new URL(topSiteUrl);
        return `${tu.protocol}//${tu.hostname}`;
      }
    } catch (_e) {}
    return originSite;
  })();
  if (partOrigin) {
    queries.push(queryCookiesPromise({ url: targetUrl, partitionKey: { topLevelSite: partOrigin } }));
  }

  const results = await Promise.all(queries);
  return mergeCookieStrings(
    cachedUrl && cachedUrl.cookies,
    ...results,
    cachedHost && cachedHost.cookies
  );
}

function getCachedExtraHeaders(targetUrl) {
  if (!targetUrl || !targetUrl.startsWith("http")) return {};
  const exact = urlAuthCache.get(targetUrl);
  let host = "";
  try {
    host = new URL(targetUrl).hostname.toLowerCase();
  } catch (_e) {}
  const byHost = host ? (hostAuthCache.get(host) || hostAuthCache.get(getBaseDomain(host))) : null;
  return Object.assign(
    {},
    (byHost && byHost.extraHeaders) || {},
    (exact && exact.extraHeaders) || {}
  );
}

async function fetchJsonBounded(url, timeout = 6000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, { credentials: "include", signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}; browser verification may be required`);
    return await response.json();
  } finally { clearTimeout(timer); }
}

async function getMergedCookies(urls) {
  const parts = [];
  const primaryTop = urls.find((u) => u && u.startsWith("http")) || "";
  for (const u of urls) {
    if (!u || !u.startsWith("http")) continue;
    const hdr = await getCookiesHeader(u, primaryTop);
    if (hdr) parts.push(hdr);
  }
  return mergeCookieStrings(...parts);
}

function extractExtension(urlStr, filenameStr) {
  const checkTarget = (str) => {
    if (!str) return "";
    try {
      const clean = str.split("?")[0].split("#")[0];
      const base = clean.substring(clean.lastIndexOf("/") + 1);
      const dot = base.lastIndexOf(".");
      if (dot > 0 && dot < base.length - 1) {
        return base.substring(dot + 1).toUpperCase();
      }
    } catch (_e) {}
    return "";
  };
  return checkTarget(filenameStr) || checkTarget(urlStr);
}

function isDomainExcluded(urlStr, refererStr) {
  const list = cachedState.excluded_domains || [];
  if (!list.length) return false;
  const hosts = [];
  for (const s of [urlStr, refererStr]) {
    if (!s) continue;
    try {
      const h = new URL(s).hostname.toLowerCase();
      if (h) hosts.push(h);
    } catch (_e) {}
  }
  for (const rawEx of list) {
    const ex = String(rawEx || "").trim().toLowerCase().replace(/^\*\./, "");
    if (!ex) continue;
    for (const h of hosts) {
      if (h === ex || h.endsWith("." + ex)) return true;
    }
  }
  return false;
}

// ---------------------------------------------------------------------------
// 1. Ağ Trafiğinden Gerçek İstek Başlıkları + Medya Akışı (.mp4/.m3u8/.mpd) Yakalama
// ---------------------------------------------------------------------------
try {
  const extraOpts = ["requestHeaders"];
  if (typeof chrome !== "undefined" && chrome.webRequest && chrome.webRequest.OnBeforeSendHeadersOptions && chrome.webRequest.OnBeforeSendHeadersOptions.EXTRA_HEADERS) {
    extraOpts.push("extraHeaders");
  }
  extApi.webRequest.onBeforeSendHeaders.addListener(
    (details) => {
      if (extensionDisabled) return;
      const reqUrl = details.url || "";
      if (!reqUrl.startsWith("http") || reqUrl.startsWith(BRIDGE_HTTP)) return;

      let referer = "";
      let origin = details.initiator || "";
      let cookies = "";
      const extraHeaders = {};

      for (const h of details.requestHeaders || []) {
        const rawName = h.name || "";
        const n = rawName.toLowerCase();
        const val = h.value || "";
        if (!val) continue;
        if (n === "referer") referer = val;
        else if (n === "origin") origin = val;
        else if (n === "cookie") cookies = val;
        else if (
          n === "authorization" ||
          n === "x-authorization" ||
          n === "x-api-key" ||
          n === "x-auth-token" ||
          n === "x-csrf-token" ||
          n === "x-xsrf-token"
        ) {
          extraHeaders[rawName] = val;
        }
      }

      const now = Date.now();
      if (cookies || Object.keys(extraHeaders).length > 0 || referer) {
        let host = "";
        try {
          host = new URL(reqUrl).hostname.toLowerCase();
        } catch (_e) {}

        const prevHost = host ? hostAuthCache.get(host) : null;
        const snap = {
          cookies: mergeCookieStrings(cookies, prevHost && prevHost.cookies),
          referer: referer || (prevHost && prevHost.referer) || "",
          origin: origin || (prevHost && prevHost.origin) || "",
          extraHeaders: Object.assign({}, (prevHost && prevHost.extraHeaders) || {}, extraHeaders),
          ts: now
        };
        urlAuthCache.set(reqUrl, snap);
        if (urlAuthCache.size > 500) {
          urlAuthCache.delete(urlAuthCache.keys().next().value);
        }
        if (host) {
          hostAuthCache.set(host, snap);
          if (hostAuthCache.size > 200) {
            hostAuthCache.delete(hostAuthCache.keys().next().value);
          }

          // Resmi IDM eklentisi de açık olsa köprünün her zaman güncel çerez/auth bilgisine sahip olması için senkronize et
          const hasRichAuth = Boolean(cookies || Object.keys(extraHeaders).length > 0);
          const lastSync = hostSyncTs.get(host) || 0;
          if (hasRichAuth && cachedState.online && (now - lastSync > 8000 || Object.keys(extraHeaders).length > 0)) {
            hostSyncTs.set(host, now);
            fetch(`${BRIDGE_HTTP}/api/auth-context`, {
              method: "POST",
              headers: { "Content-Type": "application/json", "X-IDM-Linux": "1" },
              body: JSON.stringify({
                url: reqUrl,
                cookies: snap.cookies,
                referer: snap.referer,
                origin: snap.origin,
                userAgent: navigator.userAgent,
                extraHeaders: snap.extraHeaders
              })
            }).catch(() => {});
          }
        }
      }

      if (details.tabId >= 0 && (referer || origin)) {
        reqHeadersMap.set(details.requestId, { referer, origin, ts: now });
        if (reqHeadersMap.size > 400) {
          const oldest = reqHeadersMap.keys().next().value;
          reqHeadersMap.delete(oldest);
        }
      }
    },
    { urls: ["http://*/*", "https://*/*"] },
    extraOpts
  );
} catch (_e) {}

extApi.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (extensionDisabled) return;
    if (details.tabId < 0 || details.statusCode >= 400) return;
    const url = details.url || "";
    if (!url.startsWith("http") || url.startsWith(`${BRIDGE_HTTP}/stream/`)) return;

    if (/\.(ts|m4s|vtt|srt)(\?|$)/i.test(url)) return;

    let mime = "";
    let size = 0;
    for (const h of details.responseHeaders || []) {
      const name = (h.name || "").toLowerCase();
      if (name === "content-type") mime = h.value || "";
      if (name === "content-length") size = parseInt(h.value || "0", 10) || 0;
    }

    // v3.11.0 YOUTUBE ANINDA KAYNAK YAKALAMA — eski sürümde googlevideo/videoplayback
    // istekleri BİLİNÇLİ ATLANIYORDU; bu yüzden bara "⚡ Hazır" anlık kaynak hiç düşmüyor
    // ve her şey 20-90 sn'lik yt-dlp çözümlemesine mahkûm kalıyordu (kullanıcı: "YouTube
    // kaynakları aşırı geç bulunuyor / bazen hiç bulunamıyor"). Artık oynatıcının KENDİ
    // çektiği videoplayback URL'leri akıllı tekilleştirmeyle yakalanır:
    //  • range/rn/rbuf/cmsg/keepalive gibi segment-varişi parametreler SOYULUR (tam dosya indirilebilir URL kalır)
    //  • aynı itag+host serisi sekme başına en fazla 4 kayıt (segment seline karşı)
    if (/googlevideo\.com\/(videoplayback|initplayback)/i.test(url)) {
      const itagM = url.match(/[?&]itag=(\d+)/);
      const itag = itagM ? itagM[1] : "0";
      let norm;
      try {
        const u = new URL(url);
        ["range", "rn", "rbuf", "cmsg", "keepalive", "playerttl", "request", "ei"].forEach((p) => u.searchParams.delete(p));
        norm = u.toString();
      } catch (_e) {
        norm = url;
      }
      // clen (Content-Length) parametresi — aralıklı yanıtların content-length'inden güvenilirdir
      const clenM = url.match(/[?&]clen=(\d+)/);
      const realSize = clenM ? parseInt(clenM[1], 10) || 0 : 0;
      if (!ytSeriesCount.has(details.tabId)) ytSeriesCount.set(details.tabId, new Map());
      const sm = ytSeriesCount.get(details.tabId);
      const seriesKey = itag + "@" + (norm.split("?")[0] || "");
      const cnt = (sm.get(seriesKey) || 0) + 1;
      sm.set(seriesKey, cnt);
      if (sm.size > 40) sm.clear();
      if (cnt > 4) return; // aynı seriden 4. kayıttan sonrası çöp
      if (!tabStreams.has(details.tabId)) tabStreams.set(details.tabId, new Map());
      const streamMap = tabStreams.get(details.tabId);
      const reqMeta = reqHeadersMap.get(details.requestId) || {};
      reqHeadersMap.delete(details.requestId);
      const prevItem = streamMap.get(norm);
      streamMap.set(norm, {
        url: norm,
        mime: (mime || "video/mp4").split(";")[0].trim(),
        isHls: false,
        manifestText: "",
        size: realSize || (prevItem && prevItem.size) || null,
        referer: reqMeta.referer || details.documentUrl || details.initiator || (prevItem && prevItem.referer) || "",
        origin: reqMeta.origin || details.initiator || (prevItem && prevItem.origin) || "",
        detectedAt: Date.now()
      });
      try {
        extApi.tabs.sendMessage(details.tabId, { type: "IDM_MEDIA_UPDATED", count: streamMap.size }, () => { void extApi.runtime.lastError; });
      } catch (_e) {}
      return;
    }

    const isDisguisedHls = /\/(master|index|playlist|chunklist|manifests?|hls)[^/?]*\.(txt|json|m3u)(\?|$)/i.test(url);
    const isManifest = /\.(m3u8|mpd)(\?|$)/i.test(url) || /mpegurl|dash\+xml/i.test(mime) || isDisguisedHls;
    const isMediaMime = MEDIA_MIME_PATTERNS.some((rx) => rx.test(mime));
    const isMediaExt = MEDIA_EXT_REGEX.test(url);

    if (!isManifest && !isMediaMime && !isMediaExt) return;
    if (!isManifest && size > 0 && size < 120 * 1024) return;

    const reqMeta = reqHeadersMap.get(details.requestId) || {};
    reqHeadersMap.delete(details.requestId);
    const streamReferer = reqMeta.referer || details.documentUrl || details.initiator || "";
    const streamOrigin = reqMeta.origin || details.initiator || "";

    if (!tabStreams.has(details.tabId)) {
      tabStreams.set(details.tabId, new Map());
    }
    const streamMap = tabStreams.get(details.tabId);
    const prevItem = streamMap.get(url);
    streamMap.set(url, {
      url,
      mime: mime.split(";")[0].trim(),
      isHls: isDisguisedHls || /\.m3u8(\?|$)/i.test(url) || /mpegurl/i.test(mime) || Boolean(prevItem && prevItem.isHls),
      manifestText: (prevItem && prevItem.manifestText) || "",
      size: size > 0 ? size : null,
      referer: streamReferer || (prevItem && prevItem.referer) || "",
      origin: streamOrigin || (prevItem && prevItem.origin) || "",
      detectedAt: Date.now()
    });

    if (streamMap.size > 300) {
      const firstKey = streamMap.keys().next().value;
      streamMap.delete(firstKey);
    }

    try {
      extApi.tabs.sendMessage(
        details.tabId,
        { type: "IDM_MEDIA_UPDATED", count: streamMap.size },
        () => { void extApi.runtime.lastError; }
      );
    } catch (_e) {}
  },
  { urls: ["http://*/*", "https://*/*"] },
  ["responseHeaders"]
);

// ---------------------------------------------------------------------------
// v3.7.1: ALTYAZI AĞ GÖZLEMCİSİ (TÜM katmanların garantisi) — webRequest her
// çerçeveyi, Web Worker'ları ve sayfa açılmadan yüklenmiş kaynakları GÖRÜR.
// fullhdfilmizlesene/rapidvid gibi sitelerde oyuncu altyazıyı .vtt olarak
// çeker; burada yakalanıp sekmenin içerik komut dosyasına bildirilir.
// ---------------------------------------------------------------------------
const IDM_SUB_EXT_RE = /\.(vtt|srt|ass|ssa|ttml|dfxp|smi|sami|sbv|sub)(\?|#|$)/i;
const IDM_SUB_NAME_RE = /(subtitl|captio|altyaz|timedtext)/i;
const IDM_VIDEO_FILE_RE = /\.(mp4|mkv|webm|avi|mov|m3u8|mpd|ts|m4s|m4v)(\?|#|$)/i;
const idmSubSeen = new Map(); // "tabId|url" -> ts (tekilleştirme + bellek koruması)

try {
  extApi.webRequest.onCompleted.addListener((details) => {
    try {
      const u = details.url || "";
      if (!u.startsWith("http") || u.startsWith(`${BRIDGE_HTTP}/`)) return;
      const t = details.type || "";
      const isMedia = t === "media";
      const isReq = t === "xmlhttprequest" || t === "other" || t === "";
      if (!isMedia && !isReq) return; // ad-tabanı eşleşme yalnızca isteklerde (video dosyası sanılışı olmasın)
      let hit = IDM_SUB_EXT_RE.test(u);
      if (!hit && isReq && IDM_SUB_NAME_RE.test(u) && !IDM_VIDEO_FILE_RE.test(u)) hit = true;
      if (!hit) return;
      const tabId = details.tabId;
      if (typeof tabId !== "number" || tabId < 0) return;
      const key = `${tabId}|${u}`;
      const now = Date.now();
      if (idmSubSeen.has(key)) return;
      idmSubSeen.set(key, now);
      if (idmSubSeen.size > 300) {
        for (const [k, ts] of idmSubSeen) {
          if (now - ts > 180000) idmSubSeen.delete(k);
        }
        if (idmSubSeen.size > 600) idmSubSeen.clear();
      }
      extApi.tabs.sendMessage(
        tabId,
        { type: "IDM_BG_SUBTITLE", url: u, label: "altyazı" },
        () => { void extApi.runtime.lastError; }
      );
    } catch (_e) {}
  }, { urls: ["http://*/*", "https://*/*"] }, []);
} catch (_e) {}

extApi.tabs.onRemoved.addListener((tabId) => {
  tabStreams.delete(tabId);
  for (const [id, owner] of blobUploadOwners) if (owner.startsWith(`${tabId}:`)) blobUploadOwners.delete(id);
  ytSeriesCount.delete(tabId); // v3.11.0: sekme kapanınca sayaç da düşsün
});

extApi.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading" && changeInfo.url) {
    tabStreams.delete(tabId);
    ytSeriesCount.delete(tabId); // v3.11.0: yeni gezinmede seri sayacı sıfırla
  }
});

// ---------------------------------------------------------------------------
// 2. SIFIR-SIZINTILI ANINDA İNDİRME YAKALAMA (Tarayıcının İndirmesini %100 Engeller!)
// ---------------------------------------------------------------------------
const processedDownloadIds = new Set();
const interceptedDownloadIds = new Set();

function isStrictAuthDomain(urlStr) {
  try {
    const h = new URL(urlStr).hostname.toLowerCase();
    return (
      h === "arena.ai" ||
      h.endsWith(".arena.ai") ||
      h === "lmarena.ai" ||
      h.endsWith(".lmarena.ai") ||
      h === "huggingface.co" ||
      h.endsWith(".huggingface.co")
    );
  } catch (_e) {
    return false;
  }
}

function evaluateInterceptSync(item) {
  if (extensionDisabled) return { intercept: false };
  const url = item.finalUrl || item.url || "";
  if (!url.startsWith("http://") && !url.startsWith("https://")) return { intercept: false };
  if (
    url.startsWith(`${BRIDGE_HTTP}/stream/`) ||
    url.startsWith(`${BRIDGE_HTTP}/proxy/`) ||
    url.startsWith(`${BRIDGE_HTTP}/extension/`)
  ) {
    return { intercept: false };
  }
  try {
    const pu = new URL(url);
    if ((pu.hostname === "127.0.0.1" || pu.hostname === "localhost") && pu.pathname.startsWith("/extension/")) {
      return { intercept: false };
    }
  } catch (_e) {}
  if (item.state && item.state !== "in_progress") return { intercept: false };

  const now = Date.now();
  if (now < bypassCaptureUntil) return { intercept: false };

  const referer = item.referrer || "";
  const extraHdrs = getCachedExtraHeaders(url);
  const needsRichAuthTakeover = Object.keys(extraHdrs).length > 0 || isStrictAuthDomain(url);

  const forced = now < forceCaptureUntil;
  if (!forced && !cachedState.capture_downloads) return { intercept: false };
  if (!forced && isDomainExcluded(url, referer)) return { intercept: false };

  // v3.13.0: GOFILE HER KOŞULDA BİZE AİT — kullanıcı kuralı: "tarayıcıda asla
  // inmesin, IDM en doğru şekilde yakalayıp en doğru şekilde indirsin."
  // Daemon artık gofile API'siyle TAZE gerçek store linkini kendisi çözdüğü için
  // (gofile_resolver) burada körlemesine devralmak %100 güvenli.
  if (/gofile\.io\//i.test(url)) {
    return { intercept: true, url, referer, forced: true };
  }

  // v3.14.2: İÇERİK-TİPİ TORRENT TESPİTİ — filmix.gg/download/<id> gibi dinamik .torrent
  // üreticilerinde URL '.torrent' ile BITMEZ; sunucu 'application/x-bittorrent' mime'i veya
  // '*.torrent' dosya adı döndürür. Böyle indirmeler DOSYA olarak değil, 'Torrent İndirme
  // Onayı' penceresiyle karşılanır (Linux Mint .torrent davranışı TÜM sitelerde garanti).
  const lowUrl = url.toLowerCase();
  const fnameLow = (item.filename || "").toLowerCase();
  const mimeLow = (item.mime || "").toLowerCase().split(";")[0].trim();
  const looksTorrent =
    mimeLow === "application/x-bittorrent" ||
    /\.torrent(\?|#|$)/i.test(lowUrl) ||
    fnameLow.endsWith(".torrent");
  if (looksTorrent) {
    // kullanıcı az önce 'Hayır' dedi -> tarayıcı kendi indirmesine bırakılır (döngü yok)
    const declineTs = torrentDeclineUrls.get(url) || 0;
    if (Date.now() < declineTs) return { intercept: false };
    return { intercept: true, url, referer, forced: forced, torrent: true };
  }

  // Resmi IDM eklentisi bağlıysa bile:
  // 1) Anında çerez/başlık zenginleştirmesini köprüye göndeririz,
  // 2) Eğer site HttpOnly/Cloudflare/Authorization gerektiriyorsa (örn. arena.ai), resmi eklenti
  //    çerez gönderemediği için indirmeyi doğrudan biz devralırız (daemon çift pencereyi engeller!).
  if (!forced && cachedState.official_extension_connected && !needsRichAuthTakeover) {
    getCookiesHeader(url, referer).then((cookies) => {
      if (!cookies && !Object.keys(extraHdrs).length) return;
      callBridge("/api/auth-context", "POST", {
        url,
        cookies,
        referer,
        userAgent: navigator.userAgent,
        extraHeaders: extraHdrs
      });
    }).catch(() => {});
    return { intercept: false };
  }

  const ext = extractExtension(url, item.filename || "");
  const allowedSet = new Set((cachedState.file_extensions || []).map((e) => e.toUpperCase()));
  const mime = (item.mime || "").toLowerCase().split(";")[0].trim();
  const isBinaryMime = BINARY_MIMES.has(mime);

  if (!forced && !allowedSet.has(ext) && !isBinaryMime && !needsRichAuthTakeover) {
    return { intercept: false };
  }
  return { intercept: true, url, referer, forced };
}

function purgeBrowserDownload(downloadId, alreadyOwned = false) {
  if (extensionDisabled && !alreadyOwned) return;
  try {
    extApi.downloads.cancel(downloadId, () => {
      void extApi.runtime.lastError;
      if (extApi.downloads.removeFile) {
        try {
          extApi.downloads.removeFile(downloadId, () => { void extApi.runtime.lastError; });
        } catch (_e) {}
      }
      extApi.downloads.erase({ id: downloadId }, () => {
        void extApi.runtime.lastError;
      });
    });
  } catch (_e) {}
}

// Ek Kanca 1: Chromium dosya adını diske yazmaya hazırlanırken (7-Zip gibi küçük dosyaları bile yakalar!)
if (extApi.downloads && extApi.downloads.onDeterminingFilename) {
  try {
    extApi.downloads.onDeterminingFilename.addListener((item, suggest) => {
      if (extensionDisabled) { suggest(); return; }
      if (interceptedDownloadIds.has(item.id)) {
        suggest();
        return;
      }
      const check = evaluateInterceptSync(item);
      if (check.intercept && cachedState.online && cachedState.idm_installed) {
        interceptedDownloadIds.add(item.id);
        try { extApi.downloads.pause(item.id, () => { void extApi.runtime.lastError; }); } catch (_e) {}
        suggest();
        // v3.14.2: içerik-tipi torrent -> DOSYA olarak değil onay penceresiyle
        if (check.torrent) {
          dispatchTorrentPopup(item, check);
          return;
        }
        dispatchInterceptedToIdm(item, check);
        return;
      }
      suggest();
    });
  } catch (_e) {}
}

async function dispatchInterceptedToIdm(item, check) {
  if (extensionDisabled) {
    try { extApi.downloads.resume(item.id, () => { void extApi.runtime.lastError; }); } catch (_e) {}
    return;
  }
  if (processedDownloadIds.has(item.id)) return;
  processedDownloadIds.add(item.id);
  setTimeout(() => {
    processedDownloadIds.delete(item.id);
    interceptedDownloadIds.delete(item.id);
  }, 30000);

  const cookies = await getCookiesHeader(check.url, check.referer);
  if (extensionDisabled) {
    try { extApi.downloads.resume(item.id, () => { void extApi.runtime.lastError; }); } catch (_e) {}
    return;
  }
  const extraHeaders = getCachedExtraHeaders(check.url);
  let origin = "";
  try {
    if (check.referer) origin = new URL(check.referer).origin;
  } catch (_e) {}

  const res = await callBridge(
    "/api/download",
    "POST",
    {
      url: check.url,
      referer: check.referer,
      origin,
      cookies,
      extraHeaders,
      userAgent: navigator.userAgent,
      filename: item.filename ? item.filename.split(/[/\\]/).pop() : "",
      force: check.forced,
      source: "companion-hook"
    },
    "download"
  );

  if (res && res.ok && res.takeover !== false) {
    // IDM devraldı -> tarayıcı indirmesini ve varsa inmiş parçayı tamamen temizle!
    purgeBrowserDownload(item.id, true);
  } else {
    // Köprü devralmadıysa veya kapalıysa tarayıcı indirmesini devam ettir
    interceptedDownloadIds.delete(item.id);
    try {
      extApi.downloads.resume(item.id, () => {
        // Resume the original item: do not replay expired/authenticated/object URLs.
        void extApi.runtime.lastError;
      });
    } catch (_e) {}
  }
}

// v3.14.2: İÇERİK-TİPİ TORRENT POPUP'U — indirme torrent kokuyorsa (mime/dosya adı),
// DOSYA olarak IDM'ye gitmez; başlatan sekmede 'Torrent İndirme Onayı' penceresi açılır.
// Sekme bulunamazsa / içerik betiği yoksa eski dosya akışına geri düşer.
async function dispatchTorrentPopup(item, check) {
  if (extensionDisabled) { try { extApi.downloads.resume(item.id, () => {}); } catch (_e) {} return; }
  purgeBrowserDownload(item.id);
  if (processedDownloadIds.has(item.id)) return;
  processedDownloadIds.add(item.id);
  setTimeout(() => {
    processedDownloadIds.delete(item.id);
    interceptedDownloadIds.delete(item.id);
  }, 30000);

  const url = check.url || item.finalUrl || item.url || "";
  const tab = await findTabForDownload(check.referer);
  if (tab && tab.id >= 0) {
    try {
      const resp = await new Promise((resolve) => {
        try {
          extApi.tabs.sendMessage(
            tab.id,
            { type: "IDM_SHOW_TORRENT_POPUP", url, name: (item.filename || "").split(/[/\\]/).pop() },
            (r) => {
              void extApi.runtime.lastError;
              resolve(r);
            }
          );
        } catch (_syncErr) {
          resolve(null);
        }
      });
      if (resp && resp.ok) return; // popup sekmede açıldı
    } catch (_e) {}
  }
  // İçerik betiği yok (mağaza sayfası vb.) -> eski davranış: .torrent dosyasını IDM'ye ver
  processedDownloadIds.delete(item.id);
  dispatchInterceptedToIdm(item, check);
}

// İndirmeyi başlatan sekmeyi bul: önce referer origin eşleşmesi, sonra aktif sekme
async function findTabForDownload(referer) {
  try {
    let origin = "";
    try { if (referer) origin = new URL(referer).origin; } catch (_e) {}
    if (origin) {
      const all = await extApi.tabs.query({});
      for (const t of all) {
        try {
          if (t.active && t.url && new URL(t.url).origin === origin) return t;
        } catch (_e) {}
      }
      for (const t of all) {
        try {
          if (t.url && new URL(t.url).origin === origin) return t;
        } catch (_e) {}
      }
    }
    const act = await extApi.tabs.query({ active: true, lastFocusedWindow: true });
    if (act && act.length) return act[0];
  } catch (_e) {}
  return null;
}

extApi.downloads.onCreated.addListener((item) => {
  if (!item || processedDownloadIds.has(item.id)) return;

  const check = evaluateInterceptSync(item);
  if (!check.intercept) return;

  // 0. MİLİSANIYEDE SENKRON MÜDAHALE (HİÇ await YOK!):
  // Tarayıcının küçük dosyaları (örn. 7-Zip 1.5MB) arkada indirip bitirmesini anında durdurur!
  interceptedDownloadIds.add(item.id);
  try { extApi.downloads.pause(item.id, () => { void extApi.runtime.lastError; }); } catch (_e) {}

  // v3.14.2: içerik-tipi torrent -> DOSYA olarak değil onay penceresiyle
  if (check.torrent) {
    dispatchTorrentPopup(item, check);
    return;
  }
  dispatchInterceptedToIdm(item, check);
});

// ---------------------------------------------------------------------------
// 3. Sağ Tık Menüsü (Context Menus)
// ---------------------------------------------------------------------------
function setupContextMenus() {
  try {
    extApi.contextMenus.removeAll(() => {
      void extApi.runtime.lastError;
      extApi.contextMenus.create({
        id: "idm-dl-link",
        title: "IDM ile İndir",
        contexts: ["link", "video", "audio"]
      });
      extApi.contextMenus.create({
        id: "idm-dl-page-video",
        title: "Bu Sayfadaki Videoyu IDM ile İndir",
        contexts: ["page", "frame"]
      });
      extApi.contextMenus.create({
        id: "idm-toggle-enabled",
        title: "IDM-Linux Eklentisini Pasifleştir",
        contexts: ["action"]
      });
      extApi.contextMenus.create({
        id: "idm-dl-all-links",
        title: "Sayfadaki Tüm Bağlantıları IDM ile İndir...",
        contexts: ["page"]
      });
    });
  } catch (_e) {}
}

extApi.runtime.onInstalled.addListener(() => {
  setupContextMenus();
  refreshDaemonState();
});
setupContextMenus();
refreshDaemonState();

extApi.contextMenus.onClicked.addListener(async (info, tab) => {
  const pageUrl = (tab && tab.url) || info.pageUrl || "";
  if (info.menuItemId === "idm-dl-link") {
    const targetUrl = info.linkUrl || info.srcUrl || "";
    const lowTarget = targetUrl.toLowerCase();
    if (!targetUrl.startsWith("http") && !lowTarget.startsWith("magnet:?")) return;
    const cookies = targetUrl.startsWith("http") ? await getCookiesHeader(targetUrl) : "";
    await callBridge(
      "/api/download",
      "POST",
      {
        url: targetUrl,
        referer: pageUrl,
        cookies,
        userAgent: navigator.userAgent,
        force: true,
        source: "context-menu"
      },
      "download"
    );
  } else if (info.menuItemId === "idm-dl-page-video" && tab && tab.id >= 0) {
    extApi.tabs.sendMessage(tab.id, { type: "IDM_OPEN_VIDEO_PICKER" }, () => {
      void extApi.runtime.lastError;
    });
  } else if (info.menuItemId === "idm-dl-all-links" && tab && tab.id >= 0) {
    extApi.tabs.sendMessage(tab.id, { type: "IDM_OPEN_BATCH_MODAL" }, () => {
      void extApi.runtime.lastError;
    });
  }
});

// v2.9.4: sekme içi gezinmede eski sayfanın kaynaklarını SIFIRLA (bar karışmasın)
try {
  chrome.webNavigation.onBeforeNavigate.addListener((d) => {
    if (d.frameId === 0) tabStreams.delete(d.tabId);
  });
  chrome.webNavigation.onHistoryStateUpdated.addListener((d) => {
    if (d.frameId === 0) tabStreams.delete(d.tabId);
  });
} catch (_e) {}

// ---------------------------------------------------------------------------
// 4. Content Script & Popup Mesaj Yöneticisi
// ---------------------------------------------------------------------------
extApi.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return false;
  const tabId = sender && sender.tab ? sender.tab.id : msg.tabId;
  const topTabUrl = (sender && sender.tab && sender.tab.url) || "";
  const topTabTitle = (sender && sender.tab && sender.tab.title) || "";

  (async () => {
    if (extensionDisabled && !["IDM_POPUP_STATUS", "IDM_GET_TAB_INFO", "IDM_GET_STATE", "IDM_UPDATE_CONFIG"].includes(msg.type)) {
      sendResponse({ ok: false, takeover: false, disabled: true }); return;
    }

    // v3.10.0: OYNATICIYA GÖMÜLÜ ALTYAZI — daemon kasasına yaz, yerel URL'yi akış
    // listesine ekle (böylece bar "📝 Türkçe Altyazı" olarak listeler ve IDM indirir).
    if (msg.type === "IDM_SUBTITLE_TEXT") {
      const vtt = String(msg.vtt || "");
      if (vtt.length < 40) { sendResponse({ ok: false }); return; }
      const label = String(msg.label || "altyazı").slice(0, 80);
      const res = await callBridge("/api/subtitle/register", "POST", {
        vtt,
        label,
        url: msg.pageUrl || "",
      }, null);
      if (res && res.ok && res.url && tabId >= 0) {
        if (!tabStreams.has(tabId)) tabStreams.set(tabId, new Map());
        const streamMap = tabStreams.get(tabId);
        streamMap.set(res.url, {
          url: res.url,
          mime: "text/vtt",
          isHls: false,
          manifestText: "",
          size: res.size || null,
          referer: msg.pageUrl || "",
          origin: "",
          sub_label: label,
          original_url: msg.sourceUrl || "",
          detectedAt: Date.now()
        });
        while (streamMap.size > 300) streamMap.delete(streamMap.keys().next().value);
        try {
          extApi.tabs.sendMessage(tabId, { type: "IDM_MEDIA_UPDATED", count: streamMap.size }, () => {
            void extApi.runtime.lastError;
          });
        } catch (_e) {}
        sendResponse({ ok: true, url: res.url });
      } else {
        sendResponse(res || { ok: false });
      }
      return;
    }

    if (msg.type === "IDM_REGISTER_CAPTURED_STREAM" || msg.type === "IDM_REGISTER_CAPTURED_STREAMS") {
      const st0 = await chrome.storage.local.get(["extDisabled"]);
      if (st0.extDisabled) { sendResponse({ ok: false, disabled: true }); return; }
      if (tabId >= 0) {
        if (!tabStreams.has(tabId)) {
          tabStreams.set(tabId, new Map());
        }
        const streamMap = tabStreams.get(tabId);
        const items = Array.isArray(msg.streams) ? msg.streams : (msg.stream ? [msg.stream] : []);
        for (const s of items) {
          if (!s || !s.url) continue;
          streamMap.set(s.url, {
            url: s.url,
            mime: s.mime || "",
            isHls: Boolean(s.isHls),
            manifestText: (s.manifestText || "").slice(0, 8192), // v2.9.0 bellek koruması
            size: s.size || null,
            referer: s.referer || "",
            origin: s.origin || "",
            user_agent: s.user_agent || s.userAgent || navigator.userAgent,
            sub_label: s.sub_label || "", // v3.2.1: altyazı adı bar'a taşınır
            detectedAt: Date.now()
          });
        }
        // v2.8.7 bellek koruması: sekme başına yakalama haritası en fazla 300 kayıt (en eski düşer)
        while (streamMap.size > 300) streamMap.delete(streamMap.keys().next().value);
        try {
          extApi.tabs.sendMessage(
            tabId,
            { type: "IDM_MEDIA_UPDATED", count: streamMap.size },
            () => { void extApi.runtime.lastError; }
          );
        } catch (_e) {}
      }
      sendResponse({ ok: true });
      return;
    }

    if (msg.type === "IDM_SET_MODIFIER") {
      if (msg.altKey) bypassCaptureUntil = Date.now() + 3500;
      if (msg.insertKey) forceCaptureUntil = Date.now() + 4500;
      sendResponse({ ok: true });
      return;
    }

    if (msg.type === "IDM_GET_TAB_INFO") {
      if (!cachedState.online) {
        await refreshDaemonState();
      }
      const sMap = tabId >= 0 && tabStreams.has(tabId) ? tabStreams.get(tabId) : new Map();
      const host = msg.hostname || "";
      const excluded = isDomainExcluded(`https://${host}/`, topTabUrl);
      sendResponse({
        ok: true,
        videoBarEnabled: !extensionDisabled && cachedState.video_bar_enabled && !excluded,
        streamCount: sMap.size,
        streams: Array.from(sMap.values()),
        tabTitle: topTabTitle,
        state: cachedState
      });
      return;
    }

    if (msg.type === "IDM_ABYSS_META") {
      try {
        await callBridge("/api/abyss/meta", "POST", { payload: msg.payload || "" }, "abyss_meta");
      } catch (_e) {}
      sendResponse({ ok: true });
      return;
    }

    if (msg.type === "IDM_PROBE_VIDEO") {
      const frameUrl = msg.pageUrl || topTabUrl || "";
      // Üst sekme URL'si YouTube/Twitch ise onu kullan; iframe oynatıcıysa yakalanan akışlarla birleştir
      const effectivePageUrl = topTabUrl && topTabUrl.startsWith("http") ? topTabUrl : frameUrl;
      const sMap = tabId >= 0 && tabStreams.has(tabId) ? tabStreams.get(tabId) : new Map();
      const extraStreams = Array.isArray(msg.domStreams) ? msg.domStreams : [];
      const mergedStreams = [...Array.from(sMap.values()), ...extraStreams];

      const cookieUrls = [effectivePageUrl, frameUrl];
      for (const st of mergedStreams.slice(0, 5)) {
        if (st && st.url) cookieUrls.push(st.url);
      }
      // Prefer sources already captured by the browser. No challenge-bypass retries.
      const hasBiliSources = mergedStreams.some((st) => { try { return /(^|\.)hdslb\.com$|(^|\.)bilivideo\.com$/.test(new URL(st.url).hostname); } catch (_e) { return false; } });
      let isBiliPage = false;
      try { isBiliPage = /(^|\.)bilibili\.com$/.test(new URL(effectivePageUrl).hostname); } catch (_e) {}
      if (!hasBiliSources && isBiliPage) {
        try {
          const bm = effectivePageUrl.match(/\/video\/(BV[0-9A-Za-z]+)/);
          if (bm) {
            let cid = msg.biliCid || "";
            if (!cid) {
              const view = await fetchJsonBounded(`https://api.bilibili.com/x/web-interface/view?bvid=${bm[1]}`);
              const part = Math.max(1, Number(new URL(effectivePageUrl).searchParams.get("p")) || 1);
              const pages = view && view.data && view.data.pages;
              cid = String((pages && pages[part - 1] && pages[part - 1].cid) || (part === 1 && view && view.data && view.data.cid) || "");
            }
            if (cid) {
              const pl = await fetchJsonBounded(`https://api.bilibili.com/x/player/playurl?bvid=${bm[1]}&cid=${cid}&fnval=16&fnver=0&fourk=1`);
              const data = pl && pl.code === 0 && pl.data;
              const dash = data && data.dash;
              if (dash) {
                (dash.video || []).slice(0, 6).forEach((v) => mergedStreams.push({ url: v.baseUrl || v.base_url || "", mime: v.mimeType || "video/mp4", referer: "https://www.bilibili.com/", isHls: false }));
                (dash.audio || []).slice(0, 2).forEach((v) => mergedStreams.push({ url: v.baseUrl || v.base_url || "", mime: v.mimeType || "audio/mp4", referer: "https://www.bilibili.com/", isHls: false }));
              } else if (data && data.durl) {
                data.durl.slice(0, 3).forEach((v) => mergedStreams.push({ url: v.url, mime: "video/mp4", referer: "https://www.bilibili.com/", isHls: false }));
              }
            }
          }
        } catch (_e) {}
      }

      const cookies = await getMergedCookies(cookieUrls);
      await Promise.all(mergedStreams.slice(-300).map(async st => {
        if (!st || !/^https?:/.test(st.url || "") || !(/^text\//i.test(st.mime || "") || /timedtext|\.(vtt|srt|ass|ssa|ttml|dfxp|smi)(?:[?#]|$)/i.test(st.url))) return;
        st.cookie_header = await queryCookiesPromise({url: st.url});
        st.user_agent = st.user_agent || navigator.userAgent;
      }));

      let res = await callBridge(
        "/api/video/probe",
        "POST",
        {
          pageUrl: effectivePageUrl,
          streams: mergedStreams,
          cookies,
          referer: frameUrl || effectivePageUrl,
          userAgent: navigator.userAgent,
          useYtdlp: true,
          biliCid: msg.biliCid || "",
          forceRefresh: Boolean(msg.forceRefresh)
        },
        "probe_video"
      );
      if ((!res || !res.ok) && topTabUrl) {
        // v2.9.7: köprü hiç yoksa uyandırıp bir kez daha probe et (bar boş kalmasın)
        const woke = await wakeDaemon(true);
        if (woke) {
          await new Promise((r) => setTimeout(r, 1500));
          const res2 = await callBridge(
            "/api/video/probe",
            "POST",
            {
              pageUrl: effectivePageUrl,
              streams: mergedStreams,
              cookies,
              referer: frameUrl || effectivePageUrl,
              userAgent: navigator.userAgent,
              useYtdlp: true,
              biliCid: msg.biliCid || "",
              forceRefresh: Boolean(msg.forceRefresh)
            },
            "probe_video"
          );
          if (res2) res = res2;
        }
      }
      if (res && !res.title && topTabTitle) {
        res.title = topTabTitle;
      }
      sendResponse(res);
      return;
    }

    if (msg.type === "IDM_DOWNLOAD_VIDEO") {
      const frameUrl = msg.pageUrl || "";
      const rawTitle = (msg.title || "").trim();
      const bestTitle = (!rawTitle || rawTitle.toLowerCase() === "video") && topTabTitle
        ? topTabTitle
        : (rawTitle || "video");

      const cookies = msg.delivery === "subs" && msg.directUrl
        ? await queryCookiesPromise({url:msg.directUrl})
        : await getMergedCookies([
        msg.directUrl,
        msg.sourceUrl,
        msg.streamReferer,
        frameUrl,
        topTabUrl
      ]);

      const res = await callBridge(
        "/api/video/download",
        "POST",
        {
          pageUrl: topTabUrl || frameUrl,
          title: bestTitle,
          ext: msg.ext || "mp4",
          resolution: msg.resolution || "",
          delivery: msg.delivery || "direct",
          directUrl: msg.directUrl || "",
          sourceUrl: msg.sourceUrl || topTabUrl || frameUrl,
          formatSelector: msg.formatSelector || "",
          abyssSlug: msg.abyssSlug || "",
          abyssLabel: msg.abyssLabel || "",
          subLang: msg.subLang || "",
          muxVideoUrl: msg.muxVideoUrl || "",
          muxAudioUrl: msg.muxAudioUrl || "",
          muxVideoHeaders: msg.muxVideoHeaders || {},
          muxAudioHeaders: msg.muxAudioHeaders || {},
          manifestText: msg.manifestText || "",
          isHls: Boolean(msg.isHls),
          streamReferer: msg.streamReferer || frameUrl || topTabUrl,
          streamOrigin: msg.streamOrigin || "",
          streamUserAgent: msg.streamUserAgent || navigator.userAgent,
          filesize: msg.filesize || null,
          filesizeExact: Boolean(msg.filesizeExact),
          segmentUrls: msg.segmentUrls || [],
          manifestUrl: msg.manifestUrl || "",
          audioSegmentUrls: msg.audioSegmentUrls || [],
          hlsMode: msg.hlsMode || "vod",
          customName: msg.customName || "",
          cookies,
          referer: msg.streamReferer || frameUrl || topTabUrl,
          userAgent: msg.streamUserAgent || navigator.userAgent
        },
        "download_video"
      );
      sendResponse(res);
      return;
    }

    if (msg.type === "IDM_DIRECT_DOWNLOAD") {
      const u = (msg.url || "").trim();
      const cookies = u.startsWith("http") ? await getCookiesHeader(u) : "";
      const res = await callBridge(
        "/api/download",
        "POST",
        {
          url: u,
          referer: msg.referer || topTabUrl || "",
          cookies,
          userAgent: navigator.userAgent,
          filename: msg.filename || "",
          force: Boolean(msg.force !== false),
          source: msg.source || "popup"
        },
        "download"
      );
      sendResponse(res);
      return;
    }

    if (msg.type === "IDM_BATCH_DOWNLOAD") {
      const pageUrl = msg.referer || topTabUrl || "";
      const cookies = pageUrl ? await getCookiesHeader(pageUrl) : "";
      const res = await callBridge(
        "/api/download-batch",
        "POST",
        {
          links: msg.links || [],
          referer: pageUrl,
          cookies,
          userAgent: navigator.userAgent
        },
        "download_batch"
      );
      sendResponse(res);
      return;
    }

    if (msg.type === "IDM_POPUP_STATUS") {
      const st = await refreshDaemonState();
      sendResponse({ ok: true, state: Object.assign({}, st, { extension_disabled: extensionDisabled, capture_downloads: !extensionDisabled && st.capture_downloads !== false }) });
      return;
    }

    if (msg.type === "IDM_UPDATE_CONFIG") {
      if (msg.config && typeof msg.config.capture_downloads === "boolean") {
        setCaptureDisabled(!msg.config.capture_downloads);
        await new Promise((resolve) => extApi.storage.local.set({ extDisabled: extensionDisabled }, resolve));
      }
      const res = await callBridge(
        "/api/config",
        "POST",
        msg.config || {},
        extensionDisabled ? null : "update_config"
      );
      await refreshDaemonState();
      sendResponse(res);
      return;
    }

    if (msg.type === "IDM_BLOB_TRANSFER") {
      if (!cachedState.online) await refreshDaemonState();
      if (extensionDisabled || !cachedState.online || !cachedState.idm_installed || !cachedState.capture_downloads || isDomainExcluded(msg.pageUrl || topTabUrl, topTabUrl)) {
        sendResponse({ ok: false, takeover: false }); return;
      }
      const actions = new Set(["begin", "chunk", "finish", "cancel"]);
      if (!actions.has(msg.action)) { sendResponse({ ok: false }); return; }
      const owner = `${tabId}:${sender.frameId || 0}`;
      if (msg.action !== "begin" && blobUploadOwners.get(msg.transferId) !== owner) {
        sendResponse({ ok: false, error: "Unknown blob owner" }); return;
      }
      const result = await callBridge(`/api/blob-transfer/${msg.action}`, "POST", {
        transferId: msg.transferId, filename: msg.filename, mimeType: msg.mimeType,
        size: msg.size, offset: msg.offset, dataBase64: msg.dataBase64
      });
      if (msg.action === "begin" && result && result.ok) blobUploadOwners.set(result.transferId, owner);
      if (msg.action === "finish" || msg.action === "cancel") blobUploadOwners.delete(msg.transferId);
      sendResponse(result || { ok: false }); return;
    }

    if (msg.type === "IDM_BLOB_DOWNLOAD") {
      if (!cachedState.online) {
        await refreshDaemonState();
      }
      if (
        !cachedState.online ||
        !cachedState.idm_installed ||
        !cachedState.capture_downloads ||
        Date.now() < bypassCaptureUntil ||
        isDomainExcluded(msg.pageUrl || topTabUrl, topTabUrl)
      ) {
        sendResponse({ ok: false, takeover: false });
        return;
      }
      const res = await callBridge(
        "/api/blob-upload",
        "POST",
        {
          dataBase64: msg.dataBase64 || "",
          filename: msg.filename || "download.bin",
          mimeType: msg.mimeType || "application/octet-stream"
        },
        null
      );
      sendResponse(res);
      return;
    }

    if (msg.type === "IDM_OPEN_APP") {
      const res = await callBridge("/api/open-idm", "POST", {}, "open_idm");
      sendResponse(res);
      return;
    }

    // v3.7.0: TORRENT ÖN-KONTROLÜ — popup açılırken aria2c kurulu mu / sürümü ne?
    if (msg.type === "IDM_TORRENT_PREFLIGHT") {
      const res = await callBridge("/api/torrent/preflight", "GET", null, null);
      if (res && typeof res === "object") {
        sendResponse(res);
      } else {
        sendResponse({ ok: false, installed: false, version: "", hint: "" });
      }
      return;
    }

    // v3.7.0: eD2K (eMule) motor durumu ön-kontrolü
    if (msg.type === "IDM_ED2K_PREFLIGHT") {
      const res = await callBridge("/api/ed2k/status", "GET", null, null);
      if (res && typeof res === "object") {
        sendResponse(res);
      } else {
        sendResponse({ ok: false, backend: "none", running: false, install_hint: "" });
      }
      return;
    }

    // v3.7.0: eD2K motor TEK TIK kurulum (arka plan başlar; durum /api/ed2k/status'tan yoklanır)
    if (msg.type === "IDM_ED2K_INSTALL") {
      const res = await callBridge("/api/ed2k/install", "POST", {}, null);
      sendResponse(res || { ok: false, message: "Köprüe ulaşılamadı — paneli açıp tekrar deneyin." });
      return;
    }

    // v3.7.0: eD2K bağlantısını motoruna gönder (mldonkey/aMule)
    if (msg.type === "IDM_ED2K_SEND") {
      const href = String(msg.href || "").trim();
      if (!/^ed2k:\/\/\|file\|/i.test(href)) {
        sendResponse({ ok: false, message: "Geçersiz ed2k bağlantısı." });
        return;
      }
      const payload = { link: href, source: "ext-popup-ed2k", referer: msg.referer || topTabUrl || "" };
      const res = await callBridge("/api/ed2k/download", "POST", payload, null);
      if (res && typeof res === "object") {
        sendResponse(res);
        return;
      }
      // köprü uykudaydı — callBridge zaten uyandırdı; 2 sn bekle + son bir şans
      await new Promise((r) => setTimeout(r, 2000));
      const res2 = await callBridge("/api/ed2k/download", "POST", payload, null);
      sendResponse(res2 || { ok: false, offline: true, message: "" });
      return;
    }

    // v3.6.0: TORRENT / MAGNET GÖNDERİMİ — İÇERİK BETİĞİNDEN DEĞİL, BURADAN (arka plan
    // servisi) yapılır. İçerik betiği sayfa kaynağıyla (örn. https://piratebay.org) POST
    // atacağı için CORS + 'Untrusted origin' kalkanına takılır ve kullanıcının ekranında
    // 'Torrent başlatılamadı — IDM Linux köprüsüne ulaşılamadı' hatası görülür. Arka plan
    // servisi host_permissions(<all_urls>) ile yerel köprüye serbest erişir — SORUN BİTER.
    // .torrent dosyası da artık köprü TARAFINDAN indirilir (sayfa CSP/CORS engeline takılmaz).
    if (msg.type === "IDM_TORRENT_SEND") {
      const href = String(msg.href || "").trim();
      const kind = String(msg.kind || "").trim();
      if (!href || (!href.startsWith("magnet:") && !/^https?:\/\//i.test(href))) {
        sendResponse({ ok: false, message: "Geçersiz torrent/magnet bağlantısı." });
        return;
      }
      let payload;
      if (kind === "magnet") {
        payload = { magnet: href, source: "ext-popup-magnet" };
      } else {
        let cookies = "";
        try { cookies = await getCookiesHeader(href); } catch (_e) {}
        payload = {
          url: href,
          referer: msg.referer || topTabUrl || "",
          cookies,
          userAgent: navigator.userAgent,
          source: "ext-popup-torrent"
        };
      }
      const res = await callBridge("/api/torrent/download", "POST", payload, "torrent_download");
      const okFlag = Boolean(res && res.ok);
      const respPayload = Object.assign({}, res || {});
      if (!res) {
        // v3.7.0: köprü GERÇEKTEN erişilemez — popup doğru mesajı göstersin
        respPayload.ok = false;
        respPayload.offline = true;
      }
      if (!okFlag && respPayload.offline) {
        // callBridge köprüyü uyandırmayı denedi; son bir şans: 2 sn bekle + tekrar
        await new Promise((r) => setTimeout(r, 2000));
        const res2 = await callBridge("/api/torrent/download", "POST", payload, "torrent_download");
        if (res2 && res2.ok) {
          sendResponse(Object.assign({}, res2, { ok: true }));
          return;
        }
      }
      sendResponse(respPayload);
      return;
    }

    // v3.14.2: popup 'Dosyayı İndir' — torrent İÇERİĞİNİ değil .torrent DOSYASINI
    // normal IDM indirme akışına (/api/download) verir; IDM kendi penceresiyle indirir
    if (msg.type === "IDM_TORRENT_FILE_DOWNLOAD") {
      const href = String(msg.href || "").trim();
      if (!/^https?:\/\//i.test(href)) {
        sendResponse({ ok: false, message: "Geçersiz .torrent bağlantısı." });
        return;
      }
      let cookies = "";
      try { cookies = await getCookiesHeader(href); } catch (_e) {}
      let origin = "";
      try { if (msg.referer) origin = new URL(msg.referer).origin; } catch (_e) {}
      const filePayload = {
        url: href,
        referer: msg.referer || topTabUrl || "",
        origin,
        cookies,
        userAgent: navigator.userAgent,
        force: true,
        source: "ext-torrent-file"
      };
      let fileRes = await callBridge("/api/download", "POST", filePayload, "download");
      if (!fileRes) {
        // köprü uykudaydı — callBridge uyandırdı; 2 sn bekle + son bir şans
        await new Promise((r) => setTimeout(r, 2000));
        fileRes = await callBridge("/api/download", "POST", filePayload, "download");
      }
      if (fileRes && typeof fileRes === "object") {
        sendResponse(fileRes);
      } else {
        sendResponse({ ok: false, offline: true, message: "" });
      }
      return;
    }

    // v3.14.2: popup 'Hayır' — bu URL 10 sn boyunca torrent popup'ına düşmesin
    // (kullanıcı tarayıcı indirmesini seçti; döngü koruması)
    if (msg.type === "IDM_TORRENT_DECLINE") {
      const declineUrl = String(msg.url || "").trim();
      if (declineUrl) {
        torrentDeclineUrls.set(declineUrl, Date.now() + 10000);
        if (torrentDeclineUrls.size > 300) {
          const nowMs = Date.now();
          for (const [k, ts] of torrentDeclineUrls) {
            if (ts < nowMs) torrentDeclineUrls.delete(k);
          }
        }
      }
      sendResponse({ ok: true });
      return;
    }

    sendResponse({ ok: false });
  })().catch((asyncErr) => {
    // v3.6.0 KRİTİK: async handler içindeki HERHANGİ bir istisna (çerez API'si, fetch,
    // JSON parse...) sendResponse'un HİÇ çağrılmamasına ve içerik betiği promise'inin
    // SONSUZA dek askıda kalmasına yol açıyordu -> bar 'Kaliteler hazırlanıyor...' da
    // sonsuza dek takılı kalıyordu (kullanıcı raporu). Artık her koşulda yanıt döner.
    try {
      sendResponse({ ok: false, error: String(asyncErr && asyncErr.message ? asyncErr.message : asyncErr) });
    } catch (_e) {}
  });

  return true;
});

// v2.8.6: daemon'onay kuyruğunu poll'la -> sayfada confirm() -> sonucu bildir
const _idmConfirmSeen = new Set();
setInterval(async () => {
  if (extensionDisabled) return;
  try {
    const cfg = await chrome.storage.local.get(["httpPort"]);
    const port = cfg.httpPort || 17802;
    const res = await fetch(`http://127.0.0.1:${port}/api/confirm/pending`, { headers: { Origin: `http://127.0.0.1:${port}` } });
    const data = await res.json();
    for (const p of (data.pending || [])) {
      if (_idmConfirmSeen.has(p.id)) continue;
      _idmConfirmSeen.add(p.id);
      if (_idmConfirmSeen.size > 200) _idmConfirmSeen.clear();
      const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
      let ok = false;
      try {
        const resp = await chrome.tabs.sendMessage(tabs[0].id, { type: "IDM_CONFIRM_UI", message: p.message });
        ok = Boolean(resp && resp.ok);
      } catch (e) {
        ok = false;
      }
      await fetch(`http://127.0.0.1:${port}/api/confirm-result`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${port}` },
        body: JSON.stringify({ id: p.id, ok })
      });
      if (ok && p.kind === "magnet") {
        // onaylandıysa indirmeyi daemon zaten başlatır; kullanıcıya küçük bildirim
        try { chrome.notifications.create({ type: "basic", iconUrl: "icons/icon128.png", title: "IDM-Linux", message: "Magnet indirmesi başlatıldı." }); } catch (e) {}
      }
    }
  } catch (e) {}
}, 3000);

// v2.8.8: IDM devraldıysa tarayıcının KENDİ indirme penceresi ASLA görünmesin
const _takeoverUrls = new Set();
let _gofileTakeoverUntil = 0;
chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg && msg.type === "IDM_TAKEOVER_URL") {
    if (extensionDisabled) { sendResponse({ ok: false, disabled: true }); return false; }
    if (msg.url) {
      _takeoverUrls.add(msg.url);
      if (_takeoverUrls.size > 300) _takeoverUrls.clear();
    }
    if (msg.gofileWindowMs) _gofileTakeoverUntil = Date.now() + msg.gofileWindowMs;
    sendResponse({ ok: true });
    return true;
  }
  return false;
});
try {
  chrome.downloads.onCreated.addListener((dl) => {
    const u = dl && dl.url ? dl.url : "";
    if (extensionDisabled) return;
    const inTakeover = _takeoverUrls.has(u);
    const gofileWin = Date.now() < _gofileTakeoverUntil && /gofile\.io\/(download|contents)\//i.test(u);
    if (inTakeover || gofileWin) {
      try { chrome.downloads.cancel(dl.id, () => { void chrome.runtime.lastError; }); } catch (e) {}
      try { chrome.downloads.erase({ id: dl.id }, () => { void chrome.runtime.lastError; }); } catch (e) {}
    }
  });
} catch (e) {}

// v2.8.8: arena.ai vb. HttpOnly/CF korumalı dosyaları BIZZAT TARAYICI çeker, daemon'a besler
setInterval(async () => {
  if (extensionDisabled) return;
  try {
    const cfg = await chrome.storage.local.get(["httpPort"]);
    const port = cfg.httpPort || 17802;
    const res = await fetch(`http://127.0.0.1:${port}/api/assist/pending`, { headers: { Origin: `http://127.0.0.1:${port}` } });
    const data = await res.json();
    for (const a of (data.pending || [])) {
      if (extensionDisabled) break;
      // v2.9.1: ÖNCE aynı origin'li sekmede content-script'e çektir (CORS duvarını aşar)
      try {
        const host = new URL(a.url).hostname;
        const tabs = await chrome.tabs.query({ url: `*://${host}/*` });
        if (tabs && tabs.length) {
          try {
            const resp = await chrome.tabs.sendMessage(tabs[0].id, { type: "IDM_ASSIST_FETCH", url: a.url, id: a.id, httpPort: port });
            if (resp && resp.ok) continue;
          } catch (e) {}
        }
      } catch (e) {}
      try {
        const r = await fetch(a.url, { credentials: "include", redirect: "follow" });
        if (!r.ok || !r.body) {
          await fetch(`http://127.0.0.1:${port}/api/assist/done`, { method: "POST", headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${port}` }, body: JSON.stringify({ id: a.id, ok: false }) });
          continue;
        }
        const reader = r.body.getReader();
        let buf = new Uint8Array(0);
        const post = async (bytes) => {
          let bin = "";
          for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
          await fetch(`http://127.0.0.1:${port}/api/assist/chunk`, { method: "POST", headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${port}` }, body: JSON.stringify({ id: a.id, b64: btoa(bin) }) });
        };
        for (;;) {
          if (extensionDisabled) { await reader.cancel(); throw new Error("Capture disabled"); }
          const { done, value } = await reader.read();
          if (done) break;
          const merged = new Uint8Array(buf.length + value.length);
          merged.set(buf); merged.set(value, buf.length);
          buf = merged;
          while (buf.length >= 393216) {
            await post(buf.subarray(0, 393216));
            buf = buf.subarray(393216);
          }
        }
        if (buf.length) await post(buf);
        await fetch(`http://127.0.0.1:${port}/api/assist/done`, { method: "POST", headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${port}` }, body: JSON.stringify({ id: a.id, ok: true }) });
      } catch (e) {
        try { await fetch(`http://127.0.0.1:${port}/api/assist/done`, { method: "POST", headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${port}` }, body: JSON.stringify({ id: a.id, ok: false }) }); } catch (e2) {}
      }
    }
  } catch (e) {}
}, 3000);

// v2.9.0: sağ tık menüsünden eklentiyi PASİF/AKTİF et
try {
  chrome.storage.local.get(["extDisabled"], (r) => {
    const dis = Boolean(r && r.extDisabled);
    try {
      chrome.contextMenus.update("idm-toggle-enabled", {
        title: dis ? "IDM-Linux Eklentisini Aktifleştir" : "IDM-Linux Eklentisini Pasifleştir"
      });
    } catch (e) {}
  });
  chrome.contextMenus.onClicked.addListener((info, tab) => {
    if (info.menuItemId !== "idm-toggle-enabled") return;
    chrome.storage.local.get(["extDisabled"], (r) => {
      const next = !Boolean(r && r.extDisabled);
      setCaptureDisabled(next);
      chrome.storage.local.set({ extDisabled: next }, async () => {
        try {
          const cfg2 = await chrome.storage.local.get(["httpPort"]);
          const port2 = cfg2.httpPort || 17802;
          await fetch(`http://127.0.0.1:${port2}/api/ext-state`, {
            method: "POST",
            headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${port2}` },
            body: JSON.stringify({ disabled: next })
          });
        } catch (e2) {}
        try {
          chrome.contextMenus.update("idm-toggle-enabled", {
            title: next ? "IDM-Linux Eklentisini Aktifleştir" : "IDM-Linux Eklentisini Pasifleştir"
          });
        } catch (e) {}
        try {
          chrome.notifications.create({
            type: "basic",
            iconUrl: "icons/icon128.png",
            title: "IDM-Linux",
            message: next ? "Eklenti PASİF — yakalama durdu." : "Eklenti AKTİF — yakalama sürüyor."
          });
        } catch (e) {}
      });
    });
  });
} catch (e) {}

// v2.9.2: DRM reddi gibi daemon hatalarını kullanıcıya bildir (sessiz 0 bayt yok)
try {
  chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
    if (msg && msg.type === "IDM_SHOW_ERROR" && msg.message) {
      try {
        chrome.notifications.create({
          type: "basic",
          iconUrl: "icons/icon128.png",
          title: "IDM-Linux",
          message: String(msg.message).slice(0, 300)
        });
      } catch (e) {}
      sendResponse({ ok: true });
      return true;
    }
    return false;
  });
} catch (e) {}
