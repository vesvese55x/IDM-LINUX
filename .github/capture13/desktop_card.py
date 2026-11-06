import tkinter as tk,platform,os
from pathlib import Path
r=tk.Tk();r.overrideredirect(True);r.geometry('350x168+20+820');r.configure(bg='#101c29');r.attributes('-topmost',True)
mem=next((l.split()[1] for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemTotal:')),'0')
text='LINUX\n'+platform.freedesktop_os_release().get('PRETTY_NAME','Linux')+'\nÇekirdek: '+platform.release()+'\nİşlemci: '+platform.machine()+f' / {os.cpu_count()} mantıksal çekirdek\nBellek: {int(mem)/1024/1024:.1f} GiB\nTarayıcı: Brave  |  IDM Linux'
tk.Label(r,text=text,justify='left',anchor='nw',font=('DejaVu Sans',11),fg='#f0f5fa',bg='#101c29',padx=12,pady=10).pack(fill='both',expand=True);r.mainloop()
