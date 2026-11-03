"""Append the reviewed real motor lesson to the existing partial training copy."""
from pathlib import Path
import json,subprocess,hashlib,requests
ROOT=Path('append-sources');OUT=Path('assembled-engine');OUT.mkdir(exist_ok=True);PROOF=OUT/'receipts';PROOF.mkdir(exist_ok=True)
def one(directory,name):
 paths=list(directory.rglob(name));assert len(paths)==1,(str(directory),name,len(paths));return paths[0]
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def probe(p):return json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-show_chapters','-of','json',str(p)],text=True))
previous=one(ROOT/'previous','BELGESELSEMO-EGITIM-TAMAMLANAN-BOLUMLER-CALISMA-KOPYASI-TR.mp4');assert digest(previous)=='cd37e73ad65df0bc2fb02cf41d7e5ef13302be790a17b1c9ed94fc04d315cb30'
lesson=one(ROOT/'engine','BELGESELSEMO-EGITIM-BOLUM-03-MOTOR-VE-AKTARIM-TR.mp4');report_path=min((ROOT/'engine').rglob('probe-report.json'),key=lambda p:len(p.parts));report=json.loads(report_path.read_text());assert report['status']=='PASS';assert report['console_visibility_audit']['status']=='PASS';assert report['pointer_tracking_audit']['status']=='PASS';assert digest(lesson)==report['tutorial_delivery']['sha256'];cases={c['id']:c for c in report['functional_cases']}
for name in ['real-released-gui-motor-installation','real-linux-idm-pause','real-linux-idm-resume-and-output-hash']:assert cases[name]['status']=='PASS'
assert cases['real-linux-idm-pause']['bytes_in_settled_3_seconds']==0;assert cases['real-linux-idm-resume-and-output-hash']['nonzero_range_requests_after_resume']>0;assert report['verified_output']['sha256']==report['verified_output']['expected_sha256'];assert report['actual_output_file_manager_opened']
p=probe(previous);e=probe(lesson);offset=float(p['format']['duration']);duration=offset+float(e['format']['duration']);chapters=[{'title':c['tags']['title'],'start':float(c['start_time']),'end':float(c['end_time'])} for c in p['chapters']]
chapter_titles={'engine-01.mp3':'Linux — gerçek motor hazırlığı','engine-04.mp3':'Motor — ayarlar ve görünür indirme','transfer-01.mp3':'Kontrollü gerçek dosya aktarımı','transfer-03.mp3':'Duraklatma — gerçek bayt ölçümü','transfer-04.mp3':'Devam ve içerik doğrulaması','transfer-05.mp3':'İndirilen gerçek dosyanın konumu','engine-wrap.mp3':'Bu bölümde doğrulanan kapsam'}
for cue in report['tutorial_audio_cues']:
 if cue['audio_file'] in chapter_titles:chapters.append({'title':chapter_titles[cue['audio_file']],'start':offset+cue['video_offset_seconds'],'end':duration})
# Include the first two seconds of the real new lesson in its own chapter.
chapters[5]['start']=offset
for i in range(len(chapters)-1):chapters[i]['end']=chapters[i+1]['start']
meta=OUT/'chapters.ffmetadata';text=';FFMETADATA1\ntitle=ÇALIŞMA KOPYASI V2 — tamamlanan bölümler\ncomment=Partial training assembly; not the finished full-scope film. Includes controlled owned local HTTP fixture, not proof of external hosters or browser integration.\n'
for c in chapters:text+='[CHAPTER]\nTIMEBASE=1/1000\nSTART='+str(round(c['start']*1000))+'\nEND='+str(round(c['end']*1000))+'\ntitle='+c['title']+'\n'
meta.write_text(text,encoding='utf-8');concat=OUT/'source.concat';concat.write_text("file '"+str(previous.resolve())+"'\nfile '"+str(lesson.resolve())+"'\n")
target=OUT/'BELGESELSEMO-EGITIM-CALISMA-KOPYASI-V2-MOTOR-DAHIL-TR.mp4'
with (OUT/'concat.log').open('wb') as log:subprocess.run(['ffmpeg','-v','warning','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(meta),'-map','0:v:0','-map','0:a:0','-map_metadata','1','-map_chapters','1','-c','copy','-movflags','+faststart',str(target)],stdout=log,stderr=log,check=True)
result=probe(target);actual=float(result['format']['duration']);assert abs(actual-duration)<.3;assert len(result['chapters'])==len(chapters);decoded=subprocess.run(['ffmpeg','-v','error','-i',str(target),'-f','null','-'],capture_output=True,text=True);assert decoded.returncode==0 and not decoded.stderr,decoded.stderr
md5=hashlib.md5(target.read_bytes()).hexdigest()
with target.open('rb') as f:r=requests.post('https://upload.gofile.io/uploadfile',files={'file':(target.name,f,'video/mp4')},timeout=(30,600))
r.raise_for_status();d=r.json();assert d['status']=='ok';d=d['data'];assert d['md5']==md5 and d['size']==target.stat().st_size
receipt={'file':target.name,'download_page':d['downloadPage'],'duration':actual,'bytes':target.stat().st_size,'sha256':digest(target),'md5':md5,'full_decode':'PASS','chapters':chapters,'voice_rate':1.0,'assembly':'Stream copy; previous copy and lesson unchanged','full_scope_film_complete':False,'scope':'Approved promo plus four Linux package lessons plus motor and owned local HTTP fixture. Windows/RPM/Arch, browser-to-IDM, external hosters/YouTube/playlist/P2P, exhaustive GUI and final studio edit remain outside this completed scope.','engine_lesson_delivery':report['tutorial_delivery'],'engine_lesson_run':report['run_id'],'verified_output':report['verified_output'],'pause_case':cases['real-linux-idm-pause'],'resume_case':cases['real-linux-idm-resume-and-output-hash']};(PROOF/'GOFILE-EGITIM-CALISMA-KOPYASI-V2.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2));pause=next(c for c in report['tutorial_audio_cues'] if c['audio_file']=='transfer-03.mp3')['video_offset_seconds'];subprocess.run(['ffmpeg','-v','error','-y','-ss',str(offset+pause+5),'-i',str(target),'-frames:v','1','-vf','scale=1280:-2','-q:v','3',str(PROOF/'CALISMA-KOPYASI-V2-GERCEK-DURAKLATMA.jpg')],check=True)
(PROOF/'CALISMA-KOPYASI-V2.md').write_text('# Tamamlanan eğitim bölümleri — çalışma kopyası V2\n\n**Tam kapsamlı ana film henüz tamamlanmadı.**\n\n'+receipt['download_page']+'\n\nMotor ve kontrollü gerçek dosya aktarımı eklendi. Bu yerel örnek, YouTube veya diğer kaynakların çalıştığını kanıtlamaz.\n\n'+ '\n'.join(f'- {int(c["start"]//60):02}:{int(c["start"]%60):02} — {c["title"]}' for c in chapters),encoding='utf-8');print('APPENDED_REVIEWED_ENGINE',json.dumps(receipt,ensure_ascii=False),flush=True)
