#!/usr/bin/env python3
"""Real Chromium executes production page hooks on controlled subtitle fixtures, not a live-site claim."""
import asyncio,json,os
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[2]
VTT='WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nMerhaba dünya\n'
async def main():
 results=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=False,args=['--no-sandbox'],executable_path=os.environ.get('PLAYWRIGHT_BROWSER_EXECUTABLE'))
  for family in ['chromium','firefox']:
   # The Firefox source is executed in Chromium too: this checks both shipped
   # scripts, NOT the Firefox browser engine or extension runtime.
   context=await browser.new_context()
   await context.add_init_script('window.__subMessages=[];addEventListener("message",e=>{if(e.source===window&&(e.data.__idmLinuxSubtitle||e.data.__idmLinuxSubtitleText))window.__subMessages.push(e.data)});document.addEventListener("DOMContentLoaded",()=>{document.documentElement.dataset.idmLinuxCaptureEnabled="1";document.documentElement.dataset.idmLinuxBlobReady="1";window.dispatchEvent(new Event("idm-linux-capture-state"))});')
   await context.add_init_script(path=ROOT/'src/idm_linux/extension'/family/'page_hook.js')
   page=await context.new_page()
   async def fixture(route):
    url=route.request.url
    if '/config/api' in url:
     await route.fulfill(content_type='application/json',body=json.dumps({'tracks':[{'kind':'captions','file':'../subs/1.vtt','label':'Türkçe'},{'kind':'captions','file':'/caption?id=22','label':'English'}]}))
    else:
     await route.fulfill(content_type='text/html',body='<html><head></head><body><script type="application/json">{"tracks":[{"kind":"captions","file":"/caption?id=11","label":"Deutsch"}]}</script><video></video></body></html>')
   await page.route('**/*',fixture)
   await page.goto('https://player.example.test/player')
   await page.evaluate('fetch("/config/api")')
   await page.wait_for_function('window.__subMessages.some(x=>x.url&&x.url.endsWith("/subs/1.vtt")) && window.__subMessages.some(x=>x.url&&x.url.includes("id=11")) && window.__subMessages.some(x=>x.url&&x.url.includes("id=22"))',timeout=12000)
   messages=await page.evaluate('window.__subMessages');assert all(x.get('url','').startswith('https://player.example.test/') for x in messages)
   await page.evaluate('document.documentElement.dataset.idmLinuxCaptureEnabled="0";window.__subMessages=[];fetch("/config/api?passive=1");window.dispatchEvent(new Event("idm-linux-capture-state"))')
   await page.wait_for_timeout(1800);assert await page.evaluate('window.__subMessages.length')==0
   results.append({'source':family,'test':'relative and extensionless player captions; passive mode','status':'PASS'})
   await context.close()
  context=await browser.new_context()
  await context.add_init_script('window.__subMessages=[];addEventListener("message",e=>{if(e.source===window&&e.data.__idmLinuxSubtitleText)window.__subMessages.push(e.data)});document.addEventListener("DOMContentLoaded",()=>{document.documentElement.dataset.idmLinuxCaptureEnabled="1";window.dispatchEvent(new Event("idm-linux-capture-state"))});')
  await context.add_init_script(path=ROOT/'src/idm_linux/extension/chromium/page_hook.js')
  page=await context.new_page();caption_urls=[]
  async def youtube_fixture(route):
   if '/api/timedtext' in route.request.url:
    caption_urls.append(route.request.url);await route.fulfill(content_type='text/vtt',body=VTT)
   else:await route.fulfill(content_type='text/html',body='<html><head></head><body>YouTube controlled fixture</body></html>')
  await page.route('**/*',youtube_fixture)
  await page.goto('https://www.youtube.com/watch?v=one')
  data={'videoDetails':{'videoId':'one'},'captions':{'playerCaptionsTracklistRenderer':{'captionTracks':[{'baseUrl':'https://www.youtube.com/api/timedtext?v=one&lang=en&fmt=srv3','languageCode':'en','name':{'simpleText':'English'},'kind':'asr'}]}}}
  await page.evaluate('(data)=>{window.ytInitialPlayerResponse=data;dispatchEvent(new Event("yt-player-updated"))}',data)
  # The production hook may announce the same track from several detectors; the bar
  # de-duplicates by normalised key. Assert per-video coverage, not a raw message count.
  await page.wait_for_function('window.__subMessages.some(m=>m.sourceUrl&&m.sourceUrl.includes("v=one"))')
  first=await page.evaluate('window.__subMessages.map(m=>m.sourceUrl)')
  assert set(first)=={'https://www.youtube.com/api/timedtext?v=one&lang=en&fmt=vtt'}, first
  data['videoDetails']['videoId']='two';data['captions']['playerCaptionsTracklistRenderer']['captionTracks'][0]['baseUrl']='https://www.youtube.com/api/timedtext?v=two&lang=en&fmt=srv3'
  await page.evaluate('(data)=>{history.pushState({},"","/watch?v=two");window.ytInitialPlayerResponse=data;dispatchEvent(new Event("yt-navigate-finish"))}',data)
  await page.wait_for_function('window.__subMessages.some(m=>m.sourceUrl&&m.sourceUrl.includes("v=two"))')
  assert len(caption_urls)==2 and len({u for u in caption_urls})==2 and all(u.count('fmt=')==1 and 'fmt=vtt' in u for u in caption_urls), caption_urls
  results.append({'source':'chromium','test':'YouTube SPA same-language captions refreshed; one fmt=vtt parameter','status':'PASS'})
  await browser.close()
 out=ROOT/'artifacts/linux-gui';out.mkdir(parents=True,exist_ok=True)
 (out/'subtitle-browser-results.json').write_text(json.dumps({'status':'PASS','browser':'Real Chromium via Playwright under Xvfb','live_site_test':False,'tests':results},indent=2))
 print('REAL_CHROMIUM_SUBTITLE_FIXTURES_PASS',json.dumps(results))
if __name__=='__main__':asyncio.run(main())
