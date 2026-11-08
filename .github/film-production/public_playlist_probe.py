"""One ordinary original playlist extractor probe of a real public Blender playlist.
Metadata only: NOT download, native GUI, authorization/interception or finished lesson proof.
No cookies, proxies, CAPTCHA/auth/rate-limit circumvention or substituted extractor.
"""
import os,json,time
from pathlib import Path
O=Path('out/film14-public-playlist').resolve();O.mkdir(parents=True,exist_ok=True)
for k,v in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache')]:os.environ[k]=str(O/v)
from idm_linux.stream_engine import probe_playlist_entries
url='https://www.youtube.com/playlist?list=PL6B3937A5D230E335'
r={'scope':'One normal public playlist metadata probe, not transfer or GUI proof','source_url':url,'source_title':'Official Blender Open Movies','private_media_in_artifact':False,'finished_lesson':False,'final_film_export_allowed':False,'cookie_or_proxy_injected':False}
start=time.monotonic()
try:
 result=probe_playlist_entries(url,max_items=3);r['actual_original_probe']=result
 r['actual_metadata_probe_pass']=bool(result.get('ok') and len(result.get('entries',[]))==3)
 r['elapsed_seconds']=time.monotonic()-start
 (O/'actual-public-playlist-review.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
 assert r['actual_metadata_probe_pass'],'Normal public playlist extraction did not return three actual entries. Do not bypass or claim a lesson.'
finally:(O/'actual-public-playlist-review.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
