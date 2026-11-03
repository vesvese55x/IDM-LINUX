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
def wrap_pixels(draw,text,typeface,width):
 lines=[];line=''
 for word in text.split():
  candidate=(line+' '+word).strip()
  if line and draw.textlength(candidate,font=typeface)>width:lines.append(line);line=word
  else:line=candidate
 if line:lines.append(line)
 return lines

def build(out,language='tr',system_info=None):
 out=Path(out);out.mkdir(exist_ok=True,parents=True)
 info=dict(system_info) if system_info is not None else facts()
 en=language.lower().startswith('en')
 source=ASSETS/'user-national-wallpaper.png'
 im=Image.open(source).convert('RGBA');w,h=im.size
 # Preserve the supplied composition, quote, portrait, colours and dimensions.
 # A single bottom-left information plate is the only image edit.
 scale=w/1920
 fs=lambda n:max(12,round(n*scale))
 fhead=font(fs(25),True);fbody=font(fs(19));fsite=font(fs(27),True)
 pad=round(20*scale);left=round(26*scale);bottom=round(58*scale)
 width=round(620*scale);line_height=round(27*scale)
 layer=Image.new('RGBA',im.size,(0,0,0,0));d=ImageDraw.Draw(layer)
 kernel_label=('Build' if info['os_family']=='Windows' else 'Kernel') if en else ('Derleme' if info['os_family']=='Windows' else 'Çekirdek')
 header=info['os_family']+'  /  '+('SYSTEM INFO' if en else 'SİSTEM BİLGİSİ')
 rows=[info['os_name'],kernel_label+': '+info['build_or_kernel'],('Processor: ' if en else 'İşlemci: ')+info['cpu'],(str(info['logical_cpus'])+' logical CPUs' if en else str(info['logical_cpus'])+' mantıksal işlemci')+'  ·  '+str(info['ram_gib'])+' GiB RAM  ·  '+info['architecture']]
 wrapped=[]
 for row in rows:wrapped.extend(wrap_pixels(d,row,fbody,width-pad*2))
 height=pad*2+fs(31)+len(wrapped)*line_height+fs(43)
 top=h-bottom-height
 d.rounded_rectangle((left,top,left+width,h-bottom),radius=round(16*scale),fill=(12,16,22,218),outline=(235,207,185,150),width=max(1,round(scale)))
 d.rounded_rectangle((left,top+pad,left+round(4*scale),h-bottom-pad),radius=2,fill=(221,40,55,255))
 x=left+pad;y=top+pad
 d.text((x,y),header,font=fhead,fill=(255,249,243,255));y+=fs(37)
 for row in wrapped:d.text((x,y),row,font=fbody,fill=(236,240,244,255));y+=line_height
 y+=fs(7)
 d.text((x,y),'belgeselsemo.com.tr',font=fsite,fill=(255,248,237,255))
 merged=Image.alpha_composite(im,layer).convert('RGB')
 target=out/'national-system-wallpaper.png';merged.save(target,optimize=True)
 import hashlib
 info.update({'language':'en' if en else 'tr','website':'https://belgeselsemo.com.tr','background_source':'User supplied bd8abdd7-f735-448d-aa53-e9cb4836729c.png','background_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_resolution':list(im.size),'edit':'Bottom-left system information plate only; original artwork and existing quote unchanged','overlay_rect':[left,top,left+width,h-bottom],'preview_from_recorded_runner_facts':system_info is not None})
 (out/'wallpaper-system-info.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
 return target,info
