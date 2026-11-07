"""Normal supported installation + read-only native language/font inspection.
No license, trial, registration, downloaded status or application UI text is patched by this test.
"""
import os,json,subprocess,time,hashlib
from pathlib import Path
from idm_linux.config import IdmLinuxConfig
from idm_linux.wine_sender import build_wine_env
from idm_linux.installer import resolve_effective_idm_language
from turkish_quality_gate import assert_clean,catalogue_gate
O=Path('out/film14-native-turkish');O.mkdir(parents=True,exist_ok=True);catalogue_gate(O)
# User-owned demonstration directory, not a renamed third-party download.
cfg=IdmLinuxConfig.load();assert cfg.find_idm_exe() is None,'Expected an isolated fresh CI installation; do not reset existing state';cfg.language='tr';cfg.download_dir=str(Path.home()/'İndirilenler'/'Türkçe_ÇĞİÖŞÜ_çğıöşü');Path(cfg.download_dir).mkdir(parents=True,exist_ok=True);cfg.save()
# Supported application installer, fresh CI environment. No reset/update/repair of existing licensing state.
with (O/'normal-install.log').open('w') as log:
 result=subprocess.run([os.sys.executable,'-m','idm_linux.cli','install','--cli','--yes','--skip-pkgs'],stdout=log,stderr=subprocess.STDOUT,timeout=900)
assert result.returncode==0,'Normal vendor/application installation failed; no alternate route or bypass attempted'
cfg=IdmLinuxConfig.load();exe=cfg.find_idm_exe();assert exe and exe.is_file();lng=exe.parent/'Languages'/'idm_tr.lng';assert lng.is_file(),'Official Turkish language resource missing'
langid,langfile=resolve_effective_idm_language(cfg);assert cfg.language=='tr' and langid==0x1f and langfile=='idm_tr.lng','Would fall back to non-Turkish native language'
env=build_wine_env(cfg);env.update(LANG='tr_TR.UTF-8',LC_ALL='tr_TR.UTF-8')
subprocess.run(['i686-w64-mingw32-gcc','-O2','-o',str(O/'native-turkish-probe.exe'),'.github/film-production/native_turkish_probe.c','-lgdi32','-luser32'],check=True)
# Open the actual application through its supported command, without initiating any download.
subprocess.Popen([os.sys.executable,'-m','idm_linux.cli','open'],stdout=open(O/'normal-open.log','w'),stderr=subprocess.STDOUT)
# Finite startup wait, no clicking unexpected dialogs and no human verification automation.
time.sleep(15)
probe=subprocess.run(['wine',str((O/'native-turkish-probe.exe').resolve())],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90);raw=probe.stdout.decode('utf-8',errors='strict');(O/'native-font-and-text-readonly.txt').write_text(raw);(O/'native-probe-stderr.txt').write_bytes(probe.stderr)
rows=[];fonts=[];acp=None;windows=0
for line in raw.splitlines():
 fields=line.split('\t')
 if fields[0]=='ACP':acp=int(fields[1])
 elif fields[0] in ['TEXT','MENU','WINDOW'] and len(fields)>1:
  text=bytes.fromhex(fields[1]).decode('utf-8',errors='strict');assert_clean(text);rows.append({'kind':fields[0],'text':text});windows+=fields[0]=='WINDOW'
 elif fields[0]=='FONT':fonts.append({'actual_native_font':bytes.fromhex(fields[1]).decode('utf-8'),'missing_turkish_glyphs':int(fields[2])})
menus=[r['text'].replace('&','') for r in rows if r['kind']=='MENU'];tokens=['Görev','Dosya','İndir','Görünüm','Yardım'];found=[token for token in tokens if any(token in text for text in menus)]
subprocess.run(['import','-window','root',str(O/'actual-native-application.png')],check=True)
report={'scope':'actual native main-window/menu and GDI preflight, not a completed chapter or all-dialogue certification','native_executable_sha256':hashlib.file_digest(exe.open('rb'),'sha256').hexdigest(),'original_turkish_language_resource_sha256':hashlib.file_digest(lng.open('rb'),'sha256').hexdigest(),'selected_language_id':langid,'language_file':langfile,'actual_wine_ansi_codepage':acp,'actual_visible_native_windows':windows,'actual_native_fonts':fonts,'actual_native_texts':rows,'turkish_native_menu_tokens_found':found,'native_probe_exit':probe.returncode,'all_download_dialogues_verified':False,'final_episode_export_allowed':False,'no_trial_or_license_reset_called':True}
(O/'native-turkish-preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
assert probe.returncode==0 and fonts and all(r['missing_turkish_glyphs']==0 for r in fonts),'Actual native GDI font is missing Turkish glyphs'
assert acp==1254,'Wine ANSI codepage is not Turkish1254; do not certify legacy text'
assert windows>0 and len(found)>=2,'Actual Turkish native menu evidence is insufficient; no successful native lesson claimed'
# Keep real native application processes, but minimize their actual windows before separate wrapper screenshots.
for line in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
 if 'xfce' not in line.lower():subprocess.run(['xdotool','windowminimize',line.split()[0]],check=False)
print('ACTUAL_NATIVE_MAIN_WINDOW_TURKISH_PREFLIGHT_PASSED_NOT_FULL_EPISODE',flush=True)
