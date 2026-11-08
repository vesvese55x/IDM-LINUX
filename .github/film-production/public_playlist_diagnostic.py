"""One ordinary original CLI simulated extraction; no auth/bot/CAPTCHA workaround."""
import os,json,subprocess,shutil,re
from pathlib import Path
O=Path('out/film14-public-playlist-diagnostic').resolve();O.mkdir(parents=True,exist_ok=True)
for k,v in [('XDG_CONFIG_HOME','config'),('XDG_DATA_HOME','data'),('XDG_CACHE_HOME','cache')]:os.environ[k]=str(O/v)
from idm_linux.stream_engine import find_ytdlp
exe=find_ytdlp();assert exe
p=subprocess.run([exe,'--simulate','--no-playlist','--verbose','--retries','0','--extractor-retries','0','https://www.youtube.com/watch?v=l5OZu-IrXpw'],capture_output=True,text=True,timeout=150)
def safe(text):return re.sub(r'https?://[^\s]+',lambda m:m.group(0).split('?')[0],text)[-14000:]
r={'scope':'Original CLI simulation diagnostic only, not transfer proof','actual_executable':exe,'actual_exit_code':p.returncode,'actual_stdout':safe(p.stdout),'actual_stderr':safe(p.stderr),'available_runtimes':{x:shutil.which(x) for x in ['deno','node','bun','qjs']},'cookies_or_proxy_injected':False,'finished_lesson':False,'final_film_export_allowed':False}
(O/'actual-public-playlist-diagnostic.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
