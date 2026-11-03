"""Click the real Brave permission bubble; never fake extension acceptance.
This proves the consent action only, not end-to-end native messaging/downloads.
"""
import time,json

def approve_windows(report,out,screenshot):
 from pywinauto import Desktop
 import psutil
 from feature_cases import norm
 case={'id':'brave-idm-extension-consent','status':'BLOCKED','scope':'Actual user confirmation only; browser-to-IDM download requires separate proof','actions':[]}
 deadline=time.monotonic()+45;clicked=False;browser=None;opening_steps=set()
 try:
  while time.monotonic()<deadline:
   browsers=[]
   for w in Desktop(backend='uia').windows(class_name='Chrome_WidgetWin_1',visible_only=True):
    try:
     if psutil.Process(w.process_id()).name().lower()=='brave.exe':browsers.append(w)
    except Exception:pass
   if not browsers:time.sleep(1);continue
   browser=max(browsers,key=lambda w:w.rectangle().width()*w.rectangle().height());browser.set_focus();time.sleep(.6)
   controls=[]
   for c in browser.descendants():
    try:
     if c.is_visible():controls.append(c)
    except Exception:pass
   snapshot=[]
   for c in controls:
    try:snapshot.append({'name':c.window_text(),'control_type':c.element_info.control_type,'automation_id':c.element_info.automation_id})
    except Exception:pass
   (out/'brave-consent-accessibility.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2),encoding='utf-8')
   enable=[c for c in controls if norm(c.window_text()).strip() in ['enable extension','uzantiyi etkinlestir'] and c.element_info.control_type in ['Button','Hyperlink']]
   if enable:
    screenshot('brave-extension-before-real-confirmation');c=enable[0]
    case['actions'].append({'label':c.window_text(),'video_offset_seconds':time.time()-report['record_wallclock_start']});c.click_input();clicked=True;time.sleep(3)
    screenshot('brave-extension-after-real-confirmation')
    remaining=[]
    for c in browser.descendants():
     try:
      if c.is_visible() and norm(c.window_text()).strip() in ['enable extension','uzantiyi etkinlestir']:remaining.append(c)
     except Exception:pass
    if not remaining:case.update({'status':'PASS','permission_button_clicked':True,'permission_bubble_dismissed':True})
    else:case['reason']='Clicked the genuine permission control, but confirmation bubble remained; no success claimed.'
    break
   # When focus was lost the bubble may have closed, while its action-required
   # item remains in the actual browser menu. Reopen it through real controls.
   candidate=None;kind=None
   for c in controls:
    name=norm(c.window_text())
    if 'action required' in name or 'islem gerekli' in name:
     if 'menu' not in opening_steps:candidate=c;kind='menu';break
    if 'idm integration module' in name and any(x in name for x in ['added','eklen']):
     if 'extension_item' not in opening_steps:candidate=c;kind='extension_item';break
   if candidate:
    opening_steps.add(kind);case['actions'].append({'label':candidate.window_text(),'video_offset_seconds':time.time()-report['record_wallclock_start']});candidate.click_input();time.sleep(1)
   else:time.sleep(1)
  if not clicked:case['reason']='Real Brave extension consent control was not discoverable; accessibility evidence retained, no fake enable or UI patch used.'
 except Exception as e:case['reason']=type(e).__name__+': '+str(e)
 report.setdefault('functional_cases',[]).append(case)
 report['brave_extension_end_to_end_download']='NOT_RUN'
 (out/'brave-consent-result.json').write_text(json.dumps(case,ensure_ascii=False,indent=2),encoding='utf-8')
 return case
