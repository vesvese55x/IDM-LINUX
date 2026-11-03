"""Read-only Tk widget introspection for automation of the unmodified release.
No UI is replaced; clicks happen externally through the real X11 desktop.
Enabled only in the application child process via FILM_WIDGET_DUMP.
"""
import os
if os.environ.get('FILM_WIDGET_DUMP'):
    import tkinter as tk
    import json,time
    from pathlib import Path
    original=tk.Tk.mainloop
    def mainloop(self,*a,**kw):
        path=Path(os.environ['FILM_WIDGET_DUMP'])
        def dump():
            try:
                if self.winfo_viewable() and not getattr(self,'_film_viewport_set',False):
                    self.geometry('1880x1000+10+10');self._film_viewport_set=True
                out=[]
                def walk(w):
                    if w.winfo_viewable():
                        try:text=str(w.cget('text'))
                        except Exception:text=''
                        out.append({'path':str(w),'class':w.winfo_class(),'text':text,'rect':[w.winfo_rootx(),w.winfo_rooty(),w.winfo_width(),w.winfo_height()]})
                    for child in w.winfo_children():walk(child)
                walk(self)
                data={'time':time.time(),'root_title':self.title(),'root_viewable':bool(self.winfo_viewable()),'window_id':self.frame(),'root_rect':[self.winfo_rootx(),self.winfo_rooty(),self.winfo_width(),self.winfo_height()],'widgets':out}
                tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');tmp.replace(path)
            except Exception:pass
            self.after(400,dump)
        self.after(500,dump)
        return original(self,*a,**kw)
    tk.Tk.mainloop=mainloop
