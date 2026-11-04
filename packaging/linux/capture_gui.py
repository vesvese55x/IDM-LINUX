#!/usr/bin/env python3
"""Capture the production Tk application on a real Xvfb screen, in an isolated HOME."""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src'))
PAGES=['installer','overview','browsers','settings','doctor','projects','support','language','about']

def capture(page,output):
    import tkinter as tk
    from PIL import ImageGrab
    from idm_linux.gui import launch_control_panel
    errors=[]
    original=tk.Tk.mainloop
    def monitored(root,*args,**kwargs):
        def callback_error(cls,error,tb):
            errors.append(''.join(traceback.format_exception(cls,error,tb)))
        root.report_callback_exception=callback_error
        def snapshot():
            try:
                root.update_idletasks()
                if not root.winfo_viewable(): raise AssertionError('Production window is not visible')
                w,h=root.winfo_width(),root.winfo_height()
                if w<990 or h<660: raise AssertionError('Unexpected production window geometry')
                if '1.0.0' not in root.title(): raise AssertionError('Product version changed')
                x,y=root.winfo_rootx(),root.winfo_rooty()
                image=ImageGrab.grab(bbox=(x,y,x+w,y+h),xdisplay=os.environ['DISPLAY'])
                if len(image.resize((100,100)).getcolors(10001) or [])<15: raise AssertionError('Blank GUI capture')
                image.save(output/(page+'.png'))
            except Exception: errors.append(traceback.format_exc())
            root.after(100,root.destroy)
        root.after(7000,snapshot)
        original(root,*args,**kwargs)
    tk.Tk.mainloop=monitored
    code=launch_control_panel(initial_page=page,project_root=ROOT)
    if code or errors: raise RuntimeError('Production GUI failed: '+ '\n'.join(errors))
    print('REAL_XVFB_GUI_PAGE_PASS',page)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'artifacts/linux-gui');parser.add_argument('--page',choices=PAGES)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    if args.page: capture(args.page,args.output.resolve());return
    results=[]
    for page in PAGES:
        with tempfile.TemporaryDirectory(prefix='idm-gui-ci-') as home:
            env=dict(os.environ,HOME=home,XDG_CONFIG_HOME=home+'/config',XDG_DATA_HOME=home+'/data',XDG_CACHE_HOME=home+'/cache')
            p=subprocess.run([sys.executable,__file__,'--page',page,'--output',str(args.output.resolve())],env=env,capture_output=True,text=True,timeout=35)
            (args.output/(page+'.log')).write_text(p.stdout+p.stderr)
            if p.returncode: raise RuntimeError('GUI page failed; see '+page+'.log: '+(p.stdout+p.stderr)[-3000:])
            image=args.output/(page+'.png');results.append({'page':page,'bytes':image.stat().st_size,'sha256':hashlib.sha256(image.read_bytes()).hexdigest()});print('REAL_XVFB_GUI_PAGE_PASS',page,flush=True)
    (args.output/'capture-manifest.json').write_text(json.dumps({'status':'PASS','source_commit':os.environ.get('GITHUB_SHA'),'renderer':'Production tkinter under Xvfb; actual X11 screen pixels','native_idman_download_test':False,'pages':results},indent=2))
if __name__=='__main__':main()
