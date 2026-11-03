"""Keep approved promo/install lessons and motor setup; replace local fixture with reviewed official external download."""
from pathlib import Path
import json,subprocess,hashlib,requests
ROOT=Path('official-sources');OUT=Path('official-assembly');OUT.mkdir(exist_ok=True);PROOF=OUT/'receipts';PROOF.mkdir(exist_ok=True)
def one(root,name):
 p=list(root.rglob(name));assert len(p)==1,(name,len(p));return p[0]
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def probe(p):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-show_chapters','-of','json',str(p)],text=True))
previous=one(ROOT/'previous','BELGESELSEMO-EGITIM-CALISMA-KOPYASI-V2-MOTOR-DAHIL-TR.mp4');assert sha(previous)=='c1f76f6836aa53091bc602ad9d52e941e350742cd214aa7f5ba5065e98e3a8aa'
lesson=one(ROOT/'external','BELGESELSEMO-EGITIM-BOLUM-04-RESMI-DOSYA-CIZIMLI-TR.mp4');rp=min((ROOT/'external').rglob('probe-report.json'),key=lambda p:len(p.parts));r=json.loads(rp.read_text());assert r['status']=='PASS' and sha(lesson)==r['tutorial_delivery']['sha256'];assert r['console_visibility_audit']['status']=='PASS' and r['pointer_tracking_audit']['status']=='PASS';assert r['native_illustration_acceptance']['status']=='PASS';draw=r['presentation_audit']['native_teaching_marks'];assert draw['status']=='PASS' and {'rectangle','rounded_rectangle','ellipse','freehand_loop','highlight'}<=set(draw['kinds']);c=next(c for c in r['functional_cases'] if c['id']=='official-external-native-idm-download');assert c['status']=='PASS' and c['localhost_fixture_used'] is False;assert c['publisher_digest']=='sha256:'+c['sha256'];assert c['bytes']==1663506 and r['actual_output_file_manager_opened'];assert r['actual_pasted_direct_url']==r['official_page_verified_link']==c['requested_url'];assert c['requested_url']=='https://github.com/ip7z/7zip/releases/download/26.05/7z2605-x64.exe'
# The previous episode's engine-04 speech ends at 1426.859346 s in this
# assembly; trim after its breathing room, before the local fixture is shown.
# Original cues prove local transfer speech starts at 1444.051191 s.
cut=1427.833334;assert 1426.859346<cut<1444.051191
prefix=OUT/'preserved-approved-prefix.mp4'
subprocess.run(['ffmpeg','-v','warning','-y','-i',str(previous),'-t',str(cut),'-map','0:v:0','-map','0:a:0','-map_metadata','-1','-map_chapters','-1','-c','copy',str(prefix)],check=True)
p,e=probe(previous),probe(lesson);offset=float(probe(prefix)['format']['duration']);duration=offset+float(e['format']['duration']);chapters=[{'title':x['tags']['title'],'start':float(x['start_time']),'end':min(offset,float(x['end_time']))} for x in p['chapters'] if float(x['start_time'])<cut]
titles={'ext-01.mp3':'Resmî dış kaynak — 7-Zip','ext-02.mp3':'Bağlantı ve doğru mimariyi seçme','ext-03.mp3':'Panodan gerçek dosya adresini yapıştırma','ext-04.mp3':'IDM ile dış bağlantıya gönderme','ext-05.mp3':'Yayıncı boyutu ve SHA-256 doğrulaması','ext-06.mp3':'Gerçek hedef dosyanın konumu','ext-07.mp3':'Doğrulanan kapsam ve sınırlar'}
prefix_chapter_count=len(chapters)
for q in r['tutorial_audio_cues']:chapters.append({'title':titles[q['audio_file']],'start':offset+q['video_offset_seconds'],'end':duration})
chapters[prefix_chapter_count]['start']=offset
for i in range(len(chapters)-1):chapters[i]['end']=chapters[i+1]['start']
metadata=OUT/'chapters.ffmetadata';s=';FFMETADATA1\ntitle=ÇALIŞMA KOPYASI V3 — çizimli gerçek dış indirme\ncomment=Partial scope. Local fixture transfer replaced by actual official 7-Zip file; approved promo and installation sections preserved without re-encoding.\n'
for x in chapters:s+='[CHAPTER]\nTIMEBASE=1/1000\nSTART='+str(round(x['start']*1000))+'\nEND='+str(round(x['end']*1000))+'\ntitle='+x['title']+'\n'
metadata.write_text(s);concat=OUT/'sources.concat';concat.write_text("file '"+str(prefix.resolve())+"'\nfile '"+str(lesson.resolve())+"'\n");target=OUT/'BELGESELSEMO-EGITIM-CALISMA-KOPYASI-V3-RESMI-INDIRME-CIZIMLI-TR.mp4'
with (OUT/'concat.log').open('wb') as f:subprocess.run(['ffmpeg','-v','warning','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(metadata),'-map','0:v:0','-map','0:a:0','-map_metadata','1','-map_chapters','1','-c','copy','-movflags','+faststart',str(target)],stdout=f,stderr=f,check=True)
actual=probe(target);assert abs(float(actual['format']['duration'])-duration)<.3;assert len(actual['chapters'])==len(chapters);check=subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,text=True);assert check.returncode==0 and not check.stderr,check.stderr
md5=hashlib.md5(target.read_bytes()).hexdigest()
with target.open('rb') as f:u=requests.post('https://upload.gofile.io/uploadfile',files={'file':(target.name,f,'video/mp4')},timeout=(30,600))
u.raise_for_status();j=u.json();assert j['status']=='ok';j=j['data'];assert j['size']==target.stat().st_size and j['md5']==md5
receipt={'file':target.name,'download_page':j['downloadPage'],'bytes':target.stat().st_size,'duration':float(actual['format']['duration']),'sha256':sha(target),'md5':md5,'full_decode':'PASS','full_scope_film_complete':False,'assembly':'Stream copy; approved promo/four installation lessons/motor setup preserved, local fixture section omitted; actual official external lesson substituted','previous_copy_unchanged':True,'preserved_prefix_cut_requested':cut,'preserved_prefix_duration':offset,'chapters':chapters,'official_lesson':r['tutorial_delivery'],'verified_output':c,'illustration_kinds':draw['kinds'],'voice_rate':1.0,'remaining_scope':'Windows/RPM/Arch, browser automatic capture, hoster/video/playlist/P2P matrix, exhaustive GUI and final studio edit.'};(PROOF/'GOFILE-EGITIM-CALISMA-KOPYASI-V3-RESMI.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
for kind in ['rectangle','rounded_rectangle','ellipse','freehand_loop','highlight']:
 m=next(m for m in draw['rendered'] if m['rendered_kind']==kind);subprocess.run(['ffmpeg','-v','error','-y','-ss',str(offset+m['start']+2),'-i',str(target),'-frames:v','1','-vf','scale=1280:-2','-q:v','3',str(PROOF/('BIRLESIK-CIZIM-'+kind+'.jpg'))],check=True)
print('OFFICIAL_ASSEMBLY',json.dumps(receipt,ensure_ascii=False),flush=True)
