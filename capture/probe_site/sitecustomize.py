"""Observe the released Tk UI including Tcl-native messageboxes. No UI replacement.
The capture viewport is the only geometry override; actions use actual mouse input.
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
                def walk(name):
                    # winfo_children() cannot wrap Tcl-created __tk__messagebox
                    # objects. Query Tcl directly so modal dialogs do not freeze
                    # the observation file or leave stale screen coordinates.
                    call=self.tk.call
                    if self.tk.getboolean(call('winfo','viewable',name)):
                        klass=str(call('winfo','class',name))
                        try:text=str(call(name,'cget','-text'))
                        except Exception:text=''
                        top=str(call('winfo','toplevel',name))
                        try:title=str(call('wm','title',top))
                        except Exception:title=''
                        item={'path':str(name),'class':klass,'text':text,'window_title':title,'toplevel':top,'window_id':str(call('winfo','id',name)),'rect':[int(call('winfo',x,name)) for x in ['rootx','rooty','width','height']]}
                        try:item['state']=str(call(name,'cget','-state'))
                        except Exception:pass
                        try:
                            if klass in ['Entry','TEntry','TCombobox']:item['value']=str(call(name,'get'))
                            elif klass=='Text':item['value']=str(call(name,'get','1.0','end-1c'))
                            elif klass=='TCheckbutton':item['checked']=self.tk.getboolean(call(name,'instate','selected'))
                        except Exception:pass
                        out.append(item)
                    for child in self.tk.splitlist(call('winfo','children',name)):walk(str(child))
                walk(str(self))
                data={'time':time.time(),'root_title':self.title(),'root_viewable':bool(self.winfo_viewable()),'window_id':self.frame(),'root_rect':[self.winfo_rootx(),self.winfo_rooty(),self.winfo_width(),self.winfo_height()],'widgets':out}
                tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');tmp.replace(path)
            except Exception:pass
            self.after(400,dump)
        self.after(500,dump)
        return original(self,*a,**kw)
    tk.Tk.mainloop=mainloop
