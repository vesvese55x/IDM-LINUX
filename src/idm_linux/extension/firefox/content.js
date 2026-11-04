/* IDM Linux Hybrid Integration — Floating "Bu videoyu indir" Bar & Batch Grabber */
(function () {
  "use strict";

  if (window.__IDM_LINUX_INJECTED__) return;
  window.__IDM_LINUX_INJECTED__ = true;

  const extApi = typeof browser !== "undefined" ? browser : chrome;

  // Kurulum sonrası /welcome karşılama ve doğrulama sayfasında eklenti aktifliğini anında bildir!
  try {
    if (
      (location.hostname === "127.0.0.1" || location.hostname === "localhost") &&
      location.pathname === "/welcome"
    ) {
      const mfVer = (extApi.runtime.getManifest && extApi.runtime.getManifest().version) || "2.2.0";
      document.documentElement.dataset.idmLinuxExtVersion = mfVer;
      window.postMessage({ type: "IDM_LINUX_EXT_ALIVE", version: mfVer }, "*");
      setTimeout(() => {
        window.postMessage({ type: "IDM_LINUX_EXT_ALIVE", version: mfVer }, "*");
        extApi.runtime.sendMessage({ type: "IDM_POPUP_STATUS" }, () => { void extApi.runtime.lastError; });
      }, 250);
    }
  } catch (_e) {}

  let videoBarAllowed = true;
  let dismissedForPage = false;
  let insertHeld = false;
  let activeVideo = null;
  let lastPlayerFrameEl = null; // v3.2.1: bar çapası — akış bildiren gömülü iframe öğesi
  let barUserPos = null; // v3.2.1: fareyle taşınan bar konumu (SPA geçişine dek korunur)
  const IS_TOP_FRAME = window === window.top; // v3.2.1: bar YALNIZ üst çerçevede (çift bar bitti)
  let barHost = null;
  let shadow = null;
  let uiRefs = null;
  let dropdownOpen = false;
  let lastPageHref = location.href;
  let cachedFormats = null;
  // v2.8.3: probe meta (canlı mı? DRM mi? yt-dlp eksik mi?)
  let probeMeta = { isLive: false, isDvr: false, drm: false, ytdlpMissing: false, ytdlpPending: false };
  let emptyAutoRetries = 0; // v2.9.10: boş bar otomatik tazeleme sayacı
  let emptyReprobeTimer = null; // v3.0.0: self-healing bar — yeni akış gelince otomatik yeniden tara
  let cachedProbeUrl = "";
  let pendingProbePromise = null;
  let prefetchedUrl = "";
  let capturedNetworkCount = 0;
  let hideTimer = null;
  const hookedStreams = [];
  // v3.9.0 ALTYAZI DİL HARİTASI: <track label/srclang> bilgisi normalize edilmiş URL
  // anahtarıyla saklanır; ağ sniffer'ının isimsiz yakaladığı altyazılar bu haritadan
  // dil etiketini miras alır (kullanıcı kararı: 'altyazı dilini de yazsın')
  const subLabelMap = new Map();
  const subNormSeen = new Set();
  let lastPrefetchCount = 0; // v3.9.0: yeni akış geldikçe otomatik yeniden tarama sayacı

  function normSubKey(u) {
    try {
      const p = new URL(u, location.href);
      const identity = new Set(["lang", "tlang", "language", "srclang", "v", "kind", "id", "track", "trackid", "sub", "subid", "subtitle", "file", "filename"]);
      const pairs = [...p.searchParams.entries()].filter(([k]) => identity.has(k.toLowerCase())).map(([k,v]) => [k.toLowerCase(),v]).sort((a,b) => a[0].localeCompare(b[0]) || a[1].localeCompare(b[1]));
      const query = new URLSearchParams(pairs).toString();
      return p.host + p.pathname.replace(/\/+$/, "") + (query ? "?" + query : "");
    } catch (_e) {
      return String(u || "").toLowerCase();
    }
  }

  function rememberTrackLabel(url, label) {
    const lbl = String(label || "").trim();
    if (!url || !lbl || /^(default|forced)$/i.test(lbl)) return;
    const key = normSubKey(url);
    const prev = subLabelMap.get(key);
    if (!prev || (prev.length < lbl.length && !/^(altyaz[ıi]|subtitle)$/i.test(lbl))) {
      subLabelMap.set(key, lbl);
    }
  }

  function enrichSubLabel(url, label) {
    const key = normSubKey(url);
    const mapped = subLabelMap.get(key) || "";
    const lbl = String(label || "").trim();
    const generic = !lbl || /^(altyaz[ıi]|subtitle)$/i.test(lbl);
    if (mapped && generic) return mapped;
    if (!lbl && mapped) return mapped;
    return lbl || "";
  }
  // v2.8.7 bellek/sel koruması: O(1) tekilleştirme + toplu kayıt + ölçülü önbellek düşürme
  const seenUrlSet = new Set();
  let pendingCaptureBatch = [];
  let captureFlushTimer = null;
  let lastFormatInvalidate = 0;
  const gofileAsked = new Set();
  // v2.9.0: eklenti sağ tık menüsünden PASİF/AKTİF edilebilir
  let extDisabled = true;
  let blobBridgeReady = false;
  function publishCaptureState() {
    if (document.documentElement) {
      const oldState = document.documentElement.dataset.idmLinuxCaptureEnabled;
      document.documentElement.dataset.idmLinuxCaptureEnabled = !extDisabled && blobBridgeReady ? "1" : "0";
      if (oldState !== document.documentElement.dataset.idmLinuxCaptureEnabled) window.dispatchEvent(new Event("idm-linux-capture-state"));
      document.documentElement.dataset.idmLinuxBlobReady = !extDisabled && blobBridgeReady ? "1" : "0";
    }
    if (extDisabled && barHost) barHost.style.display = "none";
  }
  async function refreshCaptureReadiness() {
    if (extDisabled) return;
    const info = await sendMsg({ type: "IDM_GET_TAB_INFO", hostname: location.hostname });
    if (info && info.ok) videoBarAllowed = info.videoBarEnabled !== false;
    const st = info && info.state;
    blobBridgeReady = Boolean(st && st.online && st.idm_installed && st.capture_downloads);
    publishCaptureState();
  }
  try {
    chrome.storage.local.get(["extDisabled"], (r) => { extDisabled = Boolean(r && r.extDisabled); publishCaptureState(); refreshCaptureReadiness(); });
    chrome.storage.onChanged.addListener((ch, area) => {
      if (area === "local" && ch.extDisabled) {
        extDisabled = Boolean(ch.extDisabled.newValue);
        cachedFormats = null;
        publishCaptureState();
        if (!extDisabled) { refreshCaptureReadiness(); updateBarPosition(); }
      }
    });
  } catch (_e) {}

  async function idmPostDownload(url, referer) {
    if (extDisabled) return;
    try {
      // v2.8.8: tarayıcının kendi indirmesini bastır (IDM devraldı)
      sendMsg({ type: "IDM_TAKEOVER_URL", url, gofileWindowMs: 20000 });
      const cfg = await chrome.storage.local.get(["httpPort"]);
      const port = cfg.httpPort || 17802;
      await fetch(`http://127.0.0.1:${port}/api/download`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${port}` },
        body: JSON.stringify({
          url,
          referer: referer || location.href,
          cookies: document.cookie || "",
          userAgent: navigator.userAgent,
          force: true,
          source: "gofile-capture"
        })
      });
    } catch (_e) {}
  }

  // Firefox MV2 uyumu için page_hook.js enjeksiyonu (Chromium MV3 zaten manifest world:MAIN ile yükler)
  try {
    if (typeof browser !== "undefined" && extApi.runtime && extApi.runtime.getURL) {
      const sc = document.createElement("script");
      sc.src = extApi.runtime.getURL("page_hook.js");
      sc.onload = () => sc.remove();
      (document.head || document.documentElement).appendChild(sc);
    }
  } catch (_e) {}

  let siphonId = null;      // v2.9.6: WebRTC sifon oturumu
  let siphonBase = "";
  let siphonActive = false;
  let siphonBytes = 0;      // v2.9.8: gerçek akış var mı eşiği

  window.addEventListener("message", (ev) => {
    const d = ev && ev.data;
    if (!d) return;
    // v3.2.1: alt çerçeve bildiriminin geldiği frame öğesini hatırla (barı videonun üstüne çapala)
    if (IS_TOP_FRAME && ev.source && ev.source !== window) {
      try {
        const fr = Array.from(document.querySelectorAll("iframe,frame")).find((el) => el.contentWindow === ev.source);
        if (fr) lastPlayerFrameEl = fr;
      } catch (_e) {}
    }
    if (extDisabled) {
      if (d.__idmLinuxBlobRequest && d.reqId && ev.source === window) window.postMessage({ __idmLinuxBlobResult: true, reqId: d.reqId, ok: false, takeover: false }, "*");
      return;
    } // v2.9.0: pasif modda hiçbir yakalama iletilmez

    // v2.9.6: P2P sifonu — baytlar geldikçe daemon'a akıt, IDM ANINDA açılır
    if (d.__idmLinuxSiphonStart) {
      (async () => {
        try {
          const cfg3 = await chrome.storage.local.get(["httpPort"]);
          const port3 = cfg3.httpPort || 17802;
          siphonBase = `http://127.0.0.1:${port3}`;
          const hdrs3 = { "Content-Type": "application/json", Origin: siphonBase };
          let fn = "";
          try {
            const m = ((document.body && document.body.innerText) || "").match(/\S+\.(?:xlsx|xls|zip|rar|7z|pdf|docx?|pptx?|txt|csv|exe|apk|iso|mp3|mp4|mkv)\b/i);
            if (m) fn = m[0];
          } catch (_e) {}
          const ir = await fetch(`${siphonBase}/api/blobfeed/init`, {
            method: "POST", headers: hdrs3,
            body: JSON.stringify({ filename: fn || (document.title || "p2p-dosya").slice(0, 80), mimeType: "application/octet-stream", streaming: true })
          }).then((r) => r.json());
          if (ir && ir.ok) { siphonId = ir.id; }
        } catch (_e) {}
      })();
      return;
    }
    if (d.__idmLinuxSiphonChunk && d.b64) {
      siphonBytes += Math.floor((d.b64.length * 3) / 4);
      if (siphonBytes > 262144) siphonActive = true;
      if (siphonId && siphonBase) {
        fetch(`${siphonBase}/api/assist/chunk`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Origin: siphonBase },
          body: JSON.stringify({ id: siphonId, b64: d.b64 })
        }).catch(() => {});
      }
      return;
    }
    if (d.__idmLinuxSiphonEnd) {
      if (siphonId && siphonBase) {
        fetch(`${siphonBase}/api/blobfeed/done`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Origin: siphonBase },
          body: JSON.stringify({ id: siphonId })
        }).catch(() => {});
      }
      siphonId = null;
      return;
    }

    if (d.__idmLinuxBlobRequest && d.reqId && ev.source === window) {
      sendMsg({ type: "IDM_BLOB_TRANSFER", action: d.action, transferId: d.transferId,
        filename: d.filename, mimeType: d.mimeType, size: d.size,
        offset: d.offset, dataBase64: d.dataBase64, pageUrl: location.href
      }).then((res) => {
        window.postMessage(Object.assign({}, res || { ok: false }, { __idmLinuxBlobResult: true, reqId: d.reqId }), "*");
      });
      return;
    }

    // v2.9.0: sayfanın programatik indirme gezinmesi yakalandı -> daemon devralır, tarayıcı SUSAR
    // v3.13.0: gofile da ONAYSIZ OTOMATIK — kullanıcı kuralı "IDM yakalasın, tarayıcı indirmesin"
    if (d.__idmLinuxNavTakeover && d.url && !extDisabled) {
      idmPostDownload(d.url, location.href);
      return;
    }

    // v2.9.4: abyss slug / altyazı / justbeamit doğrudan link yakalamaları
    if (d.__idmLinuxAbyssMeta && d.payload) {
      sendMsg({ type: "IDM_ABYSS_META", payload: d.payload });
      return;
    }
    if (d.__idmLinuxAbyss && d.slug) {
      sendMsg({ type: "IDM_REGISTER_CAPTURED_STREAMS", streams: [{ url: "abyss://" + d.slug, mime: "application/x-abyss", referer: location.href, origin: location.origin }] });
      return;
    }
    // v3.1.0: parent sayfada bulunan abyss gömülü iframe'i (page_hook tarayıcısı) kaydet
    if (d.__idmLinuxAbyssIframe && d.url) {
      sendMsg({ type: "IDM_REGISTER_CAPTURED_STREAMS", streams: [{ url: "abyssif://" + d.url, mime: "application/x-abyss", referer: d.pageUrl || location.href, origin: location.origin }] });
      return;
    }
    // v3.1.0: EME/DRM algılandı (dsmartgo vb. canlı TV) — bar net mesaj göstersin
    if (d.__idmLinuxDrmDetected) {
      sendMsg({ type: "IDM_REGISTER_CAPTURED_STREAMS", streams: [{ url: "drm://detected?keysystem=" + encodeURIComponent(d.keySystem || ""), mime: "application/x-idm-drm", referer: d.pageUrl || location.href, origin: location.origin }] });
      return;
    }
    if (d.__idmLinuxSubtitleText && d.vtt) {
      // v3.10.0: oynatıcıya gömülü (blob/MSE) altyazı — daemon kasasına gönderilir
      if (String(d.vtt).length > 40) {
        sendMsg({ type: "IDM_SUBTITLE_TEXT", vtt: d.vtt, label: d.label || "altyazı", lang: d.lang || "" });
      }
      return;
    }

    if (d.__idmLinuxSubtitle && d.url) {
      // v3.9.0: page_hook'tan gelen altyazı — dil etiketi <track> haritasından zenginleştirilir
      let su = "";
      try { su = new URL(d.url, location.href).href; } catch (_e) { su = d.url; }
      const lbl = enrichSubLabel(su, d.label || "");
      rememberTrackLabel(su, lbl);
      sendMsg({ type: "IDM_REGISTER_CAPTURED_STREAMS", streams: [{ url: su, mime: "text/vtt", referer: location.href, origin: location.origin, sub_label: lbl }] });
      return;
    }

    if (!d.__idmLinuxMediaHook || !d.url) return;

    // v2.8.7 GOFILE: wt token'lı gerçek indirme bağlantısı sayfada görüldüğü anda yakala
    if (d.isFileDownload && /gofile\.io/i.test(d.url)) {
      // v3.11.0: contents JSON'undan gelen GERÇEK dosya linki (fileName taşır) — onay
      // penceresi BEKLEMDEN bara kaydedilir; kullanıcı sitedeki Download'a basmadan
      // önce dosya hazır olur (algılama gecikmesi şikâyetinin çözümü).
      if (d.fileName) {
        const gitem = {
          url: d.url,
          mime: d.mime || "",
          isHls: false,
          manifestText: "",
          referer: d.referer || location.href,
          origin: d.origin || location.origin,
          size: d.fileSize || null,
          sub_label: "Gofile: " + d.fileName
        };
        if (!seenUrlSet.has(gitem.url)) {
          seenUrlSet.add(gitem.url);
          if (seenUrlSet.size > 4000) seenUrlSet.clear();
          hookedStreams.push(gitem);
          if (hookedStreams.length > 200) hookedStreams.splice(0, hookedStreams.length - 200);
          capturedNetworkCount += 1;
          cachedFormats = null;
          pendingCaptureBatch.push(gitem);
          if (!captureFlushTimer) {
            captureFlushTimer = setTimeout(() => {
              captureFlushTimer = null;
              const batch = pendingCaptureBatch.splice(0, pendingCaptureBatch.length);
              if (batch.length) sendMsg({ type: "IDM_REGISTER_CAPTURED_STREAMS", streams: batch });
            }, 600);
          }
        }
        return;
      }
      if (!gofileAsked.has(d.url)) {
        gofileAsked.add(d.url);
        if (gofileAsked.size > 100) gofileAsked.clear();
        // v3.13.0: onay penceresi YOK — gofile indirmesi doğrudan daemon'a gider,
        // daemon taze gerçek store linkini çözüp IDM'ye verir (tarayıcı indirmesi imkânsız).
        idmPostDownload(d.url, d.referer);
      }
      return;
    }
    const item = {
      url: d.url,
      mime: d.mime || (d.isHls ? "application/vnd.apple.mpegurl" : ""),
      isHls: Boolean(d.isHls),
      manifestText: (d.manifestText || "").slice(0, 8192), // v2.9.0 bellek koruması
      referer: d.referer || location.href,
      origin: d.origin || location.origin,
      size: null
    };
    if (!seenUrlSet.has(item.url)) {
      seenUrlSet.add(item.url);
      if (seenUrlSet.size > 4000) seenUrlSet.clear(); // v2.8.7: tekilleştirme seti de sınırlı
      hookedStreams.push(item);
      if (hookedStreams.length > 200) hookedStreams.splice(0, hookedStreams.length - 200); // v2.9.0: 400->200 (sızıntı regressyonu)
      capturedNetworkCount += 1;
      // v2.8.7: format önbelleğini segment başına DEĞİL en fazla 8 sn'de bir düşür (probe seli = donma)
      const nowMs = Date.now();
      if (nowMs - lastFormatInvalidate > 8000) {
        cachedFormats = null;
        lastFormatInvalidate = nowMs;
      }
      // v2.8.7 TOPLU KAYIT: segment başına mesaj yerine 1.2 sn'de bir tek paket
      pendingCaptureBatch.push(item);
      // First usable source is available immediately; later segments stay batched.
      if (hookedStreams.length === 1) {
        const batch = pendingCaptureBatch.splice(0, pendingCaptureBatch.length);
        sendMsg({ type: "IDM_REGISTER_CAPTURED_STREAMS", streams: batch });
      } else if (!captureFlushTimer) {
        captureFlushTimer = setTimeout(() => {
          captureFlushTimer = null;
          const batch = pendingCaptureBatch.splice(0, pendingCaptureBatch.length);
          if (batch.length) sendMsg({ type: "IDM_REGISTER_CAPTURED_STREAMS", streams: batch });
        }, 1200);
      }
    }
  });

  function sendMsg(payload) {
    return new Promise((resolve) => {
      try {
        extApi.runtime.sendMessage(payload, (resp) => {
          void extApi.runtime.lastError;
          resolve(resp || { ok: false });
        });
      } catch (_e) {
        resolve({ ok: false });
      }
    });
  }

  // -------------------------------------------------------------------------
  // v3.5.0: TORRENT / MAGNET ONAY PENCERESİ — şık, IDM Linux temalı popup.
  // Herhangi bir bağlantı veya buton-bağlantısı magnet:? / .torrent ise tıklamada
  // kullanıcıdan onay istenir; 'Evet' seçilirse içerik IDM Linux torrent motorundan
  // (aria2c webseed köprüsü) indirilir. 'Hayır' -> bağlantı tarayıcıya bırakılır.
  // 13 dilde yerleşik metinler (tarayıcı diline göre seçilir).
  // -------------------------------------------------------------------------
  const TORRENT_I18N = (() => {
    const lang = (navigator.language || "en").slice(0, 2).toLowerCase();
    const M = {
      tr: { title: "Torrent İndirme Onayı", ask: "Bu torrenti indirmek istiyor musunuz?", engine: "İçerik IDM Linux torrent motoru (aria2c) ile indirilecek.", autoInstall: "aria2c kurulu değil — indirme başlarken otomatik kurulacak (yetki penceresini onaylayın).", file: "Dosyayı İndir", yes: "Evet, IDM ile İndir", no: "Hayır", fail: "Torrent başlatılamadı — IDM Linux köprüsüne ulaşılamadı. Paneli açıp köprüyi başlatın.", sent: "✓ Torrent IDM Linux'a gönderildi — köprü penceresini açabilirsiniz." },
      en: { title: "Torrent Download Confirmation", ask: "Do you want to download this torrent?", engine: "It will be downloaded via the IDM Linux torrent engine (aria2c).", autoInstall: "aria2c is not installed — it will be installed automatically when the download starts (approve the auth window).", file: "Download the File", yes: "Yes, Download with IDM", no: "No", fail: "Could not start torrent — IDM Linux bridge unreachable. Start it from the Control Center.", sent: "✓ Torrent sent to IDM Linux." },
      de: { title: "Torrent-Download bestätigen", ask: "Diesen Torrent herunterladen?", engine: "Der Download erfolgt über die IDM-Linux-Torrent-Engine (aria2c).", autoInstall: "aria2c ist nicht installiert — es wird beim Download-Start automatisch installiert (Auth-Fenster bestätigen).", file: "Datei herunterladen", yes: "Ja, mit IDM laden", no: "Nein", fail: "Torrent konnte nicht gestartet werden — IDM-Linux-Bridge nicht erreichbar.", sent: "✓ Torrent an IDM Linux gesendet." },
      fr: { title: "Confirmation du téléchargement torrent", ask: "Voulez-vous télécharger ce torrent ?", engine: "Il sera téléchargé via le moteur torrent IDM Linux (aria2c).", autoInstall: "aria2c n'est pas installé — il sera installé automatiquement au démarrage du téléchargement (approuvez la fenêtre d'autorisation).", file: "Télécharger le fichier", yes: "Oui, télécharger avec IDM", no: "Non", fail: "Impossible de démarrer le torrent — pont IDM Linux injoignable.", sent: "✓ Torrent envoyé à IDM Linux." },
      ru: { title: "Подтверждение загрузки торрента", ask: "Скачать этот торрент?", engine: "Загрузка будет выполнена через торрент-движок IDM Linux (aria2c).", autoInstall: "aria2c не установлен — он будет установлен автоматически при запуске загрузки (подтвердите окно авторизации).", file: "Скачать файл", yes: "Да, скачать через IDM", no: "Нет", fail: "Не удалось запустить торрент — мост IDM Linux недоступен.", sent: "✓ Торрент отправлен в IDM Linux." },
      es: { title: "Confirmar descarga de torrent", ask: "¿Quieres descargar este torrent?", engine: "Se descargará con el motor torrent de IDM Linux (aria2c).", autoInstall: "aria2c no está instalado — se instalará automáticamente al iniciar la descarga (apruebe la ventana de autorización).", file: "Descargar el archivo", yes: "Sí, descargar con IDM", no: "No", fail: "No se pudo iniciar el torrent: puente de IDM Linux no disponible.", sent: "✓ Torrent enviado a IDM Linux." },
      it: { title: "Conferma download torrent", ask: "Vuoi scaricare questo torrent?", engine: "Verrà scaricato con il motore torrent di IDM Linux (aria2c).", autoInstall: "aria2c non è installato — verrà installato automaticamente all'avvio del download (approva la finestra di autorizzazione).", file: "Scarica il file", yes: "Sì, scarica con IDM", no: "No", fail: "Impossibile avviare il torrent: bridge IDM Linux non raggiungibile.", sent: "✓ Torrent inviato a IDM Linux." },
      pt: { title: "Confirmação de download de torrent", ask: "Deseja baixar este torrent?", engine: "Será baixado pelo motor torrent do IDM Linux (aria2c).", autoInstall: "aria2c não está instalado — será instalado automaticamente ao iniciar o download (aprovar a janela de autorização).", file: "Baixar o arquivo", yes: "Sim, baixar com IDM", no: "Não", fail: "Não foi possível iniciar o torrent — ponte IDM Linux inacessível.", sent: "✓ Torrent enviado ao IDM Linux." },
      zh: { title: "种子下载确认", ask: "要下载这个种子吗？", engine: "将通过 IDM Linux 种子引擎 (aria2c) 下载。", autoInstall: "aria2c 未安装 — 下载开始时将自动安装（请在授权窗口中确认）。", file: "下载文件", yes: "是，用 IDM 下载", no: "否", fail: "无法启动种子 — IDM Linux 桥接不可用。", sent: "✓ 种子已发送到 IDM Linux。" },
      ja: { title: "トレント ダウンロードの確認", ask: "このトレントをダウンロードしますか？", engine: "IDM Linux トレントエンジン (aria2c) でダウンロードします。", autoInstall: "aria2c が未インストール — ダウンロード開始時に自動導入されます（認証ウィンドウを承認してください）。", file: "ファイルをダウンロード", yes: "はい、IDM でダウンロード", no: "いいえ", fail: "トレントを開始できません — IDM Linux ブリッジに接続できません。", sent: "✓ トレントを IDM Linux に送信しました。" },
      ar: { title: "تأكيد تنزيل التورنت", ask: "هل تريد تنزيل هذا التورنت؟", engine: "سيتم التنزيل عبر محرك IDM Linux للتورنت (aria2c).", autoInstall: "aria2c غير مثبت — سيتم تثبيته تلقائيًا عند بدء التنزيل (وافق على نافذة التصريح).", file: "تنزيل الملف", yes: "نعم، نزّل عبر IDM", no: "لا", fail: "تعذر بدء التورنت — جسر IDM Linux غير متوفر.", sent: "✓ تم إرسال التورنت إلى IDM Linux." },
      az: { title: "Torrent endirmə təsdiqi", ask: "Bu torrenti endirmək istəyirsiniz?", engine: "IDM Linux torrent mühərriki (aria2c) ilə endiriləcək.", autoInstall: "aria2c quraşdırılmayıb — endirmə başlayanda avtomatik quraşdırılacaq (avalandırma pəncərəsini təsdiqləyin).", file: "Faylı endir", yes: "Bəli, IDM ilə endir", no: "Xeyr", fail: "Torrent başladıla bilmədi — IDM Linux körpüsü əlçatmazdır.", sent: "✓ Torrent IDM Linux-a göndərildi." },
      id: { title: "Konfirmasi Unduh Torrent", ask: "Unduh torrent ini?", engine: "Akan diunduh via mesin torrent IDM Linux (aria2c).", autoInstall: "aria2c belum terpasang — akan terpasang otomatis saat unduhan dimulai (setujui jendela otorisasi).", file: "Unduh Berkas", yes: "Ya, unduh dengan IDM", no: "Tidak", fail: "Torrent gagal dimulai — bridge IDM Linux tidak terjangkau.", sent: "✓ Torrent dikirim ke IDM Linux." },
    };
    return M[lang] || M.en;
  })();

  // -------------------------------------------------------------------------
  // v3.7.0: eD2K (eMule) ONAY PENCERESİ — docuwiki.net gibi sitelerdeki
  // ed2k://|file|... bağlantıları tarayıcı tarafından 'about:blank#blocked'
  // ile engellenir; biz TIKLAMAYI yakalayıp kendi motoruna (mldonkey/aMule)
  // iletiriz. Motor kurulu değilse TEK TIK kurulum + durum yoklaması yapılır.
  // -------------------------------------------------------------------------
  const ED2K_I18N = (() => {
    const lang = (navigator.language || "en").slice(0, 2).toLowerCase();
    // v3.8.0: eski 'Kurulum başarısız' + elle kurulum komutları KALDIRILDI (kullanıcı
    // kararı). Kurulum tam otomatiktir; tek onay, sistemin kendi pkexec
    // yetkilendirme penceresidir. Başarısızlıkta dostane 'tekrar dene' mesajı gösterilir.
    const M = {
      tr: { title: "eD2K (eMule) İndirme Onayı", ask: "Bu eD2K bağlantısını eMule motoruna eklemek istiyor musunuz?", engineOk: "Motor hazır — bağlantı kuyruğa eklenecek.", engineMissing: "eD2K motoru (aMule) kurulu değil — kurulum otomatik başlıyor.", installBtn: "🛠 Motoru Kur", installing: "⏳ Motor kuruluyor... (açılan yetkilendirme penceresini onaylayın — tek adım bu)", installOk: "✓ Motor hazır — bağlantınız otomatik olarak gönderiliyor...", autoSent: "✓ Bağlantı eMule motoruna iletildi — indirme kuyrukta başladı!", installRetry: "⏳ Kurulum bu denemede tamamlanmadı. Yetkilendirme penceresini onayladığınızdan ve internet bağlantınızın çalıştığından emin olup tekrar deneyin.", yes: "Evet, eMule ile İndir", no: "Hayır", fail: "eD2K bağlantısı eklenemedi — motor yanıtı:", sent: "✓ Bağlantı eMule motoruna eklendi — indirme kuyrukta başladı!", bridgeOff: "IDM Linux köprüsüne ulaşılamadı — paneli açıp köprüyü başlatın." },
      en: { title: "eD2K (eMule) Download Confirmation", ask: "Add this eD2K link to the eMule engine?", engineOk: "Engine ready — the link will be queued.", engineMissing: "eD2K engine (aMule) is not installed — installation starts automatically.", installBtn: "🛠 Install Engine", installing: "⏳ Installing the engine... (please approve the authorization window — that is the only step)", installOk: "✓ Engine ready — your link is being sent automatically...", autoSent: "✓ Link sent to the eMule engine — download started in queue!", installRetry: "⏳ The installation could not complete this time. Please make sure you approved the authorization window and your internet works, then try again.", yes: "Yes, Download with eMule", no: "No", fail: "Could not add the eD2K link — engine response:", sent: "✓ Link added to the eMule engine — download started in queue!", bridgeOff: "IDM Linux bridge unreachable — open the panel to start it." },
      de: { title: "eD2K-(eMule)-Download bestätigen", ask: "Diesen eD2K-Link zur eMule-Engine hinzufügen?", engineOk: "Engine bereit — der Link wird eingereiht.", engineMissing: "eD2K-Engine (aMule) ist nicht installiert — Installation startet automatisch.", installBtn: "🛠 Engine installieren", installing: "⏳ Engine wird installiert... (bitte bestätigen Sie das Autorisierungsfenster — das ist der einzige Schritt)", installOk: "✓ Engine bereit — Ihr Link wird automatisch gesendet...", autoSent: "✓ Link an die eMule-Engine gesendet — Download gestartet!", installRetry: "⏳ Die Installation konnte diesmal nicht abgeschlossen werden. Bitte bestätigen Sie das Autorisierungsfenster und prüfen Sie Ihre Internetverbindung, dann versuchen Sie es erneut.", yes: "Ja, mit eMule laden", no: "Nein", fail: "eD2K-Link konnte nicht hinzugefügt werden — Engine-Antwort:", sent: "✓ Link zur eMule-Engine hinzugefügt — Download gestartet!", bridgeOff: "IDM-Linux-Bridge nicht erreichbar — Panel öffnen." },
      fr: { title: "Confirmation de téléchargement eD2K (eMule)", ask: "Ajouter ce lien eD2K au moteur eMule ?", engineOk: "Moteur prêt — le lien sera mis en file.", engineMissing: "Le moteur eD2K (aMule) n'est pas installé — l'installation démarre automatiquement.", installBtn: "🛠 Installer le moteur", installing: "⏳ Installation du moteur... (veuillez approuver la fenêtre d'autorisation — c'est la seule étape)", installOk: "✓ Moteur prêt — votre lien est envoyé automatiquement...", autoSent: "✓ Lien envoyé au moteur eMule — téléchargement lancé !", installRetry: "⏳ L'installation n'a pas pu se terminer cette fois. Veuillez approuver la fenêtre d'autorisation, vérifier votre connexion Internet puis réessayer.", yes: "Oui, télécharger avec eMule", no: "Non", fail: "Impossible d'ajouter le lien eD2K — réponse du moteur :", sent: "✓ Lien ajouté au moteur eMule — téléchargement lancé !", bridgeOff: "Pont IDM Linux injoignable — ouvrez le panneau." },
      ru: { title: "Подтверждение загрузки eD2K (eMule)", ask: "Добавить эту eD2K-ссылку в движок eMule?", engineOk: "Движок готов — ссылка встанет в очередь.", engineMissing: "Движок eD2K (aMule) не установлен — установка начнётся автоматически.", installBtn: "🛠 Установить движок", installing: "⏳ Установка движка... (подтвердите окно авторизации — это единственный шаг)", installOk: "✓ Движок готов — ваша ссылка отправляется автоматически...", autoSent: "✓ Ссылка отправлена в движок eMule — загрузка началась!", installRetry: "⏳ Не удалось завершить установку. Убедитесь, что вы подтвердили окно авторизации и интернет работает, затем попробуйте снова.", yes: "Да, скачать через eMule", no: "Нет", fail: "Не удалось добавить ссылку — ответ движка:", sent: "✓ Ссылка добавлена в движок eMule — загрузка началась!", bridgeOff: "Мост IDM Linux недоступен — откройте панель." },
      es: { title: "Confirmar descarga eD2K (eMule)", ask: "¿Añadir este enlace eD2K al motor eMule?", engineOk: "Motor listo — el enlace se pondrá en cola.", engineMissing: "El motor eD2K (aMule) no está instalado — la instalación comienza automáticamente.", installBtn: "🛠 Instalar motor", installing: "⏳ Instalando el motor... (apruebe la ventana de autorización — es el único paso)", installOk: "✓ Motor listo — su enlace se está enviando automáticamente...", autoSent: "✓ Enlace enviado al motor eMule — ¡descarga iniciada!", installRetry: "⏳ La instalación no pudo completarse esta vez. Asegúrese de aprobar la ventana de autorización y de que su internet funciona, luego inténtelo de nuevo.", yes: "Sí, descargar con eMule", no: "No", fail: "No se pudo añadir el enlace eD2K — respuesta del motor:", sent: "✓ Enlace añadido al motor eMule — ¡descarga iniciada!", bridgeOff: "Puente de IDM Linux no disponible — abre el panel." },
      it: { title: "Conferma download eD2K (eMule)", ask: "Aggiungere questo link eD2K al motore eMule?", engineOk: "Motore pronto — il link verrà accodato.", engineMissing: "Il motore eD2K (aMule) non è installato — l'installazione parte automaticamente.", installBtn: "🛠 Installa motore", installing: "⏳ Installazione del motore... (approva la finestra di autorizzazione — è l'unico passaggio)", installOk: "✓ Motore pronto — il tuo link viene inviato automaticamente...", autoSent: "✓ Link inviato al motore eMule — download avviato!", installRetry: "⏳ L'installazione non è stata completata questa volta. Assicurati di aver approvato la finestra di autorizzazione e che internet funzioni, poi riprova.", yes: "Sì, scarica con eMule", no: "No", fail: "Impossibile aggiungere il link eD2K — risposta del motore:", sent: "✓ Link aggiunto al motore eMule — download avviato!", bridgeOff: "Bridge IDM Linux non raggiungibile — apri il pannello." },
      pt: { title: "Confirmação de download eD2K (eMule)", ask: "Adicionar este link eD2K ao motor eMule?", engineOk: "Motor pronto — o link entrará na fila.", engineMissing: "O motor eD2K (aMule) não está instalado — a instalação começa automaticamente.", installBtn: "🛠 Instalar motor", installing: "⏳ Instalando o motor... (aprovar a janela de autorização — é o único passo)", installOk: "✓ Motor pronto — seu link está sendo enviado automaticamente...", autoSent: "✓ Link enviado ao motor eMule — download iniciado!", installRetry: "⏳ A instalação não pôde ser concluída desta vez. Certifique-se de ter aprovado a janela de autorização e de que a internet funciona, depois tente novamente.", yes: "Sim, baixar com eMule", no: "Não", fail: "Não foi possível adicionar o link eD2K — resposta do motor:", sent: "✓ Link adicionado ao motor eMule — download iniciado!", bridgeOff: "Ponte IDM Linux inacessível — abra o painel." },
      zh: { title: "eD2K (eMule) 下载确认", ask: "将此 eD2K 链接添加到 eMule 引擎？", engineOk: "引擎就绪 — 链接将进入队列。", engineMissing: "尚未安装 eD2K 引擎 (aMule) — 即将自动开始安装。", installBtn: "🛠 安装引擎", installing: "⏳ 正在安装引擎...（请在授权窗口中确认 — 仅此一步）", installOk: "✓ 引擎就绪 — 正在自动发送您的链接...", autoSent: "✓ 链接已发送至 eMule 引擎 — 下载已开始！", installRetry: "⏳ 本次安装未能完成。请确认已在授权窗口中确认且网络正常，然后重试。", yes: "是，用 eMule 下载", no: "否", fail: "无法添加 eD2K 链接 — 引擎响应：", sent: "✓ 链接已添加到 eMule 引擎 — 下载已开始！", bridgeOff: "IDM Linux 桥接不可用 — 请打开面板。" },
      ja: { title: "eD2K (eMule) ダウンロード確認", ask: "この eD2K リンクを eMule エンジンに追加しますか？", engineOk: "エンジン準備完了 — リンクはキューに入ります。", engineMissing: "eD2K エンジン (aMule) が未インストール — 自動でインストールを開始します。", installBtn: "🛠 エンジンを導入", installing: "⏳ エンジンを導入中...（認証ウィンドウを承認してください — それだけです）", installOk: "✓ エンジン準備完了 — リンクを自動送信しています...", autoSent: "✓ リンクを eMule エンジンに送信 — ダウンロード開始！", installRetry: "⏳ 今回はインストールを完了できませんでした。認証ウィンドウを承認したかとインターネット接続を確認し、再試行してください。", yes: "はい、eMule でダウンロード", no: "いいえ", fail: "eD2K リンクを追加できません — エンジンの応答：", sent: "✓ リンクを eMule エンジンに追加 — ダウンロード開始！", bridgeOff: "IDM Linux ブリッジに接続できません — パネルを開いてください。" },
      ar: { title: "تأكيد تنزيل eD2K (eMule)", ask: "إضافة هذا الرابط eD2K إلى محرك eMule؟", engineOk: "المحرك جاهز — سيتم إدراج الرابط في القائمة.", engineMissing: "محرك eD2K (aMule) غير مثبت — سيبدأ التثبيت تلقائيًا.", installBtn: "🛠 تثبيت المحرك", installing: "⏳ جارٍ تثبيت المحرك... (يرجى الموافقة على نافذة التصريح — هذه هي الخطوة الوحيدة)", installOk: "✓ المحرك جاهز — يتم إرسال رابطك تلقائيًا...", autoSent: "✓ تم إرسال الرابط إلى محرك eMule — بدأ التنزيل!", installRetry: "⏳ تعذر إكمال التثبيت هذه المرة. تأكد من الموافقة على نافذة التصريح وعمل الإنترنت ثم حاول مجددًا.", yes: "نعم، نزّل عبر eMule", no: "لا", fail: "تعذر إضافة رابط eD2K — رد المحرك:", sent: "✓ تمت إضافة الرابط إلى محرك eMule — بدأ التنزيل!", bridgeOff: "جسر IDM Linux غير متوفر — افتح اللوحة." },
      az: { title: "eD2K (eMule) endirmə təsdiqi", ask: "Bu eD2K keçidini eMule mühərrikinə əlavə et?", engineOk: "Mühərrik hazırdır — keçid növbəyə düşəcək.", engineMissing: "eD2K mühərriki (aMule) quraşdırılmayıb — quraşdırma avtomatik başlayır.", installBtn: "🛠 Mühərriki quraşdır", installing: "⏳ Mühərrik quraşdırılır... (avalandırma pəncərəsini təsdiqləyin — tək addım budur)", installOk: "✓ Mühərrik hazır — keçidiniz avtomatik göndərilir...", autoSent: "✓ Keçid eMule mühərrikinə göndərildi — endirmə başladı!", installRetry: "⏳ Quraşdırma bu dəfə tamamlanmadı. Avalandırma pəncərəsini təsdiqlədiyinizi və internetin işlədiyini yoxlayıb yenidən cəhd edin.", yes: "Bəli, eMule ilə endir", no: "Xeyr", fail: "eD2K keçidi əlavə edilə bilmədi — mühərrik cavabı:", sent: "✓ Keçid eMule mühərrikinə əlavə olundu — endirmə başladı!", bridgeOff: "IDM Linux körpüsü əlçatmazdır — paneli açın." },
      id: { title: "Konfirmasi Unduh eD2K (eMule)", ask: "Tambahkan tautan eD2K ini ke mesin eMule?", engineOk: "Mesin siap — tautan akan masuk antrean.", engineMissing: "Mesin eD2K (aMule) belum terpasang — pemasangan dimulai otomatis.", installBtn: "🛠 Pasang Mesin", installing: "⏳ Memasang mesin... (setujui jendela otorisasi — hanya itu langkahnya)", installOk: "✓ Mesin siap — tautan Anda dikirim otomatis...", autoSent: "✓ Tautan dikirim ke mesin eMule — unduhan dimulai!", installRetry: "⏳ Pemasangan belum selesai kali ini. Pastikan Anda menyetujui jendela otorisasi dan internet berfungsi, lalu coba lagi.", yes: "Ya, unduh dengan eMule", no: "Tidak", fail: "Tautan eD2K tidak bisa ditambahkan — respons mesin:", sent: "✓ Tautan ditambahkan ke mesin eMule — unduhan dimulai!", bridgeOff: "Bridge IDM Linux tidak terjangkau — buka panel." },
    };
    return M[lang] || M.en;
  })();

  function idmEd2kParse(href) {
    // ed2k://|file|<ad>|<boyut>|<hash>|/  ->  {name, size}
    try {
      const m = /^ed2k:\/\/\|file\|([^|]+)\|(\d+)\|/i.exec(href || "");
      if (!m) return null;
      let name = m[1];
      try { name = decodeURIComponent(name); } catch (_e) {}
      const size = parseInt(m[2], 10) || 0;
      return { name: name.slice(0, 110), size };
    } catch (_e) {
      return null;
    }
  }

  function idmEd2kFormatSize(bytes) {
    if (!bytes || bytes <= 0) return "";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let v = bytes;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i += 1; }
    return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
  }

  let ed2kPopupEl = null;

  function idmEd2kPopup(href) {
    if (ed2kPopupEl && ed2kPopupEl.isConnected) ed2kPopupEl.remove();
    const meta = idmEd2kParse(href) || { name: "eD2K bağlantısı", size: 0 };
    const overlay = document.createElement("div");
    overlay.setAttribute("data-idm-ed2k-popup", "1");
    overlay.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:rgba(2,6,23,.66);display:flex;align-items:center;justify-content:center;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;animation:idmtp-fade .16s ease-out;";
    const card = document.createElement("div");
    card.style.cssText = "width:min(460px,92vw);background:#0f172a;border:1px solid #334155;border-radius:14px;padding:22px 22px 18px;box-shadow:0 24px 64px rgba(0,0,0,.55);color:#e2e8f0;";
    const hdr = document.createElement("div");
    hdr.style.cssText = "display:flex;align-items:center;gap:10px;margin-bottom:12px;";
    const ico = document.createElement("div");
    ico.textContent = "🐴";
    ico.style.cssText = "width:38px;height:38px;border-radius:10px;background:#1e293b;display:flex;align-items:center;justify-content:center;font-size:20px;flex:0 0 auto;";
    const htitle = document.createElement("div");
    htitle.textContent = ED2K_I18N.title;
    htitle.style.cssText = "font-size:15px;font-weight:700;color:#f8fafc;";
    hdr.appendChild(ico);
    hdr.appendChild(htitle);
    const ask = document.createElement("div");
    ask.textContent = ED2K_I18N.ask;
    ask.style.cssText = "font-size:13px;line-height:1.5;margin-bottom:8px;";
    const nm = document.createElement("div");
    nm.textContent = `${meta.name}${meta.size ? ` • ${idmEd2kFormatSize(meta.size)}` : ""}`;
    nm.style.cssText = "font-size:12px;font-weight:600;color:#7dd3fc;background:#16233a;border:1px solid #25364f;border-radius:8px;padding:8px 10px;margin-bottom:8px;word-break:break-all;max-height:64px;overflow:auto;";
    const eng = document.createElement("div");
    eng.textContent = "…";
    eng.style.cssText = "font-size:11px;color:#94a3b8;line-height:1.55;margin-bottom:12px;white-space:pre-line;";
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap;";
    const noBtn = document.createElement("button");
    noBtn.textContent = ED2K_I18N.no;
    noBtn.style.cssText = "padding:9px 16px;border-radius:9px;border:1px solid #475569;background:#1e293b;color:#e2e8f0;font-size:12px;font-weight:600;cursor:pointer;";
    const yesBtn = document.createElement("button");
    yesBtn.textContent = ED2K_I18N.yes;
    yesBtn.style.cssText = "padding:9px 16px;border-radius:9px;border:none;background:linear-gradient(135deg,#059669,#047857);color:#fff;font-size:12px;font-weight:700;cursor:pointer;box-shadow:0 6px 18px rgba(5,150,105,.35);";
    const installBtn = document.createElement("button");
    installBtn.textContent = ED2K_I18N.installBtn;
    installBtn.style.cssText = "padding:9px 14px;border-radius:9px;border:1px solid #b45309;background:linear-gradient(135deg,#d97706,#b45309);color:#fff;font-size:12px;font-weight:700;cursor:pointer;display:none;box-shadow:0 6px 18px rgba(217,119,6,.3);";
    row.appendChild(noBtn);
    row.appendChild(installBtn);
    row.appendChild(yesBtn);
    card.appendChild(hdr);
    card.appendChild(ask);
    card.appendChild(nm);
    card.appendChild(eng);
    card.appendChild(row);
    overlay.appendChild(card);
    const style = document.createElement("style");
    style.textContent = "@keyframes idmtp-fade{from{opacity:0}to{opacity:1}}@keyframes idmtp-pop{from{transform:scale(.94);opacity:0}to{transform:scale(1);opacity:1}}";
    card.style.animation = "idmtp-pop .18s ease-out";
    overlay.appendChild(style);
    const close = () => {
      try { overlay.remove(); } catch (_e) {}
      document.removeEventListener("keydown", onKey, true);
    };
    const onKey = (ev) => {
      if (ev.key === "Escape") { ev.stopPropagation(); close(); }
    };
    overlay.addEventListener("click", (ev) => {
      if (ev.target === overlay) close();
    });
    document.addEventListener("keydown", onKey, true);
    noBtn.addEventListener("click", () => close());

    // --- motor ön-kontrolü: mldonkey/aMule hazır mı? -------------------------
    let engineReady = false;
    let engineBusy = false;
    // v3.8.0 TAM OTOMATİK KURULUM: motor yoksa kurulum KENDİLİĞİNDEN başlar;
    // pkexec yetkilendirme penceresi tek onaydır. Elle kurulum komutu ASLA
    // gösterilmez; kurulum bitince bağlantı OTOMATİK motora gönderilir.
    async function startEngineInstall() {
      if (engineBusy) return;
      engineBusy = true;
      installBtn.disabled = true;
      installBtn.style.display = "none";
      yesBtn.style.display = "none";
      eng.textContent = ED2K_I18N.installing;
      eng.style.color = "#38bdf8";
      try {
        const res = await sendMsg({ type: "IDM_ED2K_INSTALL" });
        if (res && res.ok && res.started) {
          // kurulum arka planda sürüyor — durumu yokla (en fazla ~5 dk)
          for (let i = 0; i < 100; i += 1) {
            await new Promise((r) => setTimeout(r, 3000));
            if (!overlay.isConnected) return;
            const st = await sendMsg({ type: "IDM_ED2K_PREFLIGHT" });
            if (st && st.ok && st.backend && st.backend !== "none" && st.running) {
              engineReady = true;
              eng.textContent = ED2K_I18N.installOk;
              eng.style.color = "#34d399";
              // v3.8.0: bağlantıyı OTOMATİK gönder — kullanıcıya ek tık yaptırılmaz
              try {
                const sendRes = await sendMsg({ type: "IDM_ED2K_SEND", href, referer: location.href });
                if (sendRes && sendRes.ok) {
                  ask.textContent = ED2K_I18N.autoSent + (sendRes.incoming_dir ? `\n📥 ${sendRes.incoming_dir}` : "");
                  ask.style.color = "#34d399";
                  ask.style.whiteSpace = "pre-line";
                  setTimeout(close, 3200);
                  return;
                }
              } catch (_e2) {}
              yesBtn.disabled = false;
              noBtn.disabled = false;
              yesBtn.style.display = "inline-block";
              return;
            }
          }
          if (!overlay.isConnected) return;
          eng.textContent = ED2K_I18N.installRetry;
          eng.style.color = "#f87171";
        } else {
          eng.textContent = ED2K_I18N.installRetry;
          eng.style.color = "#f87171";
        }
      } catch (_e) {
        eng.textContent = ED2K_I18N.installRetry;
        eng.style.color = "#f87171";
      }
      engineBusy = false;
      installBtn.disabled = false;
      installBtn.style.display = "inline-block";
    }
    sendMsg({ type: "IDM_ED2K_PREFLIGHT" }).then((pf) => {
      if (!overlay.isConnected) return;
      if (pf && pf.ok && pf.backend && pf.backend !== "none") {
        engineReady = Boolean(pf.running);
        if (engineReady) {
          const incLine = pf.incoming_dir ? `\n📥 ${pf.incoming_dir}` : "";
          eng.textContent = ED2K_I18N.engineOk + incLine;
          eng.style.color = "#34d399";
        } else {
          // kurulu ama servisi uykuda — daemon ilk gönderimde çekirdeği kendisi başlatır
          engineReady = true;
          eng.textContent = ED2K_I18N.engineOk;
          eng.style.color = "#34d399";
        }
      } else {
        // v3.8.0: motor yok → kurulum KENDİLİĞİNDEN başlar (tek onay: pkexec penceresi)
        startEngineInstall();
      }
    });
    installBtn.addEventListener("click", startEngineInstall);

    yesBtn.addEventListener("click", async () => {
      yesBtn.disabled = true;
      noBtn.disabled = true;
      installBtn.disabled = true;
      ask.textContent = "⏳ …";
      const sendRes = await sendMsg({ type: "IDM_ED2K_SEND", href, referer: location.href });
      if (sendRes && sendRes.ok) {
        ask.textContent = ED2K_I18N.sent;
        ask.style.color = "#34d399";
        const inc = sendRes.incoming_dir ? `\n📥 ${sendRes.incoming_dir}` : "";
        ask.textContent += inc;
        setTimeout(close, 2600);
      } else {
        const off = sendRes && sendRes.offline;
        const detail = (sendRes && sendRes.message) ? sendRes.message : "";
        ask.textContent = off ? ED2K_I18N.bridgeOff : `${ED2K_I18N.fail}\n${detail || "—"}`;
        ask.style.color = "#f87171";
        ask.style.whiteSpace = "pre-line";
        yesBtn.disabled = false;
        noBtn.disabled = false;
        installBtn.disabled = false;
      }
    });

    (document.documentElement || document.body).appendChild(overlay);
    ed2kPopupEl = overlay;
    yesBtn.focus();
  }

  window.__idmLinuxEd2kPopup = idmEd2kPopup;
  window.__idmLinuxTorrentPopup = idmTorrentPopup;

  function idmTorrentName(href, kind) {
    try {
      if (kind === "magnet") {
        const m = /[?&]dn=([^&]+)/i.exec(href);
        return m ? decodeURIComponent(m[1].replace(/\+/g, " ")) : "magnet";
      }
      return decodeURIComponent((href.split("?")[0].split("#")[0].split("/").pop() || "torrent").slice(0, 90));
    } catch (_e) {
      return kind === "magnet" ? "magnet" : "torrent";
    }
  }

  function idmTorrentPopup(href, kind) {
    // zaten açık popup varsa yenile
    if (torrentPopupEl && torrentPopupEl.isConnected) torrentPopupEl.remove();
    const overlay = document.createElement("div");
    overlay.setAttribute("data-idm-torrent-popup", "1");
    overlay.style.cssText = "position:fixed;inset:0;z-index:2147483647;background:rgba(2,6,23,.66);display:flex;align-items:center;justify-content:center;font-family:system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;animation:idmtp-fade .16s ease-out;";
    const card = document.createElement("div");
    card.style.cssText = "width:min(440px,92vw);background:#0f172a;border:1px solid #334155;border-radius:14px;padding:22px 22px 18px;box-shadow:0 24px 64px rgba(0,0,0,.55);color:#e2e8f0;";
    const hdr = document.createElement("div");
    hdr.style.cssText = "display:flex;align-items:center;gap:10px;margin-bottom:12px;";
    const ico = document.createElement("div");
    ico.textContent = "🧲";
    ico.style.cssText = "width:38px;height:38px;border-radius:10px;background:#1e293b;display:flex;align-items:center;justify-content:center;font-size:20px;flex:0 0 auto;";
    const htitle = document.createElement("div");
    htitle.textContent = TORRENT_I18N.title;
    htitle.style.cssText = "font-size:15px;font-weight:700;color:#f8fafc;";
    hdr.appendChild(ico);
    hdr.appendChild(htitle);
    const ask = document.createElement("div");
    ask.textContent = TORRENT_I18N.ask;
    ask.style.cssText = "font-size:13px;line-height:1.5;margin-bottom:8px;";
    const nm = document.createElement("div");
    nm.textContent = idmTorrentName(href, kind);
    nm.style.cssText = "font-size:12px;font-weight:600;color:#38bdf8;background:#16233a;border:1px solid #25364f;border-radius:8px;padding:8px 10px;margin-bottom:8px;word-break:break-all;max-height:64px;overflow:auto;";
    const eng = document.createElement("div");
    eng.textContent = TORRENT_I18N.engine;
    eng.style.cssText = "font-size:11px;color:#94a3b8;line-height:1.5;margin-bottom:14px;white-space:pre-line;";
    // v3.7.0: MOTOR ÖN-KONTROLÜ — popup açılır açılmaz aria2c durumu sorgulanır;
    // kuruluysa yeşil sürüm rozatı, değilse sarı kurulum komutu EN BAŞTA gösterilir
    try {
      sendMsg({ type: "IDM_TORRENT_PREFLIGHT" }).then((pf) => {
        if (!overlay.isConnected) return;
        if (pf && pf.ok && pf.installed) {
          eng.textContent = `${TORRENT_I18N.engine}\n✔ ${pf.version || "aria2c"}`;
          eng.style.color = "#34d399";
        } else if (pf && pf.ok && !pf.installed) {
          eng.textContent = `⚠️ aria2c\n${TORRENT_I18N.autoInstall || "aria2c — kurulum otomatik yapılacak"}\nℹ️ WebSeed`;
          eng.style.color = "#fbbf24";
        }
      });
    } catch (_e) {}
    const row = document.createElement("div");
    row.style.cssText = "display:flex;gap:10px;justify-content:flex-end;";
    const noBtn = document.createElement("button");
    noBtn.textContent = TORRENT_I18N.no;
    noBtn.style.cssText = "padding:9px 16px;border-radius:9px;border:1px solid #475569;background:#1e293b;color:#e2e8f0;font-size:12px;font-weight:600;cursor:pointer;";
    // v3.14.2: 'Dosyayı İndir' — torrentun İÇERİĞİNİ değil, .torrent DOSYASININ kendisini
    // normal IDM indirme akışıyla indirir (kullanıcı istegi: 'Hayır'ın solunda dursun)
    const fileBtn = document.createElement("button");
    fileBtn.textContent = TORRENT_I18N.file || "Dosyayı İndir";
    fileBtn.style.cssText = "padding:9px 16px;border-radius:9px;border:1px solid #334155;background:#0b1220;color:#7dd3fc;font-size:12px;font-weight:600;cursor:pointer;";
    const yesBtn = document.createElement("button");
    yesBtn.textContent = TORRENT_I18N.yes;
    yesBtn.style.cssText = "padding:9px 16px;border-radius:9px;border:none;background:linear-gradient(135deg,#2563eb,#1d4ed8);color:#fff;font-size:12px;font-weight:700;cursor:pointer;box-shadow:0 6px 18px rgba(37,99,235,.35);";
    row.appendChild(fileBtn);
    row.appendChild(noBtn);
    row.appendChild(yesBtn);
    card.appendChild(hdr);
    card.appendChild(ask);
    card.appendChild(nm);
    card.appendChild(eng);
    card.appendChild(row);
    overlay.appendChild(card);
    const style = document.createElement("style");
    style.textContent = "@keyframes idmtp-fade{from{opacity:0}to{opacity:1}}@keyframes idmtp-pop{from{transform:scale(.94);opacity:0}to{transform:scale(1);opacity:1}}";
    card.style.animation = "idmtp-pop .18s ease-out";
    overlay.appendChild(style);
    const close = () => {
      try { overlay.remove(); } catch (_e) {}
      document.removeEventListener("keydown", onKey, true);
    };
    const onKey = (ev) => {
      if (ev.key === "Escape") { ev.stopPropagation(); close(); }
    };
    overlay.addEventListener("click", (ev) => {
      if (ev.target === overlay) close();
    });
    document.addEventListener("keydown", onKey, true);
    noBtn.addEventListener("click", () => {
      // v3.14.2: 'Hayır' -> arka plana bildir; bu URL 10 sn boyunca torrent popup'ına
      // düşmesin (döngü koruması), tarayıcı kendi davranışıyla devam etsin
      try { sendMsg({ type: "IDM_TORRENT_DECLINE", url: href }); } catch (_e) {}
      close();
      try { location.href = href; } catch (_e) {}
    });
    // v3.14.2: 'Dosyayı İndir' -> .torrent DOSYASININ kendisi normal IDM indirmesine
    // gider (İÇERİK değil!) — daemon /api/download köprüsü üzerinden
    fileBtn.addEventListener("click", async () => {
      yesBtn.disabled = true;
      noBtn.disabled = true;
      fileBtn.disabled = true;
      ask.textContent = "⏳ …";
      let res = null;
      try { res = await sendMsg({ type: "IDM_TORRENT_FILE_DOWNLOAD", href, referer: location.href }); } catch (_e) {}
      if (res && res.ok) {
        close();
      } else {
        const off = res && res.offline;
        ask.textContent = off ? TORRENT_I18N.fail : ((res && (res.message || res.error)) || TORRENT_I18N.fail);
        ask.style.color = "#f87171";
        ask.style.whiteSpace = "pre-line";
        yesBtn.disabled = false;
        noBtn.disabled = false;
        fileBtn.disabled = false;
      }
    });
    yesBtn.addEventListener("click", async () => {
      yesBtn.disabled = true;
      noBtn.disabled = true;
      ask.textContent = "⏳ …";
      const sendRes = await idmSendTorrentToDaemon(href, kind);
      if (sendRes && sendRes.ok) {
        ask.textContent = TORRENT_I18N.sent;
        ask.style.color = "#34d399";
        setTimeout(close, 1400);
      } else {
        // v3.7.0: GERÇEK nedeni göster — köprü çevrimdışıysa 'köprüye ulaşılamadı',
        // motor hata verdiyse SADECE motor mesajı (yanıltıcı 'köprü yok' metni yok)
        const off = sendRes && sendRes.offline;
        const detail = (sendRes && sendRes.message) ? sendRes.message : "";
        ask.textContent = off ? TORRENT_I18N.fail : (detail || TORRENT_I18N.fail);
        ask.style.color = "#f87171";
        ask.style.whiteSpace = "pre-line";
        yesBtn.disabled = false;
        noBtn.disabled = false;
      }
    });
    (document.documentElement || document.body).appendChild(overlay);
    torrentPopupEl = overlay;
    yesBtn.focus();
  }

  // v3.5.0: alt seviye (IIFE dışı) dinleyiciler de aynı pencereyi kullanabilsin
  window.__idmLinuxTorrentPopup = idmTorrentPopup;

  let torrentPopupEl = null;

  async function idmSendTorrentToDaemon(href, kind) {
    // v3.6.0 KÖK DÜZELTME: içerik betiği 127.0.0.1'e DOĞRUDAN POST atmıyor. Sayfa kaynağından
    // (örn. https://thepiratebay.org) yapılan POST, CORS + daemon'un güvenlik kalkanı
    // (Untrusted origin) nedeniyle HEP başarısız oluyordu -> ekranda 'Torrent başlatılamadı —
    // IDM Linux köprüsüne ulaşılamadı' hatası (kullanıcı ekran görüntüsü). İstek artık ARKA
    // PLAN servisi üzerinden gider; .torrent dosyasını da köprünün kendisi indirir (sayfa
    // CSP/CORS engeline takılmaz, çerezler de köprüye taşınır).
    try {
      const res = await sendMsg({ type: "IDM_TORRENT_SEND", href, kind, referer: location.href });
      if (res && typeof res === "object") {
        if (res.ok) return { ok: true, message: res.message || "" };
        return { ok: false, message: String(res.message || res.error || "") };
      }
      return { ok: false, message: "" };
    } catch (_relayErr) {
      // son çare (yerel dosya sayfaları vb.): doğrudan POST — köprü reddederse gerçek neden döner
      try {
        let body = null;
        if (kind === "magnet") {
          body = { magnet: href, source: "ext-popup-magnet" };
        } else {
          const res2 = await fetch(href, { credentials: "include" });
          if (!res2.ok) return { ok: false, message: ".torrent dosyası tarayıcıdan indirilemedi (CSP/CORS)." };
          const buf = new Uint8Array(await res2.arrayBuffer());
          let bin = "";
          for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
          body = { torrent_base64: btoa(bin), source: "ext-popup-torrent" };
        }
        let cfg = {};
        try { cfg = await extApi.storage.local.get(["httpPort"]); } catch (_e2) {}
        const port = cfg.httpPort || 17802;
        const resp = await fetch(`http://127.0.0.1:${port}/api/torrent/download`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Origin: `http://127.0.0.1:${port}` },
          body: JSON.stringify(body),
        });
        const j = await resp.json().catch(() => null);
        if (j && j.ok) return { ok: true, message: j.message || "" };
        return { ok: false, message: (j && (j.message || j.error)) || "" };
      } catch (_e3) {
        return { ok: false, message: "" };
      }
    }
  }

  // v3.5.0: HERHANGİ bir magnet:/.torrent/ed2k:// bağlantısına tıklamada onay popup'u (yakalama fazı)
  document.addEventListener(
    "click",
    (e) => {
      try {
        if (extDisabled) return;                       // pasif mod: tarayıcı kendi indirir
        if (e.button !== 0 || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
        // v3.13.0: shadow DOM kökündeki <a> da yakalanır (composedPath) —
        // TPB gibi sitelerde retarget nedeniyle magnet tıklaması kaçırılıyordu.
        let a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
        if (!a && typeof e.composedPath === "function") {
          for (const el of e.composedPath()) {
            if (el && el.tagName === "A" && el.getAttribute && el.getAttribute("href")) {
              a = el;
              break;
            }
          }
        }
        if (!a) return;
        const href = (a.getAttribute("href") || "").trim();
        const low = href.toLowerCase();
        // v3.13.0: TÜM magnet URİ'leri (yalnız magnet:?xt= değil — TPB magnetleri
        // dn=/tr= ile başlayabilir) + .torrent + ed2k://
        const isMagnet = low.startsWith("magnet:");
        const isTorrent = /\.torrent(\?|#|$)/i.test(low);
        // v3.7.0: eD2K bağlantıları — tarayıcı 'about:blank#blocked' ile engeller;
        // biz yakalayıp eMule motoruna iletiyoruz (tüm ed2k:// biçimleri)
        const isEd2k = low.startsWith("ed2k://");
        if (!isMagnet && !isTorrent && !isEd2k) return;
        e.preventDefault();
        e.stopPropagation();
        if (isEd2k) {
          idmEd2kPopup(href);
        } else {
          idmTorrentPopup(href, isMagnet ? "magnet" : "torrent");
        }
      } catch (_e) {}
    },
    true
  );

  // -------------------------------------------------------------------------
  // 1. Windows IDM Klavye Kısayolları (Alt = Atla, Insert = Zorla Yakala)
  // -------------------------------------------------------------------------
  window.addEventListener(
    "keydown",
    (e) => {
      if (e.key === "Insert") insertHeld = true;
    },
    true
  );
  window.addEventListener(
    "keyup",
    (e) => {
      if (e.key === "Insert") insertHeld = false;
    },
    true
  );
  window.addEventListener(
    "mousedown",
    (e) => {
      if (e.altKey || insertHeld) {
        sendMsg({
          type: "IDM_SET_MODIFIER",
          altKey: Boolean(e.altKey),
          insertKey: Boolean(insertHeld)
        });
      }
    },
    true
  );

  // v3.5.0 NOT: eski 'magnet tıkla -> doğrudan gönder' yakalayıcısı KALDIRILDI.
  // Artık magnet:/.torrent bağlantıları yukarıdaki ŞIK ONAY PENCERESİNDEN geçer;
  // kullanıcı onaylarsa daemon /api/torrent/download ile aria2c motoru başlar.

  // -------------------------------------------------------------------------
  // 2. Sayfadaki Ana <video> Oynatıcısını Algılama
  // -------------------------------------------------------------------------
  function findBestVideoElement() {
    const videos = Array.from(document.querySelectorAll("video"));
    // v3.1.0 BELLEK/CPU KORUMASI: 'document.querySelectorAll("*")' her 1.2 sn'de YouTube
    // gibi dev sayfalarda on binlerce düğümü tarayıp sistemi kilitliyordu (kullanıcı çökme
    // raporu). Artık yalnızca oyuncu konteynerleri hedeflenir + gölge taraması 5 sn'de bir.
    try {
      const nowMs = Date.now();
      if (!findBestVideoElement._shadowHosts || nowMs - (findBestVideoElement._shadowTs || 0) > 5000) {
        findBestVideoElement._shadowTs = nowMs;
        findBestVideoElement._shadowHosts = document.querySelectorAll(
          "main, header, section, [id*='player' i], [class*='player' i], [id*='video' i], [class*='video' i], ytd-player, #movie_player"
        );
      }
      for (const el of findBestVideoElement._shadowHosts) {
        if (el && el.shadowRoot) {
          for (const sv of el.shadowRoot.querySelectorAll("video")) {
            videos.push(sv);
          }
        }
      }
    } catch (_e) {}

    let best = null;
    let bestArea = 0;
    for (const v of videos) {
      const rect = v.getBoundingClientRect();
      if (rect.width < 180 || rect.height < 100) continue;
      const style = window.getComputedStyle(v);
      if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity) === 0) {
        continue;
      }
      // Görünür video alanı hesabı
      const area = rect.width * rect.height;
      const hasSource =
        Boolean(v.currentSrc || v.src) ||
        v.readyState >= 1 ||
        v.querySelector("source") !== null ||
        capturedNetworkCount > 0;
      if (hasSource && area > bestArea) {
        bestArea = area;
        best = v;
      }
    }
    return best;
  }

  const ABYSS_IFRAME_HOSTS = /(^|\.)(abyss\.to|abyssplayer\.com|abysscdn\.com|embedplayabyss\.top|short\.icu)$/i;
  const PLAYER_IFRAME_HOSTS = /(^|\.)(dailymotion\.com|dai\.ly|ok\.ru|vk\.com|vk\.ru|vkvideo\.ru|sibnet\.ru|vidmoly|molystream|hdplayer|streamin\.|cda\.pl|rutube\.ru)/i;

  function collectDomMediaStreams() {
    const out = [];
    const seen = new Set();
    for (const hs of hookedStreams) {
      if (hs && hs.url && !seen.has(hs.url)) {
        seen.add(hs.url);
        out.push(hs);
      }
    }
    for (const v of document.querySelectorAll("video, audio")) {
      const srcs = [v.currentSrc, v.src];
      for (const s of v.querySelectorAll("source")) {
        srcs.push(s.src);
      }
      for (const u of srcs) {
        if (u && u.startsWith("http") && !seen.has(u)) {
          seen.add(u);
          out.push({ url: u, mime: "video/mp4", size: null, referer: location.href, origin: location.origin });
        }
      }
      // v3.4.0 ALTYAZI YAKALAMA: <track kind="subtitles/captions" src=...> öğeleri —
      // film sitelerinde altyazı AÇILMAMIŞ olsa bile player DOM'unda tanımlıdır.
      // Bar böylece altyazıları (Türkçe/İngilizce vb. etiketleriyle) anında listeler.
      for (const tr of v.querySelectorAll("track[src]")) {
        const kind = String(tr.getAttribute("kind") || "").toLowerCase();
        if (kind && !(kind === "subtitles" || kind === "captions")) continue;
        let tu = "";
        try { tu = new URL(tr.getAttribute("src"), location.href).href; } catch (_e) { continue; }
        if (!tu.startsWith("http")) continue;
        const lbl = String(tr.getAttribute("label") || tr.getAttribute("srclang") || "").trim();
        rememberTrackLabel(tu, lbl || tr.getAttribute("srclang") || "");
        if (seen.has(tu)) continue;
        seen.add(tu);
        out.push({ url: tu, mime: "text/vtt", size: null, referer: location.href, origin: location.origin, sub_label: lbl });
      }
    }
    // v3.4.0: player sayfası <track>'leri video öğesi DIŞINDA da tanımlı olabilir
    // (sayfa genelinde TEK seferlik tarama — döngü içinde tekrarlanmaz, hafif).
    for (const tr of document.querySelectorAll("track[src][kind='subtitles'], track[src][kind='captions']")) {
      let tu = "";
      try { tu = new URL(tr.getAttribute("src"), location.href).href; } catch (_e) { continue; }
      if (!tu.startsWith("http")) continue;
      const lbl = String(tr.getAttribute("label") || tr.getAttribute("srclang") || "").trim();
      rememberTrackLabel(tu, lbl || tr.getAttribute("srclang") || "");
      if (seen.has(tu)) continue;
      seen.add(tu);
      out.push({ url: tu, mime: "text/vtt", size: null, referer: location.href, origin: location.origin, sub_label: lbl });
    }
    // v3.6.0 ALTYAZI HTML/JAVA SCRİPT TARAMASI: jwplayer/artplayer/videojs gibi oyuncular
    // altyazıyı <track> OLMADAN JS konfigürasyonunda tutar (file:"//cdn/x/tr.vtt",
    // captions:[{track:"...srt"}]). Sayfa kaynağı üzerinde TEK geçişli, sınırlı ve
    // kısılmış (5 sn) tarama — performans korunur, film sitelerinde altyazılar artık
    // kaçmaz (kullanıcı raporu: 'altyazı oldukları halde idm bar bulamıyor').
    try {
      const nowScan = Date.now();
      if (!collectDomMediaStreams._subScanTs || nowScan - collectDomMediaStreams._subScanTs > 5000) {
        collectDomMediaStreams._subScanTs = nowScan;
        const html = document.documentElement.innerHTML;
        if (html && html.length < 3000000) { // 3 MB üstü sayfalarda tarama yapma (bellek koruması)
          const re = /https?:\/\/[^"'\s\\<>]{8,300}?\.(vtt|srt|ass|ssa|ttml|dfxp|smi|sami|sbv|sub)(\?[^"'\s\\<>]*)?/gi;
          let m2;
          let guard = 0;
          while ((m2 = re.exec(html)) !== null && guard < 24) {
            guard += 1;
            const su = m2[0];
            if (seen.has(su)) continue;
            seen.add(su);
            out.push({ url: su, mime: "text/vtt", size: null, referer: location.href, origin: location.origin, sub_label: "" });
          }
        }
        // v3.7.1 PERFORMANCE RESOURCE TIMING taraması: oyuncu altyazıyı ÇOKTAN fetch
        // etse bile (fullhdfilmizlesene/rapidvid vb.) URL'i tarayıcının kaynak kaydında
        // durur — DOM'da <track> olmasa ve JS config'de görünmese bile yakalanır.
        try {
          const resEntries = performance.getEntriesByType("resource") || [];
          const reRes = /\.(vtt|srt|ass|ssa|ttml|dfxp|smi|sami|sbv|sub)(\?|#|$)/i;
          let guardRes = 0;
          for (let ri = resEntries.length - 1; ri >= 0 && guardRes < 12; ri -= 1) {
            const rname = String(resEntries[ri] && resEntries[ri].name || "");
            if (!rname || !rname.startsWith("http")) continue;
            if (!reRes.test(rname)) continue;
            guardRes += 1;
            if (seen.has(rname)) continue;
            seen.add(rname);
            out.push({ url: rname, mime: "text/vtt", size: null, referer: location.href, origin: location.origin, sub_label: "" });
          }
        } catch (_resErr) {}
      }
    } catch (_subScanErr) {}

    // v3.1.0: oynatıcı IFRAME'lerini de kaynağa taşı — abyss.to gömülü film sitelerinde
    // (belgeselsemo vb.) iframe oynatıcının URL'si daemon'da Android protokolüyle çözülür.
    try {
      for (const fr of document.querySelectorAll("iframe[src]")) {
        let abs = "";
        try { abs = new URL(fr.getAttribute("src"), location.href).href; } catch (_e) { continue; }
        if (!abs.startsWith("http") || seen.has(abs)) continue;
        let host = "";
        try { host = new URL(abs).hostname; } catch (_e) { continue; }
        if (ABYSS_IFRAME_HOSTS.test(host)) {
          seen.add(abs);
          out.push({ url: "abyssif://" + abs, mime: "application/x-abyss", referer: location.href, origin: location.origin });
        } else if (PLAYER_IFRAME_HOSTS.test(host)) {
          seen.add(abs);
          out.push({ url: abs, mime: "text/html", referer: location.href, origin: location.origin });
        }
      }
    } catch (_e) {}
    return out;
  }

  // -------------------------------------------------------------------------
  // 3. Orijinal IDM Tasarımlı Shadow DOM "Bu videoyu indir" Yüzen Barı
  // -------------------------------------------------------------------------
  function ensureVideoBarMounted() {
    if (!IS_TOP_FRAME) return; // v3.2.1: çift bar kök çözümü — alt çerçeve bar monte etmez
    if (barHost && shadow) {
      // Tam ekran moduna geçildiyse barı fullscreen kapsayıcısına taşı!
      const fsParent = document.fullscreenElement || document.documentElement;
      if (barHost.parentNode !== fsParent) {
        fsParent.appendChild(barHost);
      }
      return;
    }

    barHost = document.createElement("div");
    barHost.id = "__idm_linux_videobar_host__";
    barHost.style.cssText =
      "position:fixed !important; top:0 !important; left:0 !important; width:0 !important; height:0 !important; z-index:2147483647 !important; pointer-events:none !important;";
    shadow = barHost.attachShadow({ mode: "open" });

    shadow.innerHTML = `
      <style>
        * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Ubuntu, sans-serif; }
        .idm-bar-wrap {
          position: fixed;
          pointer-events: auto;
          display: none;
          flex-direction: column;
          align-items: flex-end;
          z-index: 2147483647;
          transition: opacity 0.18s ease;
          user-select: none;
        }
        .idm-bar-wrap.faded {
          opacity: 0.32;
        }
        .idm-bar-wrap:hover, .idm-bar-wrap.open {
          opacity: 1 !important;
        }
        .idm-pill {
          display: inline-flex;
          cursor: grab;
          align-items: center;
          background: linear-gradient(180deg, #eff6ff 0%, #dbeafe 52%, #bfdbfe 100%);
          border: 1px solid #3b82f6;
          border-radius: 5px;
          box-shadow: 0 3px 12px rgba(15, 23, 42, 0.38), inset 0 1px 0 #ffffff;
          height: 28px;
          overflow: hidden;
        }
        .idm-main-btn {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          padding: 0 10px 0 8px;
          height: 100%;
          border: none;
          background: transparent;
          color: #0f172a;
          font-size: 12px;
          font-weight: 600;
          cursor: pointer;
          white-space: nowrap;
        }
        .idm-main-btn:hover {
          background: rgba(59, 130, 246, 0.16);
        }
        .idm-badge {
          background: #16a34a;
          color: #ffffff;
          font-size: 10px;
          font-weight: 700;
          padding: 1px 5px;
          border-radius: 3px;
        }
        .idm-caret {
          font-size: 10px;
          color: #1d4ed8;
          margin-left: 2px;
        }
        .idm-close-btn {
          border: none;
          border-left: 1px solid #93c5fd;
          background: transparent;
          color: #475569;
          width: 24px;
          height: 100%;
          font-size: 14px;
          line-height: 1;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          justify-content: center;
        }
        .idm-close-btn:hover {
          background: #fee2e2;
          color: #dc2626;
        }
        .idm-menu {
          margin-top: 4px;
          min-width: 290px;
          max-width: 390px;
          max-height: 330px;
          overflow-y: auto;
          background: #0f172a;
          color: #f8fafc;
          border: 1px solid #334155;
          border-radius: 7px;
          box-shadow: 0 10px 28px rgba(0, 0, 0, 0.55);
          padding: 6px;
          display: none;
        }
        .idm-menu.visible {
          display: block;
        }
        .idm-mode-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 8px;
          padding: 5px 8px;
          font-size: 11px;
          color: #94a3b8;
          border-bottom: 1px solid #1e293b;
          margin-bottom: 4px;
        }
        .idm-mode-row select {
          background: #1e293b;
          color: #e2e8f0;
          border: 1px solid #334155;
          border-radius: 4px;
          font-size: 11px;
          padding: 2px 5px;
          cursor: pointer;
        }
        .idm-menu-hdr {
          font-size: 11px;
          font-weight: 700;
          color: #94a3b8;
          padding: 4px 8px 6px;
          border-bottom: 1px solid #1e293b;
          margin-bottom: 4px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .idm-item {
          width: 100%;
          text-align: left;
          background: transparent;
          border: none;
          color: #f1f5f9;
          padding: 7px 9px;
          border-radius: 5px;
          font-size: 12px;
          cursor: pointer;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 8px;
        }
        .idm-item:hover {
          background: #0284c7;
          color: #ffffff;
        }
        .idm-item-tag {
          font-size: 10px;
          font-weight: 700;
          padding: 2px 6px;
          border-radius: 4px;
          background: #1e293b;
          color: #38bdf8;
          flex-shrink: 0;
        }
        .idm-item:hover .idm-item-tag {
          background: rgba(255, 255, 255, 0.2);
          color: #ffffff;
        }
        .idm-status-row {
          padding: 10px;
          font-size: 12px;
          color: #cbd5e1;
          text-align: center;
        }
        .idm-footer-btn {
          width: 100%;
          border: none;
          border-top: 1px solid #1e293b;
          margin-top: 4px;
          padding: 6px 8px 4px;
          background: transparent;
          color: #94a3b8;
          font-size: 11px;
          cursor: pointer;
          text-align: right;
        }
        .idm-footer-btn:hover {
          color: #f87171;
        }
      </style>
      <div class="idm-bar-wrap" id="wrap">
        <div class="idm-pill">
          <button class="idm-main-btn" id="mainBtn" title="Internet Download Manager ile bu videoyu indir">
            <svg width="16" height="16" viewBox="0 0 128 128">
              <circle cx="54" cy="56" r="44" fill="#0284c7" stroke="#bae6fd" stroke-width="5"/>
              <path d="M14 56 H94 M54 12 V100" stroke="#e0f2fe" stroke-width="4" opacity="0.65"/>
              <path d="M74 44 H98 V78 H115 L86 114 L57 78 H74 Z" fill="#22c55e" stroke="#ffffff" stroke-width="4"/>
            </svg>
            <span id="btnLabel">Bu videoyu indir</span>
            <span class="idm-badge" id="badge">IDM</span>
            <span class="idm-caret">▾</span>
          </button>
          <button class="idm-close-btn" id="closeBtn" title="Bu sayfada gizle">×</button>
        </div>
        <div class="idm-menu" id="menu">
          <div class="idm-menu-hdr">
            <span id="menuTitle">Kalite Seçin (IDM)</span>
            <span id="refreshBtn" style="cursor:pointer;color:#38bdf8;" title="Yeniden tara">↻ Yenile</span>
          </div>
          <div class="idm-mode-row" id="modeRow" style="display:none;">
            <span>Yayın Modu (HLS/m3u8):</span>
            <select id="hlsMode" title="DVR: yayın başından sonuna kayıt | Canlı: şu andan itibaren kayıt">
              <option value="dvr">DVR — baştan kayıt</option>
              <option value="live">Canlı — şu andan</option>
              <option value="vod">Statik liste (VOD)</option>
            </select>
          </div>
          <div class="idm-mode-row" style="display:flex;flex-wrap:wrap;gap:5px;">
            <span>Bağlantı:</span><select id="networkTransport" title="Tarayıcı modu kaynak sekmesi açıkken çalışır; normal bağlantıya otomatik dönmez.">
              <option value="direct">Doğrudan</option><option value="browser">Tarayıcı bağlantısıyla — VPN/oturum</option>
            </select>
            <label id="routePinRow" style="display:none;font-size:10px;white-space:normal;">
              <input type="checkbox" id="routePin" checked>Çıkış kontrolü (api.ipify.org). VPN kill-switch yerine geçmez.
            </label>
          </div>
          <div id="menuList"></div>
          <button class="idm-footer-btn" id="excludeSiteBtn">Bu sitede video barını devre dışı bırak</button>
        </div>
      </div>
    `;

    (document.fullscreenElement || document.documentElement).appendChild(barHost);

    uiRefs = {
      wrap: shadow.getElementById("wrap"),
      mainBtn: shadow.getElementById("mainBtn"),
      btnLabel: shadow.getElementById("btnLabel"),
      badge: shadow.getElementById("badge"),
      closeBtn: shadow.getElementById("closeBtn"),
      menu: shadow.getElementById("menu"),
      menuList: shadow.getElementById("menuList"),
      networkTransport: shadow.getElementById("networkTransport"),
      routePin: shadow.getElementById("routePin"),
      routePinRow: shadow.getElementById("routePinRow"),
      hlsMode: shadow.getElementById("hlsMode"),
      modeRow: shadow.getElementById("modeRow"),
      menuTitle: shadow.getElementById("menuTitle"),
      refreshBtn: shadow.getElementById("refreshBtn"),
      excludeSiteBtn: shadow.getElementById("excludeSiteBtn")
    };

    uiRefs.networkTransport.addEventListener("change", () => {
      uiRefs.routePinRow.style.display = uiRefs.networkTransport.value === "browser" ? "block" : "none";
    });

    // v3.2.1 → v3.9.0: bar fareyle SERBEST taşınabilir — EŞİKLİ sürükleme.
    // KÖK NEDEN: pill'in tamamı bir <button> olduğu için eski kod 'closest(button)'
    // kontrolüyle HER TIKLAMADA erken dönüyordu → sürükleme fiilen HİÇ çalışmıyordu.
    // Yeni mantık: pointerdown pill'in HERHANGİ yerinde (closeBtn hariç) takibi başlatır;
    // 6 px'i aşan hareket = SÜRÜKLEME (canlı konum güncellemesi + sonraki click bastırılır);
    // aşmayan = normal TIKLAMA (dropdown açılır). Konum siteye özel kalıcıdır.
    const pillEl = shadow.querySelector(".idm-pill");
    if (pillEl) {
      let dragJustHappened = false;
      pillEl.addEventListener("pointerdown", (e) => {
        try {
          if (e.target.closest && e.target.closest("#closeBtn")) return; // kapatma butonu hariç
          if (e.button !== 0) return;
          const startX = e.clientX;
          const startY = e.clientY;
          const r0 = uiRefs.wrap.getBoundingClientRect();
          const ox = startX - r0.left;
          const oy = startY - r0.top;
          let dragging = false;
          pillEl.style.cursor = "grabbing";
          const move = (ev2) => {
            const dx = ev2.clientX - startX;
            const dy = ev2.clientY - startY;
            if (!dragging && Math.hypot(dx, dy) < 6) return; // eşik: mikro titremeler tıklama sayılır
            dragging = true;
            dragJustHappened = true;
            barUserPos = {
              x: Math.max(4, Math.min(window.innerWidth - 80, r0.left + dx)),
              y: Math.max(4, Math.min(window.innerHeight - 40, r0.top + dy)),
            };
            uiRefs.wrap.style.left = `${barUserPos.x}px`;
            uiRefs.wrap.style.top = `${barUserPos.y}px`;
            try { e.preventDefault(); } catch (_pe) {}
          };
          const up = () => {
            window.removeEventListener("pointermove", move);
            window.removeEventListener("pointerup", up);
            pillEl.style.cursor = "grab";
            if (dragging && barUserPos) {
              persistBarPos(barUserPos);
              // click olayının dropdown açmasını ENGELLE (sürükleme bitti, tıklama değildi)
              setTimeout(() => { dragJustHappened = false; }, 120);
            }
          };
          window.addEventListener("pointermove", move, { passive: false });
          window.addEventListener("pointerup", up);
        } catch (_dErr) {}
      });
      // sürükleme bitimindeki hayali click'i yut
      pillEl.addEventListener("click", (e) => {
        if (dragJustHappened) {
          e.preventDefault();
          e.stopPropagation();
          dragJustHappened = false;
        }
      }, true);
    }

    uiRefs.mainBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleFormatDropdown(false);
    });

    uiRefs.refreshBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      cachedFormats = null;
      pendingProbePromise = null;
      loadFormatsIntoMenu(true);
    });

    uiRefs.closeBtn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      dismissedForPage = true;
      closeDropdown();
      uiRefs.wrap.style.display = "none";
    });

    uiRefs.excludeSiteBtn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const host = location.hostname.toLowerCase();
      const info = await sendMsg({ type: "IDM_POPUP_STATUS" });
      const cur = (info && info.state && info.state.excluded_domains) || [];
      if (!cur.includes(host)) cur.push(host);
      await sendMsg({ type: "IDM_UPDATE_CONFIG", config: { excluded_domains: cur } });
      videoBarAllowed = false;
      uiRefs.wrap.style.display = "none";
    });

    document.addEventListener("click", (ev) => {
      if (dropdownOpen && barHost && !ev.composedPath().includes(barHost)) {
        closeDropdown();
      }
    });
  }

  // v3.9.0: bar konumu siteye özel KALICI (chrome.storage.local) — sayfa/SPA geçişlerinde
  // korunur, kullanıcı barı bir kez taşıyıp bir daha uğraşmaz
  function persistBarPos(pos) {
    try {
      const k = "barPos::" + location.hostname;
      const obj = {};
      obj[k] = { x: Math.round(pos.x), y: Math.round(pos.y) };
      extApi.storage.local.set(obj, () => { void extApi.runtime.lastError; });
    } catch (_e) {}
  }

  function restoreBarPos() {
    try {
      const k = "barPos::" + location.hostname;
      extApi.storage.local.get([k], (r) => {
        const p = r && r[k];
        if (p && typeof p.x === "number" && typeof p.y === "number") {
          barUserPos = {
            x: Math.max(4, Math.min(window.innerWidth - 80, p.x)),
            y: Math.max(4, Math.min(window.innerHeight - 40, p.y)),
          };
          if (uiRefs && uiRefs.wrap) {
            uiRefs.wrap.style.left = `${barUserPos.x}px`;
            uiRefs.wrap.style.top = `${barUserPos.y}px`;
          }
        }
      });
    } catch (_e) {}
  }

  function closeDropdown() {
    dropdownOpen = false;
    if (uiRefs) {
      uiRefs.menu.classList.remove("visible");
      uiRefs.wrap.classList.remove("open");
    }
  }

  async function toggleFormatDropdown(forceOpen) {
    if (!IS_TOP_FRAME) return; // v3.2.1: dropdown da yalnız üst çerçevede
    ensureVideoBarMounted();
    if (dropdownOpen && !forceOpen) {
      closeDropdown();
      return;
    }
    dropdownOpen = true;
    uiRefs.menu.classList.add("visible");
    uiRefs.wrap.classList.add("open");
    await loadFormatsIntoMenu();
  }

  function fetchFormatsShared(forceRefresh = false) {
    if (!forceRefresh && cachedFormats && cachedProbeUrl === location.href && cachedFormats.length > 0) {
      return Promise.resolve({ ok: true, formats: cachedFormats });
    }
    if (!forceRefresh && pendingProbePromise && cachedProbeUrl === location.href) {
      return pendingProbePromise;
    }
    cachedProbeUrl = location.href;
    const domStreams = collectDomMediaStreams();
    pendingProbePromise = sendMsg({
      type: "IDM_PROBE_VIDEO",
      pageUrl: location.href,
      domStreams,
      biliCid: (() => {
        // v2.9.5: bilibili cid'yi sayfadan oku (view API 412 verse bile playurl çalışsın)
        if (!/bilibili\.com|b23\.tv/.test(location.host)) return "";
        try {
          const m = document.documentElement.innerHTML.match(/"cid"\s*:\s*(\d{4,})/);
          return m ? m[1] : "";
        } catch (_e) { return ""; }
      })(),
      forceRefresh: Boolean(forceRefresh)
    }).then((res) => {
      pendingProbePromise = null;
      if (res && res.ok) {
        const pageTitle = (res.title || document.title || "video").trim();
        const formats = Array.isArray(res.formats) ? res.formats.slice() : [];
        if (formats.length === 0 && domStreams.length > 0) {
          formats.push({
            id: "dom_0",
            label: "Mevcut Video Akışı (MP4 • Doğrudan)",
            ext: "mp4",
            delivery: "direct",
            direct_url: domStreams[0].url,
            source_url: domStreams[0].url
          });
        }
        if (formats.length > 0) {
          cachedFormats = formats.map((f) => Object.assign({}, f, { _title: pageTitle }));
        }
        // v3.9.0: bar HAZIR oldugunda rozet kaynak sayısını gösterir — kullanıcı
        // tıklamadan önce 'kaç kaynak bulundu' bilir (otomatik tespit göstergesi)
        try {
          if (uiRefs && uiRefs.badge) {
            const nSub = formats.filter((f) => f.delivery === "subs" || f.delivery === "yt_subs").length;
            const nVid = formats.length - nSub;
            uiRefs.badge.textContent = nVid > 0 ? `IDM · ${nVid}` : (nSub > 0 ? `CC · ${nSub}` : "IDM");
          }
        } catch (_bErr) {}
        lastPrefetchCount = Math.max(lastPrefetchCount, domStreams.length);
        probeMeta = {
          isLive: Boolean(res.is_live),
          isDvr: Boolean(res.is_dvr),
          drm: Boolean(res.drm),
          ytdlpMissing: Boolean(res.ytdlp_missing),
          ytdlpUpdating: Boolean(res.ytdlp_updating),
          ytdlpPending: Boolean(res.ytdlp_pending), // v3.1.0: arka plan probe sürüyor
          // v3.4.0: abyss pasifken daemon'un yerelleştirilmiş aktivasyon notu (20 dil)
          abyssNote: String(res.abyss_note || ""),
          // v3.5.0: yerelleştirilmiş altyazı grup başlığı (altyazı varsa dolu)
          subsHeader: String(res.subs_header || "")
        };
        return { ok: true, formats: cachedFormats || [] };
      }
      return res || { ok: false };
    });
    return pendingProbePromise;
  }

  function triggerBackgroundPrefetch() {
    if (prefetchedUrl === location.href) return;
    prefetchedUrl = location.href;
    // Sayfada video görülür görülmez arka planda sessizce kaliteleri hazırla (0ms tıklama hızı!)
    setTimeout(() => {
      if (activeVideo && !cachedFormats) {
        fetchFormatsShared(false).catch(() => {});
      }
    }, 350);
  }

  // v3.0.0 SELF-HEALING BAR: oynatıcı geç açılırsa (SPA/film siteleri) yakalanan akışlar
  // bar İLK boş sonucu verdikten SONRA gelir. Artık yeni akış kaydı barı otomatik
  // yeniden tarar (debounce 1.5 sn, sayfa başına en fazla 5 kez — sel koruması).
  function scheduleEmptyReprobe(reason) {
    if (emptyAutoRetries >= 5) return;
    if (emptyReprobeTimer) clearTimeout(emptyReprobeTimer);
    emptyReprobeTimer = setTimeout(() => {
      emptyReprobeTimer = null;
      if (dismissedForPage || !videoBarAllowed) return;
      emptyAutoRetries += 1;
      cachedFormats = null;
      prefetchedUrl = "";
      const p = fetchFormatsShared(true);
      if (p && p.catch) p.catch(() => {});
      p.then((res) => {
        // dropdown açıksa listeyi anında tazele; değilse sessiz prefetch yeterli
        if (res && res.ok && (res.formats || []).length > 0 && dropdownOpen && uiRefs) {
          renderFormatItems(res.formats);
        }
      });
    }, 1500);
  }

  async function loadFormatsIntoMenu(forceRefresh = false) {
    if (!uiRefs) return;
    if (!forceRefresh && cachedFormats && cachedProbeUrl === location.href && cachedFormats.length > 0) {
      renderFormatItems(cachedFormats);
      return;
    }

    // v3.6.0: 'Kaliteler hazırlanıyor...' satırı CANLI geri sayım gösterir + promise asla
    // sonsuza dek askıda kalmaz (90 sn sigortası) — kullanıcı donmuş arayüz görmez.
    uiRefs.menuList.innerHTML = `<div class="idm-status-row">⚡ Kaliteler hazırlanıyor…</div>`;
    const _t0 = Date.now();
    const _tick = setInterval(() => {
      if (!uiRefs || !uiRefs.menuList || !uiRefs.menuList.isConnected) { clearInterval(_tick); return; }
      const row = uiRefs.menuList.querySelector(".idm-status-row");
      if (row && /^⚡ Kaliteler hazırlanıyor/.test(row.textContent || "")) {
        row.textContent = `⚡ Kaliteler hazırlanıyor… ${Math.round((Date.now() - _t0) / 1000)} sn`;
      } else {
        clearInterval(_tick);
      }
    }, 1000);
    let res;
    try {
      res = await Promise.race([
        fetchFormatsShared(forceRefresh),
        new Promise((rsl) => setTimeout(() => rsl({ ok: false, timedOut: true }), 90000)),
      ]);
    } finally {
      clearInterval(_tick);
    }

    if (!res || !res.ok) {
      // v2.9.7: köprü uyanıyor olabilir — 4 kez otomatik yeniden dene
      let retryOk = null;
      for (let i = 0; i < 4 && !retryOk; i++) {
        uiRefs.menuList.innerHTML = `<div class="idm-status-row">⚡ Köprü başlatılıyor, yeniden deneniyor… (${i + 1}/4)</div>`;
        await new Promise((r) => setTimeout(r, 2500));
        const rr = await fetchFormatsShared(true);
        if (rr && rr.ok && (rr.formats || []).length >= 0 && rr.formats) retryOk = rr;
      }
      if (retryOk) {
        renderFormatItems(retryOk.formats || []);
        return;
      }
      uiRefs.menuList.innerHTML = `<div class="idm-status-row">⚠️ IDM Köprü servisine ulaşılamadı.<br/>Kontrol Panelinden servisi başlatın.</div>`;
      return;
    }

    renderFormatItems(res.formats || []);
  }

  function renderFormatItems(formats) {
    if (!uiRefs) return;
    // v2.8.3: Mod seçici YALNIZCA gerçek canlı yayında görünür (YouTube VOD'unda DVR/canlı saçmalığı bitti)
    if (uiRefs.modeRow) {
      uiRefs.modeRow.style.display = probeMeta.isLive ? "" : "none";
      if (probeMeta.isLive) {
        uiRefs.hlsMode.value = probeMeta.isDvr ? "dvr" : "live";
      } else {
        uiRefs.hlsMode.value = "vod";
      }
    }
    if (!formats.length) {
      let msg = "Bu sayfada indirilebilir akış bulunamadı.";
      if (probeMeta.drm) {
        msg = "Bu yayın DRM (Widevine/FairPlay) ile korumalı görünüyor — yasal olarak indirilemez.";
      } else if (probeMeta.abyssNote) {
        // v3.4.0: abyss kaynakları algılandı ama abyss PASİF — link yerine aktivasyon notu
        msg = `💎 ${probeMeta.abyssNote}`;
      } else if (probeMeta.ytdlpPending) {
        msg = "⚡ Video motoru arka planda kaynakları çözüyor… Birkaç saniye içinde liste dolacak.";
      } else if (probeMeta.ytdlpUpdating) {
        msg = "⏳ Video motoru (yt-dlp) güncelleniyor… 1-2 dakika içinde 'Yenile'ye basın.";
      } else if (probeMeta.ytdlpMissing) {
        // v3.14.1: motor KÖPRÜ AÇILIŞINDA otomatik kurulur; kurulum 1-2 dk sürebilir.
        // Deneme sayısı 6->40 (40 x 30 sn = 20 dk tavan) — kurulum biter bitmez bar dolarsın.
        msg = "Video motoru (yt-dlp) arka planda otomatik kuruluyor… Bu işlem 1-2 dakika sürebilir; liste kendiliğinden dolacak.";
      } else {
        msg = "İndirilebilir akış bulunamadı — ↻ Yenile ile tekrar tarayın (sayfa oynatıcıyı henüz açmamış olabilir).";
      }
      uiRefs.menuList.innerHTML = `<div class="idm-status-row">${msg}</div>`;
      // v2.9.10/v3.0.0: motor kurulur/güncellenirken VE genel boş durumda bar KENDİ KENDİNİ tazeler
      // v3.6.0: arka plan probe 75 sn'ye kadar sürebildiği için pending deneme sınırı 10->40
      // (40 x 3 sn = 2 dk); her denemede satırda kalan süre de görünür, bar asla 'dondum' demez.
      if (probeMeta.ytdlpPending && emptyAutoRetries < 40) {
        // v3.1.0: arka plan probe'u bitince daemon IDM_MEDIA_UPDATED yayar; burada
        // ayrıca kısa arayla yoklarız (3 sn — YouTube ilk açılış bekleme süresi bitti)
        emptyAutoRetries += 1;
        setTimeout(() => { loadFormatsIntoMenu(true).catch(() => {}); }, 3000);
      } else if ((probeMeta.ytdlpUpdating || probeMeta.ytdlpMissing) && emptyAutoRetries < 40) {
        emptyAutoRetries += 1;
        setTimeout(() => { loadFormatsIntoMenu(true).catch(() => {}); }, probeMeta.ytdlpMissing ? 10000 : 30000);
      } else if (capturedNetworkCount > 0 && emptyAutoRetries < 5) {
        // v3.0.0: yakalanan akış VAR ama probe boş döndü -> kısa arayla otomatik yeniden dene
        emptyAutoRetries += 1;
        setTimeout(() => { loadFormatsIntoMenu(true).catch(() => {}); }, 8000);
      }
      return;
    }

    uiRefs.menuList.innerHTML = "";
    // v3.4.0: abyss pasif notu — sayfada BAŞKA kaynaklar da varken üstte bilgi satırı olarak
    // gösterilir (abyss linkleri zaten listeye GİRMEZ; not yalnızca bilgilendirme).
    if (probeMeta.abyssNote) {
      const noteRow = document.createElement("div");
      noteRow.className = "idm-status-row";
      noteRow.style.cssText = "color:#7dd3fc;font-size:11px;line-height:1.45;padding:6px 10px;text-align:left;";
      noteRow.textContent = `💎 ${probeMeta.abyssNote}`;
      uiRefs.menuList.appendChild(noteRow);
    }
    // v3.5.0: ALTYAZI GRUBU — video kaliteleri bittikten sonra altyazılar ayrı bölümde listelenir
    let subSepInserted = false;
    const insertSubSeparator = () => {
      if (subSepInserted) return;
      subSepInserted = true;
      const sep = document.createElement("div");
      sep.className = "idm-status-row";
      sep.style.cssText = "color:#a5b4fc;font-size:10px;font-weight:700;letter-spacing:.4px;padding:7px 10px 3px;text-align:left;opacity:.9;";
      sep.textContent = probeMeta.subsHeader || "📝 Altyazılar";
      uiRefs.menuList.appendChild(sep);
    };
    const isSubFmt = (f) => f && (f.delivery === "subs" || f.delivery === "yt_subs");
    const videoFmts = formats.filter((f) => !isSubFmt(f));
    const subFmts = formats.filter(isSubFmt);
    for (const fmt of [...videoFmts, ...subFmts]) {
      if (isSubFmt(fmt)) insertSubSeparator();
      const btn = document.createElement("button");
      btn.className = "idm-item";
      const labelSpan = document.createElement("span");
      // v3.9.0: altyazı satırlarında GERÇEK dosya boyutu gösterilir ('Türkçe · 52 KB')
      // — doğrulanmış altyazıların boyutu daemon'dan gelir; 0 bayt sürprizi imkânsız
      let labelText = fmt.label || "";
      if (isSubFmt(fmt) && fmt.filesize && Number(fmt.filesize) > 0) {
        const kb = Number(fmt.filesize) / 1024;
        labelText += kb >= 1024
          ? ` · ${(kb / 1024).toFixed(1)} MB`
          : ` · ${kb >= 10 ? Math.round(kb) : kb.toFixed(1)} KB`;
      }
      labelSpan.textContent = labelText;
      labelSpan.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
      const tagSpan = document.createElement("span");
      tagSpan.className = "idm-item-tag";
      tagSpan.textContent = (fmt.ext || "MP4").toUpperCase();

      btn.appendChild(labelSpan);
      btn.appendChild(tagSpan);

      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        uiRefs.btnLabel.textContent = "⚡ IDM açılıyor...";
        closeDropdown();

        const dlRes = await sendMsg({
          // A legacy background must reject browser mode, never silently send a direct download.
          type: uiRefs.networkTransport.value === "browser" ? "IDM_DOWNLOAD_VIDEO_BROWSER" : "IDM_DOWNLOAD_VIDEO",
          networkTransport: uiRefs.networkTransport.value,
          routePin: uiRefs.routePin.checked,
          pageUrl: location.href,
          title: fmt._title || document.title || "video",
          // v3.2.2: altyazı seçeneklerinde dosya adı 'Video [Altyazı Adı].srt' olsun
          // v3.5.0: yt_subs (YouTube) da aynı akıştan geçer + 'Otomatik Altyazı' öneki temizlenir
          customName: (fmt.delivery === "subs" || fmt.delivery === "yt_subs")
            ? `${(fmt._title || document.title || "video").replace(/\.(srt|vtt|ass|ssa|ttml)$/i, "")} [${String(fmt.label || "altyazı").replace(/^📝\s*(Otomatik\s*)?Altyaz[ıi]:\s*/, "").replace(/\s*\((SRT|VTT)\)\s*$/i, "")}].${String(fmt.ext || "vtt").toLowerCase()}`
            : "",
          ext: fmt.ext || "mp4",
          resolution: fmt.resolution || "",
          delivery: fmt.delivery || "direct",
          directUrl: fmt.direct_url || "",
          sourceUrl: fmt.source_url || location.href,
          formatSelector: fmt.format_selector || "",
          muxVideoUrl: fmt.mux_video_url || "",
          muxAudioUrl: fmt.mux_audio_url || "",
          muxVideoHeaders: fmt.mux_video_headers || {},
          muxAudioHeaders: fmt.mux_audio_headers || {},
          manifestText: fmt.manifest_text || "",
          abyssSlug: fmt.abyss_slug || "",
          abyssLabel: fmt.abyss_label || "",
          subLang: fmt.sub_lang || "",
          isHls: Boolean(fmt.is_hls),
          streamReferer: fmt.stream_referer || location.href,
          streamOrigin: fmt.stream_origin || "",
          streamUserAgent: fmt.stream_user_agent || "",
          filesize: fmt.filesize || null,
          filesizeExact: Boolean(fmt.filesize_exact),
          segmentUrls: fmt.segment_urls || [],
          manifestUrl: fmt.manifest_url || "",
          delivery: fmt.delivery || "",
          audioSegmentUrls: fmt.audio_segment_urls || [],
          hlsMode: (uiRefs.modeRow && uiRefs.modeRow.style.display === "none") ? "vod" : ((uiRefs.hlsMode && uiRefs.hlsMode.value) || "vod")
        });

        uiRefs.btnLabel.textContent = dlRes && dlRes.ok ? "✓ IDM'ye Gönderildi!" : "⚠️ Hata Oluştu";
        // v2.9.2: DRM reddi vb. daemon mesajını kullanıcıya NET göster (sessiz başarısızlık yok)
        if (dlRes && dlRes.error) {
          try { window.alert(String(dlRes.error)); } catch (_e) {}
        }
        setTimeout(() => {
          if (uiRefs) uiRefs.btnLabel.textContent = "Bu videoyu indir";
        }, 2500);
      });

      uiRefs.menuList.appendChild(btn);
    }
  }

  function updateBarPosition() {
    if (extDisabled) { if (barHost) barHost.style.display = "none"; return; }
    if (!videoBarAllowed || dismissedForPage) {
      if (uiRefs) uiRefs.wrap.style.display = "none";
      return;
    }

    // SPA sayfa geçişi kontrolü (örn: YouTube video değişimi)
    if (location.href !== lastPageHref) {
      lastPageHref = location.href;
      cachedFormats = null;
      pendingProbePromise = null;
      prefetchedUrl = "";
      dismissedForPage = false;
      emptyAutoRetries = 0; // v3.1.0: yeni sayfada otomatik tazeleme hakkı tazelensin
      lastPrefetchCount = 0;
      subNormSeen.clear(); // v3.9.0: yeni sayfanın altyazıları için tekilleştirme sıfır
      // v3.9.0 NOT: barUserPos ARTIK sıfırlanmaz — kullanıcı konumu site genelinde kalıcı
      // v3.1.0 SIZINTI FIXİ: önceki sayfanın yakalama tamponları temizlenir
      // (hookedStreams/seenUrlSet birikerek RAM şişirmesin)
      hookedStreams.length = 0;
      seenUrlSet.clear();
      subLabelMap.clear();
      closeDropdown();
    }

    // v3.2.1: bar YALNIZCA üst çerçevede yaşar — gömülü oynatıcının (abyss/film siteleri)
    // içindeki işlevsiz ikinci bar ARTIK hiç monte edilmez.
    if (!IS_TOP_FRAME) {
      if (uiRefs && !dropdownOpen) uiRefs.wrap.style.display = "none";
      return;
    }

    const vid = findBestVideoElement();
    activeVideo = vid;
    let anchor = vid;
    if (!anchor) {
      // v3.2.1: gömülü oynatıcı iframe'i — barı frame öğesinin HEMEN ÜSTÜNE çapala
      if (lastPlayerFrameEl && document.contains(lastPlayerFrameEl)) {
        anchor = lastPlayerFrameEl;
      } else {
        const cand = Array.from(document.querySelectorAll("iframe,embed,object")).find((el) => {
          const r = el.getBoundingClientRect();
          return r.width > 320 && r.height > 240;
        });
        if (cand) {
          lastPlayerFrameEl = cand;
          anchor = cand;
        }
      }
    }
    if (!anchor) {
      // v3.2.0 ok.ru / vk.ru / vkvideo.ru BARI KÖK ÇÖZÜM: bu sitelerde oynatıcı video
      // öğesini sitediği için (gömülü iframe/özel player) bar HİÇ görünmüyordu. Artık
      // sayfada HERHANGİ bir yakalanmış medya akışı varsa (webRequest / page-hook /
      // iframe bildirimi) bar görünürlük koşulundan bağımsız sağ üstte gösterilir.
      const haveStreams =
        capturedNetworkCount > 0 || hookedStreams.length > 0 || collectDomMediaStreams().length > 0;
      if (!haveStreams) {
        if (uiRefs && !dropdownOpen) uiRefs.wrap.style.display = "none";
        return;
      }
      triggerBackgroundPrefetch();
      ensureVideoBarMounted();
      const topPos = 14;
      const leftPos = Math.max(8, window.innerWidth - (uiRefs.wrap.offsetWidth || 185) - 14);
      uiRefs.wrap.style.display = "flex";
      uiRefs.wrap.style.top = `${Math.round(topPos)}px`;
      uiRefs.wrap.style.left = `${Math.round(leftPos)}px`;
      return;
    }

    triggerBackgroundPrefetch();
    ensureVideoBarMounted();
    // v3.2.1: kullanıcı barı taşıdıysa konumunu KORU (SPA geçişi sıfırlar)
    if (barUserPos) {
      uiRefs.wrap.style.display = "flex";
      uiRefs.wrap.style.top = `${Math.round(barUserPos.y)}px`;
      uiRefs.wrap.style.left = `${Math.round(barUserPos.x)}px`;
      return;
    }
    const rect = anchor.getBoundingClientRect();
    if (rect.bottom < 40 || rect.top > window.innerHeight - 40) {
      if (!dropdownOpen) uiRefs.wrap.style.display = "none";
      return;
    }

    // Videonun/oynatıcının HEMEN ÜSTÜNDE sağa hizalı (v3.2.1: iframe çapasında da aynı kural)
    const barH = uiRefs.wrap.offsetHeight || 30;
    const topPos = rect.top >= barH + 8 ? Math.max(6, rect.top - barH - 6) : Math.max(8, rect.top + 8);
    const rightEdge = Math.min(window.innerWidth - 8, rect.right - 6);
    const leftPos = Math.max(8, rightEdge - (uiRefs.wrap.offsetWidth || 185));

    uiRefs.wrap.style.display = "flex";
    uiRefs.wrap.style.top = `${Math.round(topPos)}px`;
    uiRefs.wrap.style.left = `${Math.round(leftPos)}px`;
  }

  function bumpActivity() {
    if (!uiRefs) return;
    uiRefs.wrap.classList.remove("faded");
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      if (uiRefs && !dropdownOpen) {
        uiRefs.wrap.classList.add("faded");
      }
    }, 3500);
  }

  // -------------------------------------------------------------------------
  // 4. "Sayfadaki Tüm Bağlantıları IDM ile İndir" Toplu Seçici Modalı
  // -------------------------------------------------------------------------
  function openBatchLinksModal() {
    const existing = document.getElementById("__idm_linux_batch_host__");
    if (existing) existing.remove();

    const linksMap = new Map();
    for (const a of document.querySelectorAll("a[href]")) {
      const href = a.href || "";
      if (!href.startsWith("http")) continue;
      if (!linksMap.has(href)) {
        const clean = href.split("?")[0].split("#")[0];
        const fname = decodeURIComponent(clean.substring(clean.lastIndexOf("/") + 1)) || a.textContent.trim().slice(0, 60) || href;
        const dot = fname.lastIndexOf(".");
        const ext = dot > 0 ? fname.substring(dot + 1).toUpperCase() : "LINK";
        linksMap.set(href, { url: href, filename: fname, ext });
      }
    }

    const allLinks = Array.from(linksMap.values());
    const host = document.createElement("div");
    host.id = "__idm_linux_batch_host__";
    host.style.cssText = "position:fixed;inset:0;z-index:2147483647;";
    const s = host.attachShadow({ mode: "open" });

    s.innerHTML = `
      <style>
        * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .backdrop {
          position: fixed; inset: 0; background: rgba(2, 6, 23, 0.72);
          display: flex; align-items: center; justify-content: center; padding: 20px;
        }
        .modal {
          width: 680px; max-width: 96vw; max-height: 82vh; background: #0f172a; color: #f8fafc;
          border: 1px solid #334155; border-radius: 10px; display: flex; flex-direction: column;
          box-shadow: 0 20px 50px rgba(0,0,0,0.65); overflow: hidden;
        }
        .hdr { padding: 14px 18px; background: #1e293b; font-weight: 700; font-size: 14px; display: flex; justify-content: space-between; }
        .toolbar { padding: 10px 18px; display: flex; gap: 8px; border-bottom: 1px solid #1e293b; flex-wrap: wrap; align-items: center; }
        .chip { background: #1e293b; color: #cbd5e1; border: 1px solid #334155; border-radius: 5px; padding: 4px 10px; font-size: 12px; cursor: pointer; }
        .chip:hover { background: #0284c7; color: #fff; }
        .filter-in { margin-left: auto; background: #020617; border: 1px solid #334155; color: #f8fafc; border-radius: 5px; padding: 5px 10px; font-size: 12px; }
        .list { flex: 1; overflow-y: auto; padding: 8px 18px; }
        .row { display: flex; align-items: center; gap: 8px; padding: 5px 4px; border-bottom: 1px solid #1e293b; font-size: 12px; }
        .ext { background: #1e293b; color: #38bdf8; font-weight: 700; font-size: 10px; padding: 2px 6px; border-radius: 4px; min-width: 44px; text-align: center; }
        .url { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #cbd5e1; }
        .ftr { padding: 12px 18px; background: #1e293b; display: flex; justify-content: flex-end; gap: 10px; }
        .btn { border: none; border-radius: 6px; padding: 8px 16px; font-size: 12px; font-weight: 600; cursor: pointer; }
        .btn-sec { background: #334155; color: #f8fafc; }
        .btn-pri { background: #16a34a; color: #ffffff; }
      </style>
      <div class="backdrop" id="bd">
        <div class="modal">
          <div class="hdr">
            <span>Sayfadaki Tüm Bağlantıları IDM ile İndir (${allLinks.length} bağlantı)</span>
            <span id="xBtn" style="cursor:pointer;">✕</span>
          </div>
          <div class="toolbar">
            <button class="chip" data-preset="files">Dosya & Arşivler</button>
            <button class="chip" data-preset="media">Video & Ses</button>
            <button class="chip" data-preset="all">Tümünü Seç</button>
            <button class="chip" data-preset="none">Temizle</button>
            <input class="filter-in" id="fInput" placeholder="Uzantı veya kelime filtrele (ör: .zip, .mp4)"/>
          </div>
          <div class="list" id="list"></div>
          <div class="ftr">
            <button class="btn btn-sec" id="cancelBtn">İptal</button>
            <button class="btn btn-pri" id="sendBtn">Seçilenleri IDM'ye Gönder</button>
          </div>
        </div>
      </div>
    `;
    document.documentElement.appendChild(host);

    const listEl = s.getElementById("list");
    const fInput = s.getElementById("fInput");
    const selected = new Set();

    const FILE_EXTS = new Set(["ZIP", "RAR", "7Z", "TAR", "GZ", "XZ", "ISO", "EXE", "MSI", "DEB", "RPM", "APPIMAGE", "PDF", "APK", "TORRENT"]);
    const MEDIA_EXTS = new Set(["MP4", "MKV", "WEBM", "AVI", "MOV", "FLV", "MP3", "FLAC", "M4A", "WAV"]);

    for (const item of allLinks) {
      if (FILE_EXTS.has(item.ext) || MEDIA_EXTS.has(item.ext)) {
        selected.add(item.url);
      }
    }

    function renderRows() {
      const q = fInput.value.trim().toLowerCase();
      listEl.innerHTML = "";
      for (const item of allLinks) {
        if (q && !item.url.toLowerCase().includes(q) && !item.filename.toLowerCase().includes(q)) continue;
        const row = document.createElement("label");
        row.className = "row";
        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = selected.has(item.url);
        cb.addEventListener("change", () => {
          if (cb.checked) selected.add(item.url);
          else selected.delete(item.url);
        });
        const extBadge = document.createElement("span");
        extBadge.className = "ext";
        extBadge.textContent = item.ext.slice(0, 7);
        const uSpan = document.createElement("span");
        uSpan.className = "url";
        uSpan.textContent = item.url;
        row.appendChild(cb);
        row.appendChild(extBadge);
        row.appendChild(uSpan);
        listEl.appendChild(row);
      }
    }

    s.querySelectorAll(".chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        const p = btn.getAttribute("data-preset");
        selected.clear();
        for (const item of allLinks) {
          if (p === "all") selected.add(item.url);
          else if (p === "files" && FILE_EXTS.has(item.ext)) selected.add(item.url);
          else if (p === "media" && MEDIA_EXTS.has(item.ext)) selected.add(item.url);
        }
        renderRows();
      });
    });

    fInput.addEventListener("input", renderRows);
    const close = () => host.remove();
    s.getElementById("xBtn").addEventListener("click", close);
    s.getElementById("cancelBtn").addEventListener("click", close);
    s.getElementById("sendBtn").addEventListener("click", async () => {
      const chosen = allLinks.filter((x) => selected.has(x.url));
      if (chosen.length > 0) {
        await sendMsg({
          type: "IDM_BATCH_DOWNLOAD",
          referer: location.href,
          links: chosen
        });
      }
      close();
    });

    renderRows();
  }

  // -------------------------------------------------------------------------
  // 5. Mesaj Dinleyici ve Gözlemciler
  // -------------------------------------------------------------------------
  extApi.runtime.onMessage.addListener((msg) => {
    if (!msg || !msg.type) return;
    if (msg.type === "IDM_MEDIA_UPDATED") {
      capturedNetworkCount = msg.count || 0;
      if (!cachedFormats || cachedFormats.length === 0) {
        prefetchedUrl = "";
        // v3.0.0 SELF-HEALING: yeni akış geldi ama bar boştu -> otomatik yeniden tara
        scheduleEmptyReprobe("media-updated");
      } else if (capturedNetworkCount > lastPrefetchCount && emptyAutoRetries < 8) {
        // v3.9.0 OTOMATİK TESPİT: sayfada YENİ kaynaklar belirdi (geç açılan oynatıcı/
        // altyazı) — kullanıcı tıklamadan ÖNCE liste tazelenir; tıklayınca hazır olur
        lastPrefetchCount = capturedNetworkCount;
        cachedFormats = null;
        prefetchedUrl = "";
        const p2 = fetchFormatsShared(true);
        if (p2 && p2.catch) p2.catch(() => {});
        p2.then((res2) => {
          if (res2 && res2.ok && (res2.formats || []).length > 0 && dropdownOpen && uiRefs) {
            renderFormatItems(res2.formats);
          }
        });
      }
      updateBarPosition();
      bumpActivity();
    } else if (msg.type === "IDM_OPEN_VIDEO_PICKER") {
      if (window === window.top) {
        ensureVideoBarMounted();
        uiRefs.wrap.style.display = "flex";
        uiRefs.wrap.style.top = "16px";
        uiRefs.wrap.style.left = `${Math.max(16, window.innerWidth - 340)}px`;
        toggleFormatDropdown(true);
      }
    } else if (msg.type === "IDM_OPEN_BATCH_MODAL" && window === window.top) {
      openBatchLinksModal();
    } else if (msg.type === "IDM_BG_SUBTITLE" && msg.url) {
      // v3.7.1: arka plan webRequest gözlemcisi bir altyazı dosyası gördü — film
      // sitelerindeki oyuncular altyazıyı worker/iframe içinden çekse bile kaçmaz.
      // yalnızca TEPE çerçeve kaydeder (çift kayıt olmasın).
      if (!IS_TOP_FRAME) return;
      let su = "";
      try { su = new URL(msg.url, location.href).href; } catch (_e) { return; }
      if (!su.startsWith("http")) return;
      // v3.9.0: normalize edilmiş tekilleştirme — aynı altyazının sorgu varyantları
      // (2 altyazı gösterip 3 satır basan hata) bar'da tek satıra iner
      const nk = normSubKey(su);
      if (subNormSeen.has(nk)) return;
      subNormSeen.add(nk);
      if (subNormSeen.size > 2000) subNormSeen.clear();
      seenUrlSet.add(su);
      if (seenUrlSet.size > 4000) seenUrlSet.clear();
      const lbl = enrichSubLabel(su, msg.label || "");
      rememberTrackLabel(su, lbl);
      sendMsg({
        type: "IDM_REGISTER_CAPTURED_STREAMS",
        streams: [{ url: su, mime: "text/vtt", size: null, referer: location.href, origin: location.origin, sub_label: lbl }],
      });
      capturedNetworkCount += 1;
      cachedFormats = null;
      lastPrefetchCount = 0; // yeni altyazı geldi — otomatik tarama hakkı tazelensin
      scheduleEmptyReprobe("bg-subtitle");
      bumpActivity();
    }
  });

  async function init() {
    const info = await sendMsg({
      type: "IDM_GET_TAB_INFO",
      hostname: location.hostname
    });
    if (info && info.ok) {
      videoBarAllowed = info.videoBarEnabled !== false;
      capturedNetworkCount = info.streamCount || 0;
      const st = info.state || {};
      if (st.online && st.idm_installed && st.capture_downloads !== false && location.hostname !== "127.0.0.1" && location.hostname !== "localhost") {
        blobBridgeReady = true;
        publishCaptureState();
      }
    }

    updateBarPosition();
    restoreBarPos(); // v3.9.0: siteye özel kalıcı bar konumu geri yüklenir
    // v3.1.0 ADAPTİF TARAMA: video görünene dek 1.2 sn, video yoksa 5 sn'ye yumuşar —
    // YouTube gibi ağır sayfalarda sürekli DOM gezmesi CPU'yu yormasın
    let idleTicks = 0;
    setInterval(() => {
      const had = Boolean(document.querySelector("video"));
      if (had) idleTicks = 0;
      else idleTicks += 1;
      if (idleTicks > 4 && idleTicks % 4 !== 0) return; // 5 tikte 1 çalış
      updateBarPosition();
    }, 1200);
    window.addEventListener("scroll", updateBarPosition, { passive: true });
    window.addEventListener("resize", updateBarPosition, { passive: true });
    window.addEventListener("mousemove", bumpActivity, { passive: true });
    document.addEventListener("fullscreenchange", updateBarPosition);
    window.addEventListener("yt-navigate-finish", () => {
      cachedFormats = null;
      pendingProbePromise = null;
      prefetchedUrl = "";
      emptyAutoRetries = 0;
      hookedStreams.length = 0;
      seenUrlSet.clear();
      setTimeout(updateBarPosition, 350);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();

// v2.8.6: background'tan gelen onay isteğini sayfada native confirm ile sor
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === "IDM_CONFIRM_UI") {
    const ok = window.confirm(msg.message || "İndirilsin mi?");
    sendResponse({ ok });
    return true;
  }
  // v3.14.2: arka plan, içerik-tipi torrent indirmesini yakaladı (filmix.gg/download/<id>
  // gibi '.torrent' ile bitmeyen dinamik URL'ler) — 'Torrent İndirme Onayı' popup'ını BURADA aç
  if (msg && msg.type === "IDM_SHOW_TORRENT_POPUP") {
    try {
      if (typeof window.__idmLinuxTorrentPopup === "function" && msg.url) {
        window.__idmLinuxTorrentPopup(msg.url, "torrent");
        sendResponse({ ok: true });
      } else {
        sendResponse({ ok: false });
      }
    } catch (e) {
      try { sendResponse({ ok: false }); } catch (_e) {}
    }
    return true;
  }
  return false;
});

