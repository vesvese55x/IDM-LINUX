"""Real browser upload/download of a self-created demonstration ZIP, not a simulated transfer."""
import os,time,json,subprocess,signal,hashlib,zipfile,re,shutil,csv,io
from pathlib import Path
from playwright.sync_api import sync_playwright
from pointer_tracker import PointerTracker
site=os.environ['CAPTURE_SITE'];R=Path('out')/site;R.mkdir(parents=True,exist_ok=True)
fixture=Path('/tmp/IDM-ornek-paketi.zip')
with zipfile.ZipFile(fixture,'w',compression=zipfile.ZIP_STORED) as z:
 z.writestr('README.txt','IDM Linux egitiminde kullanilan ornek dosya. Kisisel veri icermez.\n')
 z.writestr('ornek-veri.bin',os.urandom(4*1024*1024))
if site=='mediafire':
 fixture=Path('/tmp/test.txt');fixture.write_bytes(b'test download worked!')
expected=hashlib.sha256(fixture.read_bytes()).hexdigest();epoch=time.time();events=[];rec=None;ptr=PointerTracker(R/'pointer.json',epoch).start()
def event(name,**kw):
 events.append({'seconds':round(time.time()-epoch,3),'event':name,**kw});(R/'events.json').write_text(json.dumps(events,indent=2));print(name,flush=True)
def windows():return subprocess.run(['wmctrl','-lG'],capture_output=True,text=True).stdout
def physical_click(page,loc,button="left"):
 loc.wait_for(state='visible',timeout=20000);loc.scroll_into_view_if_needed();box=loc.bounding_box();assert box
 session=page.context.new_cdp_session(page)
 try:bounds=session.send('Browser.getWindowForTarget')['bounds'];metrics=session.send('Page.getLayoutMetrics')['cssLayoutViewport']
 finally:session.detach()
 border=max(0,(bounds['width']-metrics['clientWidth'])/2);x=round(bounds['left']+border+box['x']+box['width']/2);y=round(bounds['top']+bounds['height']-metrics['clientHeight']-border+box['y']+box['height']/2)
 subprocess.run(['xdotool','mousemove','--sync',str(x),str(y)],check=True);time.sleep(.6);loc.click(timeout=20000,button=button);event('browser_click',x=x,y=y)
def barrier(page):
 for f in page.locator('iframe[src*="captcha"]').all():
  if f.is_visible():raise RuntimeError('CAPTCHA requires user; no bypass attempted')
 if re.search(r'Sign in to confirm|Access denied|verify you are human',page.locator('body').inner_text(),re.I):raise RuntimeError('Access barrier; no bypass attempted')
