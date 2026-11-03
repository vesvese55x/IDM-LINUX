"""Lossless assembly of approved/completed footage, explicitly NOT the full film."""
from pathlib import Path
import json,subprocess,hashlib,requests
ROOT=Path('sources');OUT=Path('joined');OUT.mkdir(exist_ok=True);PROOF=OUT/'receipts';PROOF.mkdir(exist_ok=True)
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def probe(p):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-show_chapters','-of','json',str(p)],text=True))
def unique(directory,name):
 p=list(directory.rglob(name));assert len(p)==1,(directory,name,len(p));return p[0]
lessons=[];provenance=[]
for mode,title in [('one','Linux — tek satır'),('app','Linux — AppImage'),('apt','Linux — DEB / apt'),('gdebi','Linux — DEB / GDebi')]:
 directory=ROOT/mode;p=unique(directory,'BELGESELSEMO-EGITIM-KURULUM-'+mode.upper()+'-TR.mp4');reports=sorted(directory.rglob('probe-report.json'),key=lambda p:len(p.parts));assert reports;report=json.loads(reports[0].read_text());assert report['status']=='PASS';assert report['installed_gui']['overview_navigation_verified'];assert report['installed_gui']['rect'][2:]==[1380,870];assert report['console_visibility_audit']['status']=='PASS';assert digest(p)==report['tutorial_delivery']['sha256'];assert report['tutorial_delivery']['voice_rate']==1.0
 if mode=='app':assert report['appimage_launch_method']=='Direct released AppImage with FUSE';assert report['appimage_real_properties_window']
 duration=float(probe(p)['format']['duration']);lessons.append({'file':p,'title':title,'duration':duration,'mode':mode,'report':report});provenance.append({'mode':mode,'run_id':report['run_id'],'commit':report['source_checkout_commit'],'sha256':digest(p),'duration':duration,'actual_gui':report['installed_gui'],'console':report['console_visibility_audit']['status'],'full_feature_suite':'NOT_RUN'})
promo=unique(ROOT/'promo','BELGESELSEMO-EGITIM-BOLUM-01-PROMO-TR-V3.mp4');assert digest(promo)=='5180f92f135b86ad21db50aeaa2c3075f8a22ab3caa06689b4c34be52b59888c'
def signature(p):
 data=probe(p);v=next(s for s in data['streams'] if s['codec_type']=='video');a=next(s for s in data['streams'] if s['codec_type']=='audio');return [v[k] for k in ['codec_name','width','height','pix_fmt','r_frame_rate']]+[a[k] for k in ['codec_name','sample_rate','channels']]
expected=signature(promo)
for l in lessons:assert signature(l['file'])==expected
receipts=[]
def assemble(items,name,title,scope):
 target=OUT/(name+'.mp4');concat=OUT/(name+'.concat');metadata=OUT/(name+'.metadata');concat.write_text(''.join("file '"+str(l['file'].resolve())+"'\n" for l in items));offset=0.;chapters=[];text=';FFMETADATA1\ntitle='+title+'\ncomment='+scope+'\n'
 for l in items:
  end=offset+l['duration'];chapters.append({'title':l['title'],'start':offset,'end':end});text+='[CHAPTER]\nTIMEBASE=1/1000\nSTART='+str(round(offset*1000))+'\nEND='+str(round(end*1000))+'\ntitle='+l['title']+'\n';offset=end
 metadata.write_text(text,encoding='utf-8')
 with (OUT/(name+'-concat.log')).open('wb') as f:subprocess.run(['ffmpeg','-v','warning','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(metadata),'-map','0:v:0','-map','0:a:0','-map_metadata','1','-map_chapters','1','-c','copy','-movflags','+faststart',str(target)],stdout=f,stderr=f,check=True)
 data=probe(target);actual=float(data['format']['duration']);assert abs(actual-offset)<.4;assert len(data['chapters'])==len(items)
 decode=subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,text=True);assert decode.returncode==0 and not decode.stderr,decode.stderr
 md5=hashlib.md5(target.read_bytes()).hexdigest()
 with target.open('rb') as f:r=requests.post('https://upload.gofile.io/uploadfile',files={'file':(target.name,f,'video/mp4')},timeout=(30,600))
 r.raise_for_status();response=r.json();assert response['status']=='ok';d=response['data'];assert d['size']==target.stat().st_size and d['md5']==md5
 receipt={'file':target.name,'download_page':d['downloadPage'],'bytes':target.stat().st_size,'duration':actual,'sha256':digest(target),'md5':md5,'chapters':chapters,'full_decode':'PASS','voice_rate':1.0,'assembly':'Stream copy; no voice speed change or video re-encoding','scope':scope,'full_scope_film_complete':False,'source_runs':provenance};(PROOF/(name+'.json')).write_text(json.dumps(receipt,ensure_ascii=False,indent=2));receipts.append(receipt);print('ASSEMBLED',json.dumps(receipt,ensure_ascii=False),flush=True)
 return target
scope='Completed four real Linux package/control-panel installation lessons only. Wine/IDM-engine preparation, Windows, RPM/Arch, actual hoster/video/playlist/P2P transfers and exhaustive GUI tests are not completed by this assembly.'
part2=assemble(lessons,'BELGESELSEMO-EGITIM-BOLUM-02-LINUX-KURULUMLAR-TR','Bölüm 02 — Linux kurulum yolları',scope)
all_items=[{'file':promo,'title':'Tanıtım — onaylı V3','duration':float(probe(promo)['format']['duration'])}]+lessons
master=assemble(all_items,'BELGESELSEMO-EGITIM-TAMAMLANAN-BOLUMLER-CALISMA-KOPYASI-TR','ÇALIŞMA KOPYASI — tamamlanan bölümler','NOT THE FINISHED FULL-SCOPE FILM. Approved V3 promo plus four completed Linux installation lessons. '+scope)
one=lessons[0];timepoint=all_items[0]['duration']+one['report']['tutorial_audio_cues'][-1]['video_offset_seconds']+5
subprocess.run(['ffmpeg','-v','error','-y','-ss',str(timepoint),'-i',str(master),'-frames:v','1','-vf','scale=1280:-2','-q:v','3',str(PROOF/'TAMAMLANAN-BOLUMLER-GERCEK-FILM-KARESI.jpg')],check=True)
lines=['# BELGESELSEMO — tamamlanan eğitim bölümleri','','**Bu bir çalışma kopyasıdır; tam kapsamlı ana film henüz tamamlanmadı.**','']
for r in receipts:
 lines+=['## '+r['file'],'',r['download_page'],'','Süre: '+str(round(r['duration'],2))+' saniye. Tam decode ve yükleme hash kontrolü: PASS.','']
 for ch in r['chapters']:lines.append(f'- {int(ch["start"]//60):02}:{int(ch["start"]%60):02} — {ch["title"]}')
 lines.append('')
lines+=['## Kalan kapsam','','Windows CMD/EXE, RPM/Arch, motor hazırlığı, gerçek YouTube/playlist ve diğer kaynak indirmeleri, kapsamlı GUI işlevleri ve stüdyo/ana film kurgusu.','','Kontrol panelinin açılması, motorun ve bütün indirme kaynaklarının çalıştığı anlamına gelmez.']
(PROOF/'EGITIM-TAMAMLANAN-BOLUMLER.md').write_text('\n'.join(lines),encoding='utf-8')
