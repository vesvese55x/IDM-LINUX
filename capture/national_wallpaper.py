"""National desktop artwork with authentic Ataturk photo and real runner facts.
No invented CPU/RAM values. Turkish/English text is rendered using real fonts.
"""
from pathlib import Path
import os,platform,math,textwrap,json
from PIL import Image,ImageDraw,ImageFont,ImageOps
ASSETS=Path(__file__).parent/'assets'
def facts():
 win=os.name=='nt';cpu=platform.processor();memory=None
 if win:
  import winreg,ctypes
  with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion') as k:
   system=winreg.QueryValueEx(k,'ProductName')[0];build=winreg.QueryValueEx(k,'CurrentBuild')[0]
  with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as k:cpu=winreg.QueryValueEx(k,'ProcessorNameString')[0].strip()
  class MEMORYSTATUSEX(ctypes.Structure):
   _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(n,ctypes.c_ulonglong) for n in ['total_phys','avail_phys','total_page','avail_page','total_virtual','avail_virtual','avail_extended']]
  m=MEMORYSTATUSEX();m.length=ctypes.sizeof(m)
  if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):memory=round(m.total_phys/1024**3,1)
 else:
  release=platform.freedesktop_os_release();system=release.get('PRETTY_NAME',platform.system());build=platform.release()
  for line in Path('/proc/cpuinfo').read_text().splitlines():
   if line.startswith('model name'):cpu=line.split(':',1)[1].strip();break
  for line in Path('/proc/meminfo').read_text().splitlines():
   if line.startswith('MemTotal:'):memory=round(int(line.split()[1])/1024**2,1);break
 return {'os_family':'Windows' if win else 'Linux','os_name':system,'build_or_kernel':build,'architecture':platform.machine(),'cpu':cpu,'logical_cpus':os.cpu_count(),'ram_gib':memory,'capture_resolution':'1920 × 1080','capture_fps':24,'actual_runtime_information':True}
def font(size,bold=False):
 if os.name=='nt':p=Path(os.environ['WINDIR'])/'Fonts'/('segoeuib.ttf' if bold else 'segoeui.ttf')
 else:p=Path('/usr/share/fonts/truetype/dejavu')/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')
 return ImageFont.truetype(str(p),size)
def flag(draw,box):
 x,y,w,h=box;red=(190,27,49);white=(248,248,246)
 draw.rectangle((x,y,x+w,y+h),fill=red)
 cx=x+w*.34;cy=y+h*.5;r=h*.255
 draw.ellipse((cx-r,cy-r,cx+r,cy+r),fill=white)
 r2=h*.205;cx2=cx+h*.062
 draw.ellipse((cx2-r2,cy-r2,cx2+r2,cy+r2),fill=red)
 sx=x+w*.60;sr=h*.13;points=[]
 for n in range(10):
  a=n*math.pi/5;r3=sr if n%2==0 else sr*.382
  points.append((sx+math.cos(a)*r3,cy+math.sin(a)*r3))
 draw.polygon(points,fill=white)
def build(out,language='tr'):
 out=Path(out);out.mkdir(exist_ok=True,parents=True);info=facts();en=language.lower().startswith('en')
 im=Image.open(ASSETS/'studio-wallpaper.png').convert('RGB').resize((1920,1080));d=ImageDraw.Draw(im)
 # National flag and original historical portrait are separate, undistorted elements.
 d.rounded_rectangle((757,62,1338,460),radius=18,fill=(30,64,85),outline=(112,147,164),width=2)
 flag(d,(771,77,552,368))
 d.rounded_rectangle((1380,62,1858,826),radius=22,fill=(17,42,62),outline=(134,157,171),width=2)
 portrait=ImageOps.fit(Image.open(ASSETS/'ataturk-1932.jpg').convert('RGB'),(442,596),method=Image.Resampling.LANCZOS)
 im.paste(portrait,(1398,80));d=ImageDraw.Draw(im)
 d.text((1400,700),'Mustafa Kemal',font=font(27),fill=(237,243,248));d.text((1400,739),'Atatürk',font=font(40,True),fill=(248,248,245))
 # Symbolic public silhouettes, not a claim to depict a particular real gathering.
 import random
 rng=random.Random(1923)
 for row in range(2):
  for n in range(43):
   x=n*47+rng.randint(-12,12);y=970+row*57+rng.randint(-12,16);r=rng.randint(10,16);color=(35,72,94) if row==0 else (22,53,75)
   d.ellipse((x-r,y-r*3,x+r,y-r),fill=color);d.rounded_rectangle((x-r*1.25,y-r,x+r*1.25,1080),radius=12,fill=color)
 for x,y in [(155,890),(433,920),(780,870),(1135,919),(1700,884)]:
  d.line((x,y,x,y+150),fill=(180,197,206),width=3);flag(d,(x,y,78,52))
 d.rounded_rectangle((52,62,709,514),radius=22,fill=(21,49,70),outline=(133,168,188),width=2)
 d.text((82,88),'BELGESELSEMO  /  '+('SYSTEM' if en else 'SİSTEM'),font=font(20,True),fill=(138,207,229))
 d.text((80,126),info['os_family'],font=font(51,True),fill=(247,250,251))
 d.text((83,197),info['os_name'][:49],font=font(21,True),fill=(227,239,246))
 lines=[(('Build / kernel: ' if en else 'Derleme / çekirdek: ')+info['build_or_kernel']),('CPU: '+info['cpu']),((str(info['logical_cpus'])+' logical CPUs' if en else str(info['logical_cpus'])+' mantıksal işlemci')+'  ·  '+info['architecture']),('RAM: '+str(info['ram_gib'])+' GiB'),(('Recording: ' if en else 'Kayıt: ')+info['capture_resolution']+'  /  24 fps')]
 y=241
 for line in lines:
  for wrapped in textwrap.wrap(line,width=53):d.text((83,y),wrapped,font=font(18),fill=(209,227,239));y+=27
 d.line((83,448,676,448),fill=(89,130,153),width=1)
 d.text((83,468),'belgeselsemo.com.tr',font=font(25,True),fill=(241,246,248))
 d.text((64,718),'REPUBLIC  •  SCIENCE  •  TECHNOLOGY' if en else 'CUMHURİYET  •  BİLİM  •  TEKNOLOJİ',font=font(26,True),fill=(222,237,246))
 d.text((64,765),'IDM LINUX  ×  IDM SEMO',font=font(36,True),fill=(243,248,249))
 info.update({'language':'en' if en else 'tr','website':'https://belgeselsemo.com.tr','portrait':'Authentic 1932 historical photograph; source attribution in capture/assets/ataturk-source.json','crowd':'Symbolic illustration; not a documentary crowd photograph'})
 target=out/'national-system-wallpaper.png';im.save(target,optimize=True)
 (out/'wallpaper-system-info.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
 return target,info
