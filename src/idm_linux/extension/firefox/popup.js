"use strict";

const extApi = typeof browser !== "undefined" ? browser : chrome;

function sendMsg(payload) {
  return new Promise((resolve) => {
    extApi.runtime.sendMessage(payload, (resp) => {
      void extApi.runtime.lastError;
      resolve(resp || { ok: false });
    });
  });
}

function getActiveTab() {
  return new Promise((resolve) => {
    extApi.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      resolve((tabs && tabs[0]) || null);
    });
  });
}

(async function initPopup() {
  const badge = document.getElementById("statusBadge");
  const chkCapture = document.getElementById("chkCapture");
  const chkVideoBar = document.getElementById("chkVideoBar");
  const coexistNote = document.getElementById("coexistNote");
  const urlInput = document.getElementById("urlInput");
  const sendUrlBtn = document.getElementById("sendUrlBtn");
  const toggleDomainBtn = document.getElementById("toggleDomainBtn");
  const openIdmBtn = document.getElementById("openIdmBtn");

  const activeTab = await getActiveTab();
  let activeHost = "";
  try {
    if (activeTab && activeTab.url && activeTab.url.startsWith("http")) {
      activeHost = new URL(activeTab.url).hostname.toLowerCase();
    }
  } catch (_e) {}

  const res = await sendMsg({ type: "IDM_POPUP_STATUS" });
  const st = (res && res.state) || {};
  let excludedDomains = Array.isArray(st.excluded_domains) ? st.excluded_domains.slice() : [];

  if (st.online) {
    badge.textContent = st.idm_installed ? "● Aktif (IDM Hazır)" : "● Köprü Açık";
    badge.className = "status-pill ok";
  } else {
    badge.textContent = "● Servis Kapalı";
    badge.className = "status-pill err";
  }

  chkCapture.checked = st.capture_downloads !== false;
  chkVideoBar.checked = st.video_bar_enabled !== false;

  if (st.official_extension_connected) {
    coexistNote.textContent = "✓ Resmi IDM eklentisi de bağlı (Hibrit birlikte çalışma aktif).";
  }

  function renderDomainBtn() {
    if (!activeHost) {
      toggleDomainBtn.style.display = "none";
      return;
    }
    const isExcl = excludedDomains.includes(activeHost);
    toggleDomainBtn.textContent = isExcl
      ? `✓ ${activeHost} Yeniden Etkinleştir`
      : `Bu Sitede Yakalamayı Durdur (${activeHost})`;
  }
  renderDomainBtn();

  chkCapture.addEventListener("change", async () => {
    await sendMsg({
      type: "IDM_UPDATE_CONFIG",
      config: { capture_downloads: chkCapture.checked }
    });
  });

  chkVideoBar.addEventListener("change", async () => {
    await sendMsg({
      type: "IDM_UPDATE_CONFIG",
      config: { video_bar_enabled: chkVideoBar.checked }
    });
  });

  toggleDomainBtn.addEventListener("click", async () => {
    if (!activeHost) return;
    if (excludedDomains.includes(activeHost)) {
      excludedDomains = excludedDomains.filter((d) => d !== activeHost);
    } else {
      excludedDomains.push(activeHost);
    }
    await sendMsg({
      type: "IDM_UPDATE_CONFIG",
      config: { excluded_domains: excludedDomains }
    });
    renderDomainBtn();
  });

  sendUrlBtn.addEventListener("click", async () => {
    const u = urlInput.value.trim();
    if (!u.startsWith("http") && !u.toLowerCase().startsWith("magnet:?")) return;
    urlInput.value = "";
    await sendMsg({
      type: "IDM_DIRECT_DOWNLOAD",
      url: u,
      referer: (activeTab && activeTab.url) || "",
      source: "popup"
    });
    window.close();
  });

  openIdmBtn.addEventListener("click", async () => {
    await sendMsg({ type: "IDM_OPEN_APP" });
    window.close();
  });
})();