// v2.8.6: .torrent dosyasına TIKLAYINCA onay al -> daemon'a base64 gönder (otomatik başlasın)
document.addEventListener("click", async (ev) => {
  try {
    if (extDisabled) return; // v2.9.3: pasif modda tarayıcı kendi indirir
    const a = ev.target.closest && ev.target.closest("a[href]");
    if (!a) return;
    const href = a.href || "";
    // v2.9.0 arena.ai: tarayıcı 401/auth diyaloğu açmasın — tıklama daemon'a gider
    if (/arena\.ai\//i.test(href) && /(\/api\/|\/cas\/|download)/i.test(href)) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
      idmPostDownload(href);
      return;
    }
    // v2.8.7 GOFILE tıklama yakalama — v3.13.0: ONAYSIZ OTOMATİK.
    // Daemon taze gerçek store linkini çözüp IDM'ye verir; tarayıcı indirmesi imkânsız.
    if (/gofile\.io\//i.test(href) && /(wt=|\/download\/)/i.test(href)) {
      ev.preventDefault();
      ev.stopImmediatePropagation();
      if (!gofileAsked.has(href)) {
        gofileAsked.add(href);
        if (gofileAsked.size > 100) gofileAsked.clear();
      }
      idmPostDownload(href);
      return;
    }
    if (!/\.torrent(\?|#|$)/i.test(href)) return;
    // v3.5.0: doğal window.confirm yerine ŞIK IDM Linux onay penceresi (yakalama fazındaki
    // genel yakalayıcı zaten bu tıklamayı alır; buraya düşmesi beklenmez — savunma amaçlı)
    ev.preventDefault();
    if (typeof window.__idmLinuxTorrentPopup === "function") {
      window.__idmLinuxTorrentPopup(href, "torrent");
    }
  } catch (e) {}
}, true);

// v2.9.1: arena.ai vb. HttpOnly/CORS korumalı dosyayı AYNI ORIGIN'den (CORS'suz) bizzat sayfa çeker
chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg && msg.type === "IDM_ASSIST_FETCH") {
    (async () => {
      try {
        const r = await fetch(msg.url, { credentials: "include", redirect: "follow" });
        if (!r.ok || !r.body) { sendResponse({ ok: false }); return; }
        const port = msg.httpPort || 17802;
        const base = `http://127.0.0.1:${port}`;
        const hdrs = { "Content-Type": "application/json", Origin: base };
        const post = async (bytes) => {
          let bin = "";
          for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
          await fetch(`${base}/api/assist/chunk`, { method: "POST", headers: hdrs, body: JSON.stringify({ id: msg.id, b64: btoa(bin) }) });
        };
        const reader = r.body.getReader();
        let buf = new Uint8Array(0);
        for (;;) {
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
        await fetch(`${base}/api/assist/done`, { method: "POST", headers: hdrs, body: JSON.stringify({ id: msg.id, ok: true }) });
        sendResponse({ ok: true });
      } catch (e) {
        try { sendResponse({ ok: false }); } catch (_e) {}
      }
    })();
    return true;
  }
  return false;
});

