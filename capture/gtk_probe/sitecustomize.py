"""Read-only live GTK widget geometry of the real, unmodified GDebi process."""
import os
if os.getenv('FILM_GTK_WIDGET_DUMP'):
 import json,time
 from pathlib import Path
 import gi
 gi.require_version('Gtk','3.0')
 from gi.repository import Gtk,GLib
 path=Path(os.environ['FILM_GTK_WIDGET_DUMP'])
 def dump():
  try:
   rows=[]
   def walk(widget,top):
    if not widget.get_visible() or not widget.get_mapped():return
    try:
     origin=top.get_window().get_origin()[-2:];xy=widget.translate_coordinates(top,0,0)[-2:];text=''
     for method in ['get_label','get_text','get_title']:
      if hasattr(widget,method):
       value=getattr(widget,method)()
       if isinstance(value,str) and value:text=value;break
     rows.append({'class':type(widget).__name__,'text':text,'sensitive':widget.get_sensitive(),'title':top.get_title(),'rect':[origin[0]+xy[0],origin[1]+xy[1],widget.get_allocated_width(),widget.get_allocated_height()]})
    except Exception:pass
    if isinstance(widget,Gtk.Container):
     for child in widget.get_children():walk(child,top)
   for window in Gtk.Window.list_toplevels():walk(window,window)
   tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps({'time':time.time(),'widgets':rows},ensure_ascii=False));tmp.replace(path)
  except Exception:pass
  return True
 GLib.timeout_add(400,dump)
