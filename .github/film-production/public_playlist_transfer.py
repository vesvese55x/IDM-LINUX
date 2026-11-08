"""Actual unmodified serial playlist backend on real public Blender Open Movies.
No mocked progress, cookies, proxies, helper replacements, or third-party media artifacts.
This is backend proof only, never a completed GUI or full-film claim.
"""
import os,time,json,subprocess,hashlib
from pathlib import Path
O=Path('out/film14-public-playlist-transfer').resolve();O.mkdir(parents=True,exist_ok=True)
for k,v in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache')]:os.environ[k]=str(O/v)
from idm_linux.stream_engine import probe_playlist_entries
from idm_linux.playlist_batch import PlaylistBatchManager
url='https://www.youtube.com/playlist?list=PL6B3937A5D230E335'
r={'scope':'Original backend only, actual public playlist selected entries 1 and 3; not GUI/native IDM/interception proof','source_url':url,'attribution':'Blender Studio / Blender Foundation — Official Blender Open Movies','attribution_source':'https://studio.blender.org/films/','downloaded_media_in_artifact':False,'finished_lesson':False,'final_film_export_allowed':False,'actual_states':[]}
def save():(O/'actual-public-playlist-transfer-review.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
manager=PlaylistBatchManager(base_dir=O/'actual-downloads')
try:
 # Normal upstream dependencies only. No altered clients, cookies or proxies.
 import runpy
 runpy.run_path('.github/film-production/public_playlist_diagnostic.py',run_name='__main__')
 diagnostic=json.loads(Path('out/film14-public-playlist-diagnostic/actual-public-playlist-diagnostic.json').read_text())
 r['ordinary_dependency_precheck_exit_code']=diagnostic['actual_exit_code'];save()
 assert diagnostic['actual_exit_code']==0,'Ordinary access still denied: stop without auth/bot workaround or transfer attempt'
 info=probe_playlist_entries(url,max_items=3);r['actual_probe']=info;save();assert info.get('ok') and len(info.get('entries',[]))==3
 chosen=[info['entries'][0],info['entries'][2]];r['actual_selected_entries']=chosen
 start=manager.start_batch(url,chosen,str(O/'actual-downloads'));r['actual_start']=start;save();assert start['ok']
 deadline=time.monotonic()+600
 while time.monotonic()<deadline:
  st=manager.status(start['batch_id']);r['actual_states'].append(st);save()
  if st and st.get('done'):break
  assert sum(p.stat().st_size for p in (O/'actual-downloads').rglob('*') if p.is_file())<4*1024**3,'Bounded recording-resource budget reached'
  time.sleep(1)
 final=manager.status(start['batch_id']);r['actual_final']=final;save()
 assert final and final.get('done') and all(e['status']=='completed' for e in final['entries']),'Actual selected public downloads were not completed; no bypass or GUI success claim'
 files=list(Path(start['out_dir']).glob('*.mp4'));assert len(files)==2
 results=[]
 for f in files:
  p=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(f)],text=True))
  assert {'video','audio'}<={s['codec_type'] for s in p['streams']}
  results.append({'file':f.name,'bytes':f.stat().st_size,'sha256':hashlib.file_digest(f.open('rb'),'sha256').hexdigest(),'duration':p['format']['duration'],'streams':p['streams']})
 r['actual_outputs']=results;r['actual_public_selected_transfers_verified']=True;save()
finally:manager.shutdown_all();save()
