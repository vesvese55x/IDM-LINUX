"""Unmodified official vendor payload + read-only native language/font inspection.
Never call the product installer/open pipeline: it substitutes integrity-checked helper binaries.
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
# Configure only ordinary regional/UI language settings before the first native launch.
from idm_linux.installer import initialize_wine_prefix
initialize_wine_prefix(cfg,log_fn=lambda message:None)
locale_env=build_wine_env(cfg);locale_env.update(LANG='tr_TR.UTF-8',LC_ALL='tr_TR.UTF-8',LANGUAGE='tr_TR:tr',LC_MESSAGES='tr_TR.UTF-8')
regional=r"""Windows Registry Editor Version 5.00

[HKEY_CURRENT_USER\Control Panel\International]
"Locale"="0000041f"
"LocaleName"="tr-TR"
"sLanguage"="TRK"
"sCountry"="Türkiye"
[HKEY_CURRENT_USER\Control Panel\Desktop]
"PreferredUILanguages"=hex(7):74,00,72,00,2d,00,54,00,52,00,00,00,00,00
[HKEY_LOCAL_MACHINE\System\CurrentControlSet\Control\Nls\Language]
"Default"="041f"
"InstallLanguage"="041f"
[HKEY_LOCAL_MACHINE\System\CurrentControlSet\Control\Nls\CodePage]
"ACP"="1254"
"OEMCP"="857"
"MACCP"="10081"
"""
regional_file=O/'ordinary-turkish-regional-settings.reg';regional_file.write_bytes(b'\xff\xfe'+regional.replace('\n','\r\n').encode('utf-16-le'))
subprocess.run(['wine','regedit','/S',str(regional_file.resolve())],env=locale_env,check=True,timeout=60)
# Restart the new Wine session, retaining every prefix/registry file; this is not a trial reset.
subprocess.run(['wineserver','-k'],env=locale_env,check=True,timeout=30)
subprocess.run(['wineserver','-w'],env=locale_env,check=True,timeout=30)
os.environ.update({k:locale_env[k] for k in ['LANG','LC_ALL','LANGUAGE','LC_MESSAGES']})

# Decompress the official vendor payload byte-for-byte, preserving every driver/helper.
# No normal-install/open/repair pipeline, hook stubs, licensing keys or integrity substitutions.
from idm_linux.installer import download_idm_installer, resolve_latest_official_idm_release, sync_idm_language_live
from idm_linux.sfx_unpacker import unpack_idm_installer
url,filename,release=resolve_latest_official_idm_release(cfg.idm_installer_url)
from urllib.parse import urlparse
assert urlparse(url).scheme=='https' and urlparse(url).hostname in ['internetdownloadmanager.com','www.internetdownloadmanager.com','download.internetdownloadmanager.com'],'Only the official vendor HTTPS host is allowed'
package=download_idm_installer(url,O/filename)
target=cfg.idm_exe_candidates()[0].parent
written=unpack_idm_installer(package,target)
assert written and all(path.resolve().is_relative_to(target.resolve()) for path in written.values())
original_hashes={name:hashlib.file_digest(path.open('rb'),'sha256').hexdigest() for name,path in written.items()}
(O/'original-vendor-payload-manifest.json').write_text(json.dumps({'source':url,'release_label':release,'package_sha256':hashlib.file_digest(package.open('rb'),'sha256').hexdigest(),'mode':'original decompressed vendor payload, not a full installer certification','files':original_hashes},ensure_ascii=False,indent=2))
sync_idm_language_live(cfg)
cfg=IdmLinuxConfig.load();exe=cfg.find_idm_exe();assert exe and exe.is_file();lng=exe.parent/'Languages'/'idm_tr.lng';assert lng.is_file(),'Official Turkish language resource missing'
langid,langfile=resolve_effective_idm_language(cfg);assert cfg.language=='tr' and langid==0x1f and langfile=='idm_tr.lng','Would fall back to non-Turkish native language'
env=build_wine_env(cfg);env.update(LANG='tr_TR.UTF-8',LC_ALL='tr_TR.UTF-8')
subprocess.run(['i686-w64-mingw32-gcc','-O2','-o',str(O/'native-turkish-probe.exe'),'.github/film-production/native_turkish_probe.c','-lgdi32','-luser32'],check=True)
# Initialize a credential-free CI browser before the vendor may open its welcome page.
# No account, password, keyring unlock, human verification or browser download is performed.
subprocess.Popen(['brave-browser','--no-sandbox','--no-first-run','--disable-sync','--password-store=basic','--disable-background-mode','about:blank'],stdout=open(O/'credential-free-browser.log','w'),stderr=subprocess.STDOUT)
time.sleep(3)
# Open the original vendor executable directly; no wrapper hooks or native download.
subprocess.Popen(['wine',str(exe)],env=env,stdout=open(O/'unmodified-native-open.log','w'),stderr=subprocess.STDOUT)
# Finite startup wait, no clicking unexpected dialogs and no human verification automation.
time.sleep(15)
# Reveal actual native UI, rather than accepting a desktop screenshot obscured by the welcome browser.
for line in subprocess.check_output(['wmctrl','-lx'],text=True).splitlines():
 if 'brave' in line.lower():subprocess.run(['xdotool','windowminimize',line.split()[0]],check=False)
for line in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
 if 'Internet Download Manager' in line:subprocess.run(['wmctrl','-ia',line.split()[0]],check=False)
time.sleep(1)
probe=subprocess.run(['wine',str((O/'native-turkish-probe.exe').resolve())],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90);raw=probe.stdout.decode('utf-8',errors='strict');(O/'native-font-and-text-readonly.txt').write_text(raw);(O/'native-probe-stderr.txt').write_bytes(probe.stderr)
# WineHQ 11 may expose the vendor's informational administrator-token notice.
# Acknowledge ONLY this exact known notice, without ticking its suppression box.
# This is not an activation/authentication/trial dialog and does not fix browser interception.
known_notice="Uyarı: IDM'yi Yönetici hakları ile çalıştırıyorsunuz."
notice_seen=any(known_notice in bytes.fromhex(line.split('\t')[1]).decode('utf8') for line in raw.splitlines() if line.startswith('TEXT\t'))
if notice_seen:
 (O/'expected-administrator-notice-raw.txt').write_text(raw)
 for line in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
  if line.endswith(' IDM'):subprocess.run(['wmctrl','-ia',line.split()[0]],check=True)
 time.sleep(.4)
 notice_probe=subprocess.run(['wine',str((O/'native-turkish-probe.exe').resolve())],env=env,stdout=subprocess.PIPE,check=True,timeout=30)
 buttons=[]
 for line in notice_probe.stdout.decode('utf8').splitlines():
  a=line.split('\t')
  if a[0]=='CONTROL' and len(a)>7 and a[6]=='1' and bytes.fromhex(a[2]).decode()=='Button' and bytes.fromhex(a[7]).decode().replace('&','')=='Tamam':buttons.append([int(v) for v in a[5].split(',')])
 assert len(buttons)==1,'Known notice did not have one unambiguous real OK button; stop'
 x1,y1,x2,y2=buttons[0];subprocess.run(['xdotool','mousemove',str((x1+x2)//2),str((y1+y2)//2),'click','1'],check=True)
 time.sleep(2)
 probe=subprocess.run(['wine',str((O/'native-turkish-probe.exe').resolve())],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
 raw=probe.stdout.decode('utf8',errors='strict');(O/'native-font-and-text-readonly.txt').write_text(raw)
subprocess.run(['import','-window','root',str(O/'actual-native-application-before-text-gate.png')],check=True)
owner_locales=[]
for entry in Path('/proc').iterdir():
 if not entry.name.isdigit():continue
 try:
  name=(entry/'comm').read_text().strip()
  if name.lower()!='idman.exe':continue
  proc_env=dict(x.split(b'=',1) for x in (entry/'environ').read_bytes().split(b'\0') if b'=' in x)
  if proc_env.get(b'WINEPREFIX',b'').decode()!=cfg.wine_prefix:continue
  owner_locales.append({'pid':int(entry.name),'locale_only':{k:proc_env.get(k.encode(),b'').decode(errors='strict') for k in ['LANG','LC_ALL','LC_MESSAGES','LANGUAGE']}})
 except (OSError,UnicodeDecodeError):continue
rows=[];fonts=[];acp=None;windows=0;text_failures=[]
for line in raw.splitlines():
 fields=line.split('\t')
 if fields[0]=='ACP':acp=int(fields[1])
 elif fields[0] in ['TEXT','MENU','WINDOW'] and len(fields)>1:
  text=bytes.fromhex(fields[1]).decode('utf-8',errors='strict')
  try:assert_clean(text)
  except AssertionError as e:text_failures.append(str(e))
  rows.append({'kind':fields[0],'text':text});windows+=fields[0]=='WINDOW'
 elif fields[0] in ['FONT_UI','FONT_TEST']:fonts.append({'measurement_kind':fields[0],'font_family':bytes.fromhex(fields[1]).decode('utf-8'),'missing_turkish_glyphs':int(fields[2])})
menus=[r['text'].replace('&','') for r in rows if r['kind'] in ['MENU','TEXT']];tokens=['Görev','Dosya','İndir','Görünüm','Yardım','Kategoriler','Şunu bul','Ayarlar'];found=[token for token in tokens if any(token in text for text in menus)]
subprocess.run(['import','-window','root',str(O/'actual-native-application.png')],check=True)
report={'scope':'actual native main-window/menu and GDI preflight, not a completed chapter or all-dialogue certification','wine_runtime_version':subprocess.check_output(['wine','--version'],text=True).strip(),'expected_vendor_admin_notice_acknowledged':notice_seen,'browser_interception_under_admin_token_verified':False,'native_executable_sha256':hashlib.file_digest(exe.open('rb'),'sha256').hexdigest(),'original_turkish_language_resource_sha256':hashlib.file_digest(lng.open('rb'),'sha256').hexdigest(),'selected_language_id':langid,'language_file':langfile,'read_only_probe_process_ansi_codepage':acp,'actual_native_owner_process_locales':owner_locales,'raw_native_text_quality_failures':text_failures,'actual_visible_native_windows':windows,'sampled_actual_native_control_fonts':[f for f in fonts if f['measurement_kind']=='FONT_UI'],'explicitly_created_test_fonts':[f for f in fonts if f['measurement_kind']=='FONT_TEST'],'all_native_control_fonts_verified':False,'optional_message_queries_unavailable':[line for line in raw.splitlines() if line.startswith('QUERY_UNAVAILABLE')],'actual_native_texts':rows,'turkish_native_menu_tokens_found':found,'native_probe_exit':probe.returncode,'all_download_dialogues_verified':False,'final_episode_export_allowed':False,'no_trial_or_license_reset_called':True,'no_product_install_open_repair_or_stub_path_called':True,'vendor_payload_binary_files_unchanged':all(path.is_file() and hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==original_hashes[name] for name,path in written.items() if path.suffix.lower() in ['.exe','.dll','.sys'])}
(O/'native-turkish-preflight.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
assert report['vendor_payload_binary_files_unchanged'],'Vendor binaries changed; no evidence may be certified'
assert not text_failures,'Actual raw native text is still corrupted; inspect the real screenshot, never repaint labels'
assert probe.returncode==0,'Native probe failed; this does not by itself prove missing font glyphs'
assert fonts and all(r['missing_turkish_glyphs']==0 for r in fonts),'Actual native GDI font is missing Turkish glyphs'
assert acp==1254,'Wine ANSI codepage is not Turkish1254; do not certify legacy text'
assert windows>0 and len(found)>=2,'Actual Turkish native menu evidence is insufficient; no successful native lesson claimed'
# Inspect actual settings dialogs without changing or saving any setting.
if '--isolated-fileinfo' not in os.sys.argv:
 subprocess.run([os.sys.executable,'.github/film-production/native_settings_readonly.py'],env=env,check=True,timeout=240)
else:
 (O/'isolated-fileinfo-scope.json').write_text(json.dumps({'settings_navigation_performed_in_this_process':False,'reason':'Separate fixture inspection from unverified post-scheduler state. Earlier probe timeouts used a wrong Wine prefix and do not prove a native hang. Do not claim end-to-end scheduler stability.','all_fonts_certified':False}))
# Keep real native application processes, but minimize their actual windows before separate wrapper screenshots.
for line in subprocess.check_output(['wmctrl','-l'],text=True).splitlines():
 if 'xfce' not in line.lower():subprocess.run(['xdotool','windowminimize',line.split()[0]],check=False)
print('ACTUAL_NATIVE_MAIN_WINDOW_TURKISH_PREFLIGHT_PASSED_NOT_FULL_EPISODE',flush=True)
