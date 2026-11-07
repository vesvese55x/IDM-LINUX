"""Read-only language and real-font gates. Never substitutes painted text for an application UI."""
import json,subprocess,string,re
from pathlib import Path
from fontTools.ttLib import TTFont,TTCollection
from idm_linux.i18n import I18nManager,find_all_language_dirs
MOJIBAKE=['\ufffd','Ã§','Ã‡','Ä±','Ä°','ÄŸ','Äž','ÅŸ','Åž','Ã¶','Ã–','Ã¼','Ãœ','þ','Þ','ð','Ð','ý','Ý']
TURKISH='ÇĞİÖŞÜçğıöşü'
def assert_clean(text):
 bad=[s for s in MOJIBAKE if s in text]
 assert not bad,{'mojibake_patterns':bad,'text':text}
def catalogue_gate(out):
 manager=I18nManager('tr');tr=manager._get_table('tr');en=manager._get_table('en');paths=[]
 for d in find_all_language_dirs():
  p=d/'tr.txt'
  if p.exists():p.read_text(encoding='utf-8-sig',errors='strict');paths.append(str(p))
 assert tr and set(en)<=set(tr),'Turkish catalogue would fall back to English'
 for key,value in tr.items():assert_clean(value)
 report={'scope':'wrapper Turkish catalogue, not vendor IDM visual acceptance','turkish_keys':len(tr),'english_reference_keys':len(en),'english_fallback_keys':sorted(set(en)-set(tr)),'strict_utf8':True,'mojibake_patterns_absent':True,'source_files':paths,'brands_and_original_filenames_not_translated':True}
 (out/'turkish-catalogue-gate.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));return report

def font_gate(family, required_characters=TURKISH):
 path=subprocess.check_output(['fc-match','-f','%{file}',family],text=True).strip();assert path
 if path.lower().endswith(('.ttc','.otc')):fonts=TTCollection(path).fonts
 else:fonts=[TTFont(path)]
 required=set(map(ord,required_characters));coverage=set()
 for font in fonts:coverage.update(font.getBestCmap() or {})
 assert required<=coverage,{'font':family,'file':path,'missing':[chr(c) for c in required-coverage]}
 return {'actual_tk_family':family,'font_file':path,'required_characters':required_characters,'all_required_real_glyphs_present':True}

def visible_widget_gate(root,out,stage):
 import tkinter.font as tkfont
 labels=[];fonts={}
 from idm_linux.gui import pick_ui_font_family
 primary=font_gate(pick_ui_font_family(root,'tr'))
 def walk(w):
  for child in w.winfo_children():yield child;yield from walk(child)
 for w in walk(root):
  if not w.winfo_ismapped():continue
  try:text=str(w.cget('text'))
  except Exception:text=''
  if text:assert_clean(text);labels.append({'widget':str(w),'text':text})
  try:
   actual=tkfont.Font(root=root,font=w.cget('font')).actual();family=actual['family']
   if family:
    # Language names/previews intentionally use CJK or other script fonts.
    # Require full TR coverage for each font actually used to draw Turkish letters.
    has_turkish=any(c in text for c in TURKISH)
    old=fonts.get(family)
    if old is None or (has_turkish and not old['required_characters']):fonts[family]=font_gate(family,TURKISH if has_turkish else '')
  except Exception as e:
   if isinstance(e,AssertionError):raise
   # Widgets without text fonts (frames/images) are not text evidence.
   continue
 assert labels and fonts
 report={'scope':'real visible Tk labels and selected font outlines; requires separate screenshot review','stage':stage,'labels':labels,'fonts':list(fonts.values()),'primary_turkish_font':primary,'scope_note':'CJK-only language names are not required to contain unused Turkish glyphs; every actual Turkish label font is checked for the full Turkish set','native_vendor_IDM_NOT_certified':True}
 (out/(stage+'-turkish-widget-gate.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2));return report

def native_readiness(out):
 from idm_linux.config import IdmLinuxConfig
 from idm_linux.installer import resolve_effective_idm_language
 cfg=IdmLinuxConfig.load();exe=cfg.find_idm_exe();lang_id,lang_file=resolve_effective_idm_language(cfg)
 report={'wrapper_language':cfg.language,'native_executable_present':bool(exe),'native_language_id':lang_id,'native_language_file':lang_file,'native_visual_glyph_acceptance':'NOT_VERIFIED','final_native_lesson_export_allowed':False}
 if exe:
  report['turkish_language_resource_present']=(exe.parent/'Languages'/'idm_tr.lng').is_file()
  report['native_turkish_selection_matches']=(lang_id==0x1f and lang_file=='idm_tr.lng')
 else:report['reason']='Native IDM is not installed in this preparation job; wrapper success is not native success.'
 (out/'native-turkish-readiness-NOT-FINAL.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));return report
