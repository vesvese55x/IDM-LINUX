from __future__ import annotations

import html

from .i18n import I18nManager, SUPPORTED_LANGUAGES
from .projects_data import (
    BELGESELSEMO_PREMIUM_URL,
    BELGESELSEMO_WEB_URL,
    GOOGLE_PLAY_DEV_URL,
    NOWPAYMENTS_DONATION_URL,
    NOWPAYMENTS_IFRAME_SNIPPET,
    NOWPAYMENTS_POS_URL,
    YOUTUBE_CHANNEL_URL,
)
from .qr_gen import render_qr_base64


def build_support_html(http_port: int = 17802, lang_code: str = "tr") -> str:
    i18n = I18nManager(lang_code)
    t = i18n.t
    spec = SUPPORTED_LANGUAGES.get(i18n.lang)
    dir_attr = "rtl" if (spec and spec.rtl) else "ltr"

    don_qr_b64 = render_qr_base64(NOWPAYMENTS_DONATION_URL, scale=3, border=2)
    pos_qr_b64 = render_qr_base64(NOWPAYMENTS_POS_URL, scale=3, border=2)
    prem_qr_b64 = render_qr_base64(BELGESELSEMO_PREMIUM_URL, scale=3, border=2)
    yt_qr_b64 = render_qr_base64(YOUTUBE_CHANNEL_URL, scale=3, border=2)
    gp_qr_b64 = render_qr_base64(GOOGLE_PLAY_DEV_URL, scale=3, border=2)

    deeds_html = "".join(
        f"<li>• {html.escape(t(f'sup.m2_d{i}'))}</li>" for i in range(1, 7)
    )
    prem_highlights = "".join(
        f"<li>✓ {html.escape(t(f'sup.m4_h{i}'))}</li>" for i in range(1, 5)
    )

    return f"""<!DOCTYPE html>
<html lang="{html.escape(i18n.lang)}" dir="{dir_attr}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(t('sup.title'))} — IDM-Linux × BELGESELSEMO</title>
  <style>
    :root {{
      --bg-main: #0f172a;
      --bg-card: #1e293b;
      --bg-sub: #0b1324;
      --border: #334155;
      --accent: #0284c7;
      --accent-hi: #38bdf8;
      --emerald: #10b981;
      --amber: #f59e0b;
      --purple: #a855f7;
      --fg-primary: #f8fafc;
      --fg-secondary: #cbd5e1;
      --fg-muted: #94a3b8;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans", "DejaVu Sans", sans-serif;
      background: radial-gradient(circle at top right, #172554 0%, var(--bg-main) 52%);
      color: var(--fg-primary);
      min-height: 100vh;
      padding: 28px 20px 44px;
      line-height: 1.6;
    }}
    .wrap {{ max-width: 1160px; margin: 0 auto; }}
    .justify {{ text-align: justify; text-justify: inter-word; }}
    .hero {{
      background: linear-gradient(135deg, rgba(30,41,59,0.96), rgba(15,23,42,0.96));
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 24px 28px;
      margin-bottom: 24px;
      box-shadow: 0 18px 40px rgba(0,0,0,0.32);
    }}
    .hero h1 {{ font-size: 24px; font-weight: 800; margin-bottom: 8px; }}
    .hero p {{ color: var(--fg-secondary); font-size: 14px; }}
    .grid {{
      display: grid;
      grid-template-columns: 1fr 386px;
      gap: 24px;
      align-items: start;
    }}
    @media (max-width: 960px) {{ .grid {{ grid-template-columns: 1fr; }} }}
    .methods {{ display: flex; flex-direction: column; gap: 18px; }}
    .card {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 20px 22px;
      box-shadow: 0 10px 26px rgba(0,0,0,0.22);
    }}
    .step-pill {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 8px;
      font-size: 11px;
      font-weight: 800;
      margin-bottom: 8px;
    }}
    .pill-1 {{ background: rgba(239,68,68,0.18); color: #fca5a5; border: 1px solid rgba(239,68,68,0.4); }}
    .pill-2 {{ background: rgba(16,185,129,0.18); color: #6ee7b7; border: 1px solid rgba(16,185,129,0.4); }}
    .pill-3 {{ background: rgba(245,158,11,0.18); color: #fcd34d; border: 1px solid rgba(245,158,11,0.4); }}
    .pill-4 {{ background: rgba(168,85,247,0.20); color: #d8b4fe; border: 1px solid rgba(168,85,247,0.45); }}
    .card h2 {{ font-size: 17px; font-weight: 700; margin-bottom: 8px; }}
    .card p {{ color: var(--fg-secondary); font-size: 14px; margin-bottom: 12px; }}
    .deed-list {{
      list-style: none;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 8px;
      margin-top: 8px;
    }}
    .deed-list li {{
      background: var(--bg-sub);
      border: 1px solid #26354d;
      border-radius: 10px;
      padding: 9px 12px;
      font-size: 13px;
      color: var(--fg-secondary);
    }}
    .btn-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 12px; }}
    .btn {{
      display: inline-flex;
      align-items: center;
      padding: 9px 15px;
      border-radius: 10px;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      color: #fff;
      background: var(--accent);
    }}
    .btn-yt {{ background: #dc2626; }}
    .btn-gp {{ background: #059669; }}
    .btn-amber {{ background: #d97706; }}
    .btn-prem {{ background: linear-gradient(135deg, #9333ea, #d97706); }}
    .qr-strip {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 14px; }}
    .qr-box {{
      background: var(--bg-sub);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 8px 10px;
      text-align: center;
    }}
    .qr-box img {{ width: 92px; height: 92px; border-radius: 6px; display: block; margin: 0 auto 4px; }}
    .qr-box span {{ font-size: 11px; color: var(--fg-muted); }}
    .widget-box {{
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 18px;
      padding: 18px;
      text-align: center;
    }}
    .note-box {{
      margin-top: 10px;
      background: rgba(16, 185, 129, 0.10);
      border: 1px solid rgba(16, 185, 129, 0.35);
      border-radius: 10px;
      padding: 10px 12px;
      font-size: 12.5px;
      color: #a7f3d0;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>❤️ {html.escape(t('sup.title'))}</h1>
      <p class="justify">{html.escape(t('sup.subtitle'))}</p>
    </section>
    <div class="grid">
      <div class="methods">
        <article class="card">
          <span class="step-pill pill-1">{html.escape(t('sup.m1_badge'))}</span>
          <h2>{html.escape(t('sup.m1_title'))}</h2>
          <p class="justify">{html.escape(t('sup.m1_desc'))}</p>
          <div class="btn-row">
            <a class="btn btn-yt" href="{YOUTUBE_CHANNEL_URL}" target="_blank" rel="noopener">{html.escape(t('sup.m1_btn_yt'))}</a>
            <a class="btn btn-gp" href="{GOOGLE_PLAY_DEV_URL}" target="_blank" rel="noopener">{html.escape(t('sup.m1_btn_gp'))}</a>
            <a class="btn" href="{BELGESELSEMO_WEB_URL}" target="_blank" rel="noopener">{html.escape(t('sup.m1_btn_web'))}</a>
          </div>
          <div class="qr-strip">
            <div class="qr-box"><img src="data:image/png;base64,{yt_qr_b64}" alt="YT QR" /><span>{html.escape(t('sup.m1_qr_yt'))}</span></div>
            <div class="qr-box"><img src="data:image/png;base64,{gp_qr_b64}" alt="GP QR" /><span>{html.escape(t('sup.m1_qr_gp'))}</span></div>
          </div>
        </article>

        <article class="card">
          <span class="step-pill pill-2">{html.escape(t('sup.m2_badge'))}</span>
          <h2>{html.escape(t('sup.m2_title'))}</h2>
          <p class="justify">{html.escape(t('sup.m2_desc'))}</p>
          <ul class="deed-list">{deeds_html}</ul>
        </article>

        <article class="card">
          <span class="step-pill pill-3">{html.escape(t('sup.m3_badge'))}</span>
          <h2>{html.escape(t('sup.m3_title'))}</h2>
          <p class="justify">{html.escape(t('sup.m3_desc'))}</p>
          <div class="btn-row">
            <a class="btn btn-amber" href="{NOWPAYMENTS_DONATION_URL}" target="_blank" rel="noopener">{NOWPAYMENTS_DONATION_URL}</a>
            <a class="btn" href="{NOWPAYMENTS_POS_URL}" target="_blank" rel="noopener">{NOWPAYMENTS_POS_URL}</a>
          </div>
          <div class="qr-strip">
            <div class="qr-box"><img src="data:image/png;base64,{don_qr_b64}" alt="Don QR" /><span>{html.escape(t('sup.m3_qr_don'))}</span></div>
            <div class="qr-box"><img src="data:image/png;base64,{pos_qr_b64}" alt="POS QR" /><span>{html.escape(t('sup.m3_qr_pos'))}</span></div>
          </div>
        </article>

        <article class="card">
          <span class="step-pill pill-4">{html.escape(t('sup.m4_badge'))}</span>
          <h2>{html.escape(t('sup.m4_title'))}</h2>
          <p class="justify">{html.escape(t('sup.m4_desc'))}</p>
          <ul class="deed-list">{prem_highlights}</ul>
          <div class="note-box justify">{html.escape(t('sup.m4_social_note'))}</div>
          <div class="btn-row">
            <a class="btn btn-prem" href="{BELGESELSEMO_PREMIUM_URL}" target="_blank" rel="noopener">{html.escape(t('sup.m4_btn_open'))}</a>
          </div>
          <div class="qr-strip">
            <div class="qr-box"><img src="data:image/png;base64,{prem_qr_b64}" alt="Premium QR" /><span>{html.escape(t('sup.m4_qr_lbl'))}</span></div>
          </div>
        </article>
      </div>

      <aside class="widget-box">
        <h3 style="margin-bottom:10px;font-size:15px;">{html.escape(t('sup.iframe_tab_donation'))}</h3>
        <iframe src="{NOWPAYMENTS_DONATION_URL}" width="346" height="540" frameborder="0" style="border-radius:12px;width:100%;max-width:346px;margin-bottom:14px;"></iframe>
        {NOWPAYMENTS_IFRAME_SNIPPET}
      </aside>
    </div>
  </div>
</body>
</html>
"""