try:
 rec=subprocess.Popen(['ffmpeg','-nostdin','-y','-v','warning','-f','x11grab','-draw_mouse','1','-video_size','1920x1080','-framerate','24','-i',os.environ['DISPLAY'],'-an','-c:v','libx264','-preset','veryfast','-crf','20','-bf','0',str(R/'uncut.mp4')],stdout=open(R/'capture.log','w'),stderr=subprocess.STDOUT)
 with sync_playwright() as p:
  b=p.chromium.connect_over_cdp('http://127.0.0.1:9222');ctx=b.contexts[0];sender=ctx.new_page()
  if site=='mediafire':
   download_url='https://www.mediafire.com/file/luaxzvg20jspwoz/test.txt/file'
  else:
   home={'1fichier':'https://1fichier.com/','filebin':'https://filebin.net/','justbeamit':'https://justbeamit.com/'}[site]
   sender.goto(home,wait_until='domcontentloaded',timeout=60000);event('upload_page_open',url=home);sender.wait_for_timeout(3000);barrier(sender)
   if site=='1fichier':
    consent=sender.get_by_text('I fully accept usage of cookies and the Terms of Services',exact=False)
    if consent.count() and consent.first.is_visible():physical_click(sender,consent.first)
   sender.locator('input[type=file]').first.set_input_files(str(fixture));event('own_sample_selected',sha256=expected,bytes=fixture.stat().st_size)
   if site=='1fichier':
    send=sender.get_by_role('button',name=re.compile('^Send$|^Envoyer$|^Gönder$',re.I))
    if send.count():physical_click(sender,send.first)
    else:physical_click(sender,sender.locator('input[type=submit]').first)
   if site=='justbeamit':physical_click(sender,sender.locator('#create-link-button'))
   deadline=time.time()+180;download_url=None
   while time.time()<deadline:
    barrier(sender)
    if site=='justbeamit':
     value=sender.locator('#share-link-input').input_value().strip()
     if re.match(r'https://justbeamit.com/[A-Za-z0-9]{5,12}/?$',value):download_url=value;break
    if site=='filebin' and re.search(r'filebin.net/[A-Za-z0-9]+',sender.url):download_url=sender.url;break
    for href in sender.locator('a[href]').evaluate_all('(nodes)=>nodes.map(n=>n.href)'):
     if site=='1fichier' and re.match(r'https://1fichier.com/\?[A-Za-z0-9]+',href):download_url=href;break
     if site=='justbeamit' and re.match(r'https://justbeamit.com/[A-Za-z0-9]{5,12}/?$',href) and href.rstrip('/').split('/')[-1] not in ['help','terms','privacy']:download_url=href;break
    if download_url:break
    sender.wait_for_timeout(2000)
   if not download_url:raise RuntimeError('No genuine upload sharing URL produced')
  event('real_upload_link',url=download_url);page=ctx.new_page();page.goto(download_url,wait_until='domcontentloaded',timeout=60000);page.wait_for_timeout(5000);barrier(page)
  baseline={line.split()[0] for line in windows().splitlines() if line.split()};event('recipient_page_open',url=page.url)
  page.screenshot(path=str(R/'source-page.png'));clicked=set();found=False;deadline=time.time()+240
  while time.time()<deadline:
   barrier(page);w=windows()
   lines=[line for line in w.splitlines() if line.split() and line.split()[0] not in baseline and (('dosya' in line.lower() and 'bilgisi' in line.lower()) or 'download file info' in line.lower())]
   if lines:info_line=lines[0];found=True;break
   if site=='filebin':loc=page.get_by_role('link',name='IDM-ornek-paketi.zip',exact=False)
   elif site=='mediafire':loc=page.locator('a#downloadButton[aria-label="Download file"]')
   elif site=='justbeamit':loc=page.locator('button#dl-button')
   else:raise RuntimeError('Unreviewed site selector; no generic download clicking permitted')
   for k in range(loc.count()):
    target=loc.nth(k)
    if not target.is_visible():continue
    label=target.inner_text().strip()
    if re.search('premium|high.speed',label,re.I) or label in clicked:continue
    if site=='mediafire':
     physical_click(page,target,button='right');time.sleep(2)
     screen=R/'native-context-menu.png';subprocess.run(['import','-window','root',str(screen)],check=True)
     tsv=subprocess.check_output(['tesseract',str(screen),'stdout','-l','tur+eng','tsv'],text=True)
     (R/'context-menu-ocr.tsv').write_text(tsv);rows=list(csv.DictReader(io.StringIO(tsv),delimiter='\t'));groups={}
     for row in rows:
      if row.get('text','').strip():groups.setdefault((row['block_num'],row['par_num'],row['line_num']),[]).append(row)
     chosen=None
     for group in groups.values():
      for index in range(max(0,len(group)-2)):
       segment=group[index:index+3];words=' '.join(row['text'] for row in segment)
       if re.fullmatch(r'IDM\s+ile\s+[İIıi]ndir',words,re.I):chosen=segment;break
      if chosen is not None:break
     if chosen is None:raise RuntimeError('Actual browser context-menu IDM command not located; no coordinate guessing')
     x0=min(int(row['left']) for row in chosen);y0=min(int(row['top']) for row in chosen);x1=max(int(row['left'])+int(row['width']) for row in chosen);y1=max(int(row['top'])+int(row['height']) for row in chosen)
     subprocess.run(['xdotool','mousemove','--sync',str((x0+x1)//2),str((y0+y1)//2),'click','1'],check=True)
     event('real_native_context_menu_idm_click',text=' '.join(row['text'] for row in chosen),box=[x0,y0,x1,y1])
    else:physical_click(page,target)
    clicked.add(label);event('real_download_button',label=label);break
   page.wait_for_timeout(3000)
  if not found:raise RuntimeError('Native IDM file information window not reached')
  subprocess.run(['import','-window','root',str(R/'idm-file-info.png')],check=True);time.sleep(5);subprocess.run(['xdotool','windowactivate','--sync',info_line.split()[0]],check=True);subprocess.run(['xdotool','key','Return'],check=True);event('start_pressed')
  deadline=time.time()+600;completed=False
  while time.time()<deadline:
   w=windows()
   if any(line.split() and line.split()[0] not in baseline and ('download complete' in line.lower() or 'tamamland' in line.lower()) for line in w.splitlines()):completed=True;break
   time.sleep(2)
  subprocess.run(['import','-window','root',str(R/'idm-end.png')],check=True)
  if not completed:raise RuntimeError('No native completion dialog')
  time.sleep(6);verified=None
  for f in Path.home().rglob('*'+fixture.suffix):
   if '.cache' in f.parts or '.local' in f.parts or 'out' in f.parts or f.stat().st_mtime<epoch:continue
   if f.stat().st_size==fixture.stat().st_size and hashlib.sha256(f.read_bytes()).hexdigest()==expected:verified=f;break
  if not verified:raise RuntimeError('No completed native file matching exact expected SHA256')
  if fixture.suffix=='.zip':
   with zipfile.ZipFile(verified) as z:assert z.testzip() is None
  shutil.copyfile(verified,R/('download-original'+fixture.suffix));event('VERIFIED_FILE_SHA256',file=str(verified),sha256=expected,bytes=verified.stat().st_size);time.sleep(5)
except Exception as e:
 subprocess.run(['import','-window','root',str(R/'failure.png')],check=False);event('FAIL',reason=str(e));raise
finally:
 ptr.finish()
 if rec and rec.poll() is None:
  rec.send_signal(signal.SIGINT)
  try:rec.wait(timeout=45)
  except subprocess.TimeoutExpired:rec.kill();rec.wait()
