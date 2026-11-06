import ctypes,ctypes.util,os,json,time,threading
from pathlib import Path
DISPLAY=os.environ.get('DISPLAY',':99')
class PointerTracker:
    def __init__(self, out, epoch):
        self.out = Path(out); self.epoch = epoch; self.rows = []; self.running = False
        self.x11 = ctypes.CDLL(ctypes.util.find_library('X11'))
        self.x11.XOpenDisplay.argtypes=[ctypes.c_char_p]; self.x11.XOpenDisplay.restype=ctypes.c_void_p
        self.x11.XDefaultRootWindow.argtypes=[ctypes.c_void_p]; self.x11.XDefaultRootWindow.restype=ctypes.c_ulong
        self.x11.XQueryPointer.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_int),ctypes.POINTER(ctypes.c_uint)]
        self.x11.XCloseDisplay.argtypes=[ctypes.c_void_p]
    def start(self):
        self.running=True; self.thread=threading.Thread(target=self.run,daemon=True); self.thread.start(); return self
    def run(self):
        d=self.x11.XOpenDisplay(DISPLAY.encode()); root=self.x11.XDefaultRootWindow(d)
        last=None
        while self.running:
            rr=ctypes.c_ulong(); cr=ctypes.c_ulong(); x=ctypes.c_int(); y=ctypes.c_int(); wx=ctypes.c_int(); wy=ctypes.c_int(); mask=ctypes.c_uint()
            self.x11.XQueryPointer(d,root,ctypes.byref(rr),ctypes.byref(cr),ctypes.byref(x),ctypes.byref(y),ctypes.byref(wx),ctypes.byref(wy),ctypes.byref(mask))
            row=[round(time.time()-self.epoch,4),x.value,y.value,int(mask.value)]
            if row[1:]!=last: self.rows.append(row); last=row[1:]
            time.sleep(.025)
        self.x11.XCloseDisplay(d)
    def finish(self):
        self.running=False; self.thread.join(timeout=2)
        self.out.parent.mkdir(parents=True,exist_ok=True)
        self.out.write_text(json.dumps({'display':DISPLAY,'width':1920,'height':1080,'source':'XQueryPointer','sample_interval_ms':25,'rows':self.rows},ensure_ascii=False))
        return {'samples':len(self.rows),'output':str(self.out)}