// Strict browser transport: only extension messages, bound to this exact frame.
(() => {
  const api = typeof browser !== "undefined" ? browser : chrome;
  const controllers = new Map();
  let routeCache = null;
  let routePending = null;
  async function routeHash() {
    if (routeCache && Date.now() - routeCache.at < 2000) return routeCache.hash;
    if (!routePending) routePending = (async () => {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch("https://api.ipify.org?format=json", { credentials: "omit", cache: "no-store", redirect: "error", signal: controller.signal });
        if (!response.ok) throw new Error("Çıkış IP doğrulaması başarısız.");
        const result = await response.json();
        if (!/^[0-9a-fA-F:.]{3,60}$/.test(result.ip || "")) throw new Error("Geçersiz çıkış doğrulaması.");
        const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(result.ip));
        const hash = [...new Uint8Array(digest)].map((v) => v.toString(16).padStart(2, "0")).join("");
        routeCache = { hash, at: Date.now() };
        return hash;
      } finally { clearTimeout(timer); }
    })().finally(() => { routePending = null; });
    return routePending;
  }
  function safeURL(value) {
    const url = new URL(value);
    const host = url.hostname.toLowerCase();
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password ||
        /^(localhost|127\.|0\.|10\.|192\.168\.|169\.254\.|\[|172\.(1[6-9]|2\d|3[01])\.)/.test(host) || /\.(local|localhost|internal)$/.test(host)) throw new Error("Yerel/özel kaynak reddedildi.");
    return url.href;
  }
  function pipe(client, id, action, payload) {
    return new Promise((resolve, reject) => {
      api.runtime.sendMessage({ type: "IDM_BROWSER_PIPE", client, id, action, payload }, (response) => {
        const error = api.runtime.lastError;
        if (error || !response || !response.ok) reject(new Error("Yerel tarayıcı aktarımı kapandı."));
        else resolve(response);
      });
    });
  }
  api.runtime.onMessage.addListener((msg, _sender, respond) => {
    if (!msg || !["IDM_BROWSER_ROUTE", "IDM_BROWSER_FETCH", "IDM_BROWSER_ABORT"].includes(msg.type)) return false;
    if (msg.type === "IDM_BROWSER_ABORT") {
      const controller = controllers.get(msg.id); if (controller) controller.abort();
      respond({ ok: true }); return false;
    }
    if (msg.type === "IDM_BROWSER_ROUTE") {
      routeHash().then((hash) => respond({ ok: true, hash })).catch(() => respond({ ok: false, error: "Çıkış doğrulaması engellendi/erişilemiyor. IP kontrolü api.ipify.org kullanır." }));
      return true;
    }
    (async () => {
      const req = msg.request;
      if (!req || !req.id || !msg.client || !Number.isInteger(req.limit) || req.limit < 1 || req.limit > 16 * 1024 * 1024) throw new Error("Geçersiz aktarım isteği.");
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 55000);
      controllers.set(req.id, controller);
      let reader = null;
      try {
        const url = safeURL(req.url);
        const checkRoute = async () => { if (msg.routeHash && await routeHash() !== msg.routeHash) throw new Error("Tarayıcı çıkışı değişti."); };
        let response;
        for (const credentials of ["include", "omit"]) {
          await checkRoute();
          try { response = await fetch(url, { method: "GET", headers: req.headers || {}, credentials, redirect: "error", cache: "no-store", signal: controller.signal }); break; }
          catch (error) { if (credentials === "omit" || controller.signal.aborted) throw error; }
        }
        if (!response || ![200, 206].includes(response.status) || !response.body) throw new Error("Medya HTTP isteği reddedildi.");
        await pipe(msg.client, req.id, "meta", { status: response.status, contentRange: response.headers.get("Content-Range") || "", contentType: response.headers.get("Content-Type") || "" });
        reader = response.body.getReader();
        let offset = 0;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          if (offset + value.length > req.limit) throw new Error("Medya parçası boyut sınırını aştı.");
          for (let at = 0; at < value.length; at += 393216) {
            const part = value.subarray(at, at + 393216);
            let binary = "";
            for (let n = 0; n < part.length; n += 0x8000) binary += String.fromCharCode.apply(null, part.subarray(n, n + 0x8000));
            await pipe(msg.client, req.id, "chunk", { offset, data: btoa(binary) });
            offset += part.length;
          }
        }
        await checkRoute();
        await pipe(msg.client, req.id, "done", { ok: true });
        return { ok: true };
      } catch (error) {
        if (reader) await reader.cancel().catch(() => {});
        await pipe(msg.client, req.id, "done", { ok: false }).catch(() => {});
        return { ok: false, error: "Tarayıcı/çıkış aktarımı kesildi. Doğrudan bağlantı denenmedi." };
      } finally { controller.abort(); clearTimeout(timer); controllers.delete(req.id); }
    })().then(respond).catch(() => respond({ ok: false, error: "Tarayıcı aktarımı başlatılamadı." }));
    return true;
  });
})();
