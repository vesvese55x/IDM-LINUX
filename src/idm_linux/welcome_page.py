from __future__ import annotations

import html
import json
from pathlib import Path

from . import __version__
from .browsers import DetectedDefaultBrowser, get_browser_extensions_url


def render_welcome_html(
    http_port: int,
    welcome_token: str,
    default_browser: DetectedDefaultBrowser | None,
    chrom_ext_dir: Path,
) -> str:
    b_name = html.escape(default_browser.name if default_browser else "Web Tarayıcınız")
    b_family = default_browser.family if default_browser else "chromium"
    ext_dir_raw = str(chrom_ext_dir.resolve())
    ext_dir_escaped = html.escape(ext_dir_raw)
    ext_url_raw = get_browser_extensions_url(default_browser)
    ext_url_escaped = html.escape(ext_url_raw)
    ver = html.escape(__version__)

    family_badge = "Firefox / Gecko Tabanlı" if b_family == "gecko" else "Chromium Tabanlı"

    js_family = json.dumps(b_family)
    js_ver = json.dumps(__version__)
    js_token = json.dumps(welcome_token)
    js_ext_dir = json.dumps(ext_dir_raw)
    js_ext_url = json.dumps(ext_url_raw)

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>IDM-Linux v{ver} — Tarayıcı Entegrasyonu</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: radial-gradient(circle at top, #131c31 0%, #0b0f19 65%);
      color: #f8fafc;
      font-family: system-ui, -apple-system, 'Segoe UI', Roboto, Ubuntu, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: space-between;
      padding: 36px 20px 24px;
    }}
    .card {{
      width: 100%;
      max-width: 760px;
      background: rgba(17, 24, 39, 0.95);
      border: 1px solid #1e293b;
      border-radius: 18px;
      padding: 32px;
      box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55);
    }}
    .top-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}
    .logo {{
      width: 48px;
      height: 48px;
      border-radius: 12px;
      background: linear-gradient(135deg, #10b981, #0ea5e9);
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 900;
      font-size: 18px;
      color: #062219;
    }}
    h1 {{ font-size: 22px; font-weight: 800; letter-spacing: -0.02em; }}
    .sub {{ color: #94a3b8; font-size: 13px; margin-top: 2px; }}
    .pill {{
      background: #172554;
      color: #60a5fa;
      border: 1px solid #1d4ed8;
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
    }}
    .status-box {{
      border-radius: 14px;
      padding: 20px;
      margin: 18px 0;
      border: 1px solid #334155;
      background: #0f172a;
      transition: all 0.25s ease;
    }}
    .status-box.ok {{
      background: rgba(6, 78, 59, 0.42);
      border-color: #10b981;
    }}
    .status-title {{
      font-size: 17px;
      font-weight: 700;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .status-desc {{
      color: #cbd5e1;
      font-size: 14px;
      line-height: 1.6;
    }}
    .btn-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 18px;
    }}
    button, a.btn {{
      appearance: none;
      border: none;
      border-radius: 10px;
      padding: 12px 18px;
      font-size: 13.5px;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: transform 0.12s ease, opacity 0.15s ease;
    }}
    button:hover, a.btn:hover {{ opacity: 0.94; transform: translateY(-1px); }}
    button:disabled {{ opacity: 0.65; cursor: wait; transform: none; }}
    .btn-primary {{
      background: linear-gradient(135deg, #10b981, #059669);
      color: #ffffff;
      box-shadow: 0 8px 24px rgba(16, 185, 129, 0.3);
    }}
    .btn-secondary {{
      background: #1e293b;
      color: #e2e8f0;
      border: 1px solid #334155;
    }}
    .btn-chip {{
      background: #0f172a;
      color: #38bdf8;
      border: 1px solid #1e3a8a;
      padding: 8px 13px;
      font-size: 12.5px;
    }}
    .path-box {{
      margin-top: 16px;
      padding: 14px 16px;
      background: #090d16;
      border: 1px dashed #334155;
      border-radius: 10px;
      font-size: 12.5px;
      color: #cbd5e1;
      line-height: 1.65;
    }}
    .path-code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      color: #38bdf8;
      word-break: break-all;
      font-weight: 700;
    }}
    .copy-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .features {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 12px;
      margin-top: 22px;
    }}
    .feat {{
      background: #0f172a;
      border: 1px solid #1e293b;
      border-radius: 12px;
      padding: 14px;
    }}
    .feat strong {{ display: block; font-size: 13.5px; color: #f1f5f9; margin-bottom: 4px; }}
    .feat span {{ font-size: 12px; color: #94a3b8; line-height: 1.45; display: block; }}
    footer {{
      margin-top: 28px;
      text-align: center;
      font-size: 13px;
      color: #94a3b8;
    }}
    footer a {{
      color: #38bdf8;
      font-weight: 700;
      text-decoration: none;
    }}
    footer a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="top-row">
      <div class="brand">
        <div class="logo">IDM</div>
        <div>
          <h1>IDM-Linux Hibrit Tarayıcı Kurulumu</h1>
          <div class="sub">Sürüm v{ver} • Köprü Servisi Aktif (127.0.0.1:{http_port})</div>
        </div>
      </div>
      <div class="pill">Algılanan Tarayıcı: {b_name} ({family_badge})</div>
    </div>

    <div id="ext-status" class="status-box">
      <div class="status-title" id="status-heading">⏳ Tarayıcı Eklenti Durumu Kontrol Ediliyor...</div>
      <div class="status-desc" id="status-body">
        Varsayılan tarayıcınız <b>{b_name}</b> otomatik olarak algılandı.
        Eklenti sinyali bekleniyor...
      </div>
      <div class="btn-row" id="action-buttons" style="display:none;"></div>
      <div class="path-box" id="ext-path-box" style="display:none;">
        <div>📋 Panonuza hazır eklenti dizini: <span class="path-code">{ext_dir_escaped}</span></div>
        <div style="margin-top:6px; color:#94a3b8;">
          💡 <b>Manuel Kurulum İpucu (Sıfır Hata):</b> Tarayıcıların <code>CRX_REQUIRED_PROOF_MISSING</code> kısıtlamasına takılmamak için indirilen <b>.ZIP</b> paketini doğrudan <b>{ext_url_escaped}</b> (<i>Geliştirici Modu</i> açık) ekranına sürükleyip bırakabilir veya <b>Paketlenmiş öğe yükle</b> ile yukarıdaki klasörü seçebilirsiniz.
        </div>
        <div class="copy-row">
          <button type="button" class="btn-chip" id="copy-dir-btn">📋 Eklenti Klasör Yolunu Kopyala</button>
          <button type="button" class="btn-chip" id="copy-url-btn">🔗 {ext_url_escaped} Adresini Kopyala</button>
        </div>
      </div>
    </div>

    <div class="features">
      <div class="feat">
        <strong>🔐 Oturumlu &amp; Arena.ai Desteği</strong>
        <span>Tarayıcı çerezlerini ve kimlik başlıklarını otomatik algılar; şifre sormadan tam hızda indirir.</span>
      </div>
      <div class="feat">
        <strong>🎬 16 Kanal Canlı HLS &amp; YouTube</strong>
        <span>YouTube 4K/1080p ve film sitelerindeki akışları beklemeden canlı yüzde ilerlemesiyle indirir.</span>
      </div>
      <div class="feat">
        <strong>🛡️ Sıfır Çift İndirme</strong>
        <span>Dosyaları yalnızca gerçek Windows IDM devralır; tarayıcı kendi indirme yöneticisini çalıştırmaz.</span>
      </div>
      <div class="feat">
        <strong>🧲 .torrent &amp; Magnet Desteği</strong>
        <span>.torrent dosyalarını ve magnet:? bağlantılarını canlı akış köprüsüyle doğrudan gerçek IDM üzerinden indirir.</span>
      </div>
    </div>
  </div>

  <footer>
    Bu araç <b>BELGESELSEMO</b> tarafından <b>ARENA.AI</b> &amp; <b>Z.AI</b> sayesinde yapılmıştır •
    <a href="https://belgeselsemo.com.tr" target="_blank" rel="noopener">https://belgeselsemo.com.tr</a> •
    <a href="/support" target="_blank" rel="noopener">❤️ Teşekkür Et &amp; Destekle</a>
  </footer>

  <script>
    const FAMILY = {js_family};
    const EXPECTED_VER = {js_ver};
    const TOKEN = {js_token};
    const EXT_DIR = {js_ext_dir};
    const EXT_URL = {js_ext_url};
    let detected = false;

    async function copyTextSafe(txt, btnEl, okLabel) {{
      const orig = btnEl.textContent;
      try {{
        await navigator.clipboard.writeText(txt);
        btnEl.textContent = okLabel;
      }} catch (_) {{
        const ta = document.createElement('textarea');
        ta.value = txt;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        ta.remove();
        btnEl.textContent = okLabel;
      }}
      setTimeout(() => {{ btnEl.textContent = orig; }}, 2000);
    }}

    function markActive(extVersion) {{
      detected = true;
      const box = document.getElementById('ext-status');
      const h = document.getElementById('status-heading');
      const b = document.getElementById('status-body');
      const btns = document.getElementById('action-buttons');
      const pbox = document.getElementById('ext-path-box');
      const v = String(extVersion || EXPECTED_VER);
      const vNewer = compareVersions(EXPECTED_VER, v) > 0;
      box.classList.add('ok');
      if (vNewer) {{
        // v3.9.0: ESKİ sürümlü eklenti CANLI sinyal verdi — kurumsal policy kanalından
        // yeni sürüm TARAYICIYI YENİDEN BAŞLATMADAN üzerine kuruluyor
        h.textContent = '🔄 Eklenti v' + v + ' algılandı → v' + EXPECTED_VER + ' güncellemesi uygulanıyor...';
        b.innerHTML = 'Köprü çalışıyor! Yeni sürüm (<b>v' + EXPECTED_VER + '</b>) kurumsal güncelleme kanalından <b>birkaç saniye içinde</b>, tarayıcıyı yeniden başlatmadan üzerine kurulacak. Bu sayfa açık kaldıkça yeni sürümün sinyali burada onaylanır.';
        detected = false; // yeni sürümün sinyali beklenir
        // v3.9.0: içerik betiği güncellenen sayfaya yeniden enjekte edilmez — sayfa
        // kendini tazeler ve yeni sürümün sinyali otomatik doğrulanır (3 deneme hakkı)
        const RV_KEY = 'idmRelaxReloads';
        let reloads = 0;
        try {{ reloads = parseInt(sessionStorage.getItem(RV_KEY) || '0', 10) || 0; }} catch (_) {{}}
        if (reloads < 3) {{
          sessionStorage.setItem(RV_KEY, String(reloads + 1));
          setTimeout(() => {{ if (!detected) location.reload(); }}, 20000 + reloads * 5000);
        }}
        setTimeout(() => {{
          if (!detected) {{
            h.textContent = '⏳ Güncelleme birkaç saniye içinde otomatik tamamlanır...';
            b.innerHTML = 'Sayfayı açık tutun: v' + EXPECTED_VER + ' etkinleştiğinde bu kutu yeşile döner. Chrome/Chromium türevlerinde güncelleme <b>canlı</b> uygulanır (yeniden başlatma YOK).';
          }}
        }}, 6000);
        return;
      }}
      h.textContent = '✅ IDM-Linux Companion Eklentisi Aktif ve Güncel! (v' + v + ')';
      b.innerHTML = 'Harika! Varsayılan tarayıcınız (<b>{b_name}</b>) ile gerçek Windows IDM arasındaki hibrit köprü tam performansla çalışıyor. Artık <b>arena.ai</b>, YouTube, film siteleri ve tüm dosya indirmelerinde IDM otomatik devreye girecektir.';
      btns.style.display = 'none';
      pbox.style.display = 'none';
    }}

    function compareVersions(a, b) {{
      const pa = String(a).split('.').map(x => parseInt(x, 10) || 0);
      const pb = String(b).split('.').map(x => parseInt(x, 10) || 0);
      for (let i = 0; i < Math.max(pa.length, pb.length); i++) {{
        const d = (pa[i] || 0) - (pb[i] || 0);
        if (d !== 0) return d;
      }}
      return 0;
    }}

    window.addEventListener('message', (ev) => {{
      if (ev.data && ev.data.type === 'IDM_LINUX_EXT_ALIVE') {{
        markActive(ev.data.version);
      }}
    }});

    if (document.documentElement.dataset.idmLinuxExtVersion) {{
      markActive(document.documentElement.dataset.idmLinuxExtVersion);
    }}

    setTimeout(() => {{
      if (detected) return;
      const h = document.getElementById('status-heading');
      const b = document.getElementById('status-body');
      const btns = document.getElementById('action-buttons');
      const pbox = document.getElementById('ext-path-box');
      btns.style.display = 'flex';

      if (FAMILY === 'gecko') {{
        h.textContent = '🦊 Firefox Tabanlı Tarayıcı Algılandı — Tek Tıkla Eklentiyi Kurun';
        b.innerHTML = 'Aşağıdaki butona tıklayarak paketlenmiş <b>.xpi</b> eklentisini doğrudan tarayıcınıza ekleyebilirsiniz.';
        btns.innerHTML = '<a class="btn btn-primary" href="/extension/idm-linux-companion-firefox.xpi">🦊 Firefox Eklentisini Şimdi Yükle (.xpi)</a>';
      }} else {{
        h.textContent = '🚀 Eklenti CANLI Kuruluyor — Tarayıcı Yeniden Başlatılmaz';
        b.innerHTML = 'Tarayıcınız (<b>{b_name}</b>) kurumsal <b>policy force-install</b> kanalıyla <b>canlı izleniyor</b>: eklenti birkaç saniye içinde <b>yeniden başlatma olmadan</b> kendiliğinden yüklenecek. Bu sayfa açık kaldıkça denetlenir; eğer 60 sn içinde etkinleşmezse yeşil buton (sekmeleriniz korunarak) yedek yoldur veya <b>engellenmeyen .ZIP paketini</b> indirip <code>' + EXT_URL + '</code> ekranına sürükleyin:';
        pbox.style.display = 'block';
        btns.innerHTML = `
          <button class="btn btn-primary" id="auto-relaunch-btn">⚡ Tek Tıkla Otomatik Yükle ve Etkinleştir (Sekmeleri Korur)</button>
          <a class="btn btn-secondary" href="/extension/idm-linux-companion-chromium.zip" download="idm-linux-companion-chromium.zip">📦 Eklenti Paketini İndir (.ZIP — Engellenmez)</a>
        `;

        const copyDirBtn = document.getElementById('copy-dir-btn');
        const copyUrlBtn = document.getElementById('copy-url-btn');
        if (copyDirBtn) {{
          copyDirBtn.addEventListener('click', () => copyTextSafe(EXT_DIR, copyDirBtn, '✅ Klasör Yolu Kopyalandı!'));
        }}
        if (copyUrlBtn) {{
          copyUrlBtn.addEventListener('click', () => copyTextSafe(EXT_URL, copyUrlBtn, '✅ Adres Kopyalandı! Yeni Sekmeye Yapıştırın'));
        }}

        const btn = document.getElementById('auto-relaunch-btn');
        if (btn) {{
          btn.addEventListener('click', async () => {{
            btn.disabled = true;
            btn.textContent = '⏳ Tarayıcı açık sekmeler korunarak eklentiyle yeniden başlatılıyor...';
            try {{
              await fetch('/api/browser/activate-extension', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ token: TOKEN }})
              }});
            }} catch (_) {{}}
            // Eğer tarayıcı yeniden başlaması 7 saniyeyi aşarsa bilgi mesajı göster
            setTimeout(() => {{
              if (!detected) {{
                btn.disabled = false;
                btn.textContent = '🔄 Tekrar Dene veya Aşağıdaki Kopyalanan Klasörle Yükle';
              }}
            }}, 7500);
          }});
        }}
      }}
    }}, 800);
  </script>
</body>
</html>
"""
