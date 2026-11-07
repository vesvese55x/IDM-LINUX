#!/usr/bin/env python3
"""SOL-ÜST SİSTEM BİLGİSİ KARTI — ana filmdeki (Bölüm 27, 15:48) kartın BİREBİR düzeni.

Ana filmdeki kart:
    ▎ Linux                      <- sol tarafta pembe→mor dikey şerit, büyük kalın başlık
      Ubuntu 24.04 LTS           <- dağıtım + sürüm (gri)
      Çekirdek: 7.0.0-1017-azure
      İşlemci: INTEL(R) XEON(R) PLATINUM ... · 4 mantıksal işlemci · 15.6 GiB RAM
      belgeselsemo.com.tr        <- marka (beyaz kalın)

TÜM değerler makineden okunur; hiçbir değer uydurulmaz.

Kullanımlar:
    python3 system_card_v3.py --info                    # değerleri yazdır
    python3 system_card_v3.py --out card.png            # saydam PNG üret
    python3 system_card_v3.py --bake                    # mevcut duvar kağıdına göm (film görünümü)
    python3 system_card_v3.py --bake --restore          # duvar kağıdını yedekten geri al
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

BRAND = "belgeselsemo.com.tr"
ACCENT_TOP = (226, 56, 122)      # pembe
ACCENT_BOTTOM = (123, 92, 255)   # mor


def sh(cmd: str, default: str = "") -> str:
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10).stdout.strip() or default
    except Exception:
        return default


def collect() -> dict:
    osrel = {}
    p = Path("/etc/os-release")
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                osrel[k] = v.strip('"')
    info = {}
    pretty = osrel.get("PRETTY_NAME") or platform.platform()
    info["distro"] = re.sub(r"\s*\(.*\)\s*$", "", pretty).strip()
    info["version"] = osrel.get("VERSION_ID", "")
    info["kernel"] = sh("uname -r")
    info["arch"] = sh("uname -m")
    cpu = ""
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text().splitlines():
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    cpu = re.sub(r"\s+", " ", cpu)
    cpu = re.sub(r"\s+CPU\s+@.*$", "", cpu)          # "… CPU @ 2.60GHz" -> temiz
    cpu = re.sub(r"\s+@\s+.*$", "", cpu)
    info["cpu"] = cpu
    info["cores"] = sh("nproc")
    mem = {}
    mp = Path("/proc/meminfo")
    if mp.exists():
        for line in mp.read_text().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                mem[k] = int(v.strip().split()[0] or 0)
    total_kb = mem.get("MemTotal", 0)
    info["ram_gib"] = f"{total_kb / 1024 / 1024:.1f} GiB" if total_kb else ""
    info["host"] = sh("hostname")
    info["datetime"] = sh('date "+%d.%m.%Y %H:%M"')
    return info


def render(info: dict, out: Path, scale: float = 1.0) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    def font(size: int, bold: bool = False):
        base = "/usr/share/fonts/truetype/dejavu/DejaVuSans"
        for cand in (base + ("-Bold" if bold else "") + ".ttf", base + ".ttf"):
            if Path(cand).exists():
                return ImageFont.truetype(cand, int(size * scale))
        return ImageFont.load_default()

    f_title = font(42, True)
    f_body = font(21)
    f_brand = font(22, True)

    line4 = " · ".join(x for x in [
        f"{info['cores']} mantıksal işlemci" if info.get("cores") else "",
        f"{info['ram_gib']} RAM" if info.get("ram_gib") else "",
        info.get("arch", ""),
    ] if x)
    rows = [
        (f_title, "Linux", (255, 255, 255, 255), 14),
        (f_body, info.get("distro", ""), (176, 190, 206, 255), 8),
        (f_body, f"Çekirdek: {info.get('kernel', '')}", (176, 190, 206, 255), 6),
        (f_body, f"İşlemci: {info.get('cpu', '')}", (176, 190, 206, 255), 6),
        (f_body, f"         {line4}", (176, 190, 206, 255), 12),
        (f_brand, BRAND, (255, 255, 255, 255), 0),
    ]

    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    bar_w = int(7 * scale)
    pad_l = int(30 * scale)
    pad_r = int(30 * scale)
    pad_t = int(18 * scale)
    pad_b = int(20 * scale)
    text_w = max(int(probe.textlength(t, font=f)) for f, t, _, _ in rows)
    W = text_w + pad_l + pad_r
    heights = [int(f.size * 1.25) for f, _, _, _ in rows]
    H = pad_t + sum(h + int(g * scale) for h, (_, _, _, g) in zip(heights, rows)) + pad_b

    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # kart zemini: ana filmdeki gibi çok hafif koyu levha
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=int(14 * scale), fill=(6, 10, 18, 150))
    # sol dikey şerit: pembe -> mor degrade
    bar = Image.new("RGBA", (bar_w, H - int(28 * scale)), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    bh = bar.size[1]
    for y in range(bh):
        t = y / max(1, bh - 1)
        col = tuple(int(ACCENT_TOP[i] + (ACCENT_BOTTOM[i] - ACCENT_TOP[i]) * t) for i in range(3)) + (255,)
        bd.line((0, y, bar_w - 1, y), fill=col)
    img.alpha_composite(bar, (int(10 * scale), int(14 * scale)))

    y = pad_t
    for (f, text, color, gap), h in zip(rows, heights):
        if text.strip():
            d.text((pad_l, y), text, font=f, fill=color)
        y += h + int(gap * scale)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def _wallpaper_candidates():
    cands = []
    for key in ("last-image", "image-path"):
        p = sh(f"xfconf-query -c xfce4-desktop -l 2>/dev/null | grep -m1 '{key}'")
        if p:
            v = sh(f"xfconf-query -c xfce4-desktop -p '{p}' 2>/dev/null")
            if v and Path(v).is_file():
                cands.append((p, Path(v)))
    g = sh("gsettings get org.gnome.desktop.background picture-uri 2>/dev/null").strip("'")
    if g.startswith("file://") and Path(g[7:]).is_file():
        cands.append((None, Path(g[7:])))
    for p in Path.home().glob(".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml"):
        for m in re.finditer(r'name="(last-image|image-path)" type="string" value="([^"]+)"', p.read_text(errors="replace")):
            if Path(m.group(2)).is_file():
                cands.append((None, Path(m.group(2))))
    return cands


def bake(card: Path, restore: bool = False, x: int = 30, y: int = 26) -> int:
    """Kartı duvar kağıdına gömer — kayıtta masaüstünün gerçek parçası olur (ana filmdeki gibi)."""
    from PIL import Image
    home = Path.home()
    state = home / ".cache/idm-linux-film/card-wallpaper.state"
    state.parent.mkdir(parents=True, exist_ok=True)
    target = home / ".cache/idm-linux-film/film-desktop.png"

    if restore:
        if not state.exists():
            print("yedek durumu yok")
            return 1
        _, orig, prop = state.read_text().splitlines()[:3]
        if prop and prop != "-" and Path(orig).is_file():
            subprocess.run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", orig], check=False)
        elif Path(orig).is_file():
            subprocess.run(["feh", "--bg-fill", orig], check=False)
        state.unlink(missing_ok=True)
        print("duvar kağıdı geri alındı:", orig)
        return 0

    cands = _wallpaper_candidates()
    prop = "-"
    base_src = None
    if cands:
        prop, base_src = cands[0]
        prop = prop or "-"
    if base_src and base_src.is_file():
        base = Image.open(base_src).convert("RGB")
    else:  # duvar kağıdı bulunamazsa mevcut ekranı taban al (gerçek görüntü)
        tmp = Path("/tmp/_wall_base.png")
        subprocess.run(f"DISPLAY=${{DISPLAY:-:1}} import -window root {tmp}", shell=True, check=False)
        base = Image.open(tmp).convert("RGB") if tmp.exists() else Image.new("RGB", (1920, 1080), (9, 19, 32))
    W, H = base.size
    # ekran oranına sığdır
    rw, rh = sh("xrandr 2>/dev/null | awk '/\\*/{print $1; exit}'").split("x") if "x" in sh("xrandr 2>/dev/null | awk '/\\*/{print $1; exit}'") else (str(W), str(H))
    try:
        W, H = int(rw), int(rh)
    except ValueError:
        pass
    frame = base.resize((W, H), Image.Resampling.LANCZOS)
    c = Image.open(card).convert("RGBA")
    frame = frame.convert("RGBA")
    frame.alpha_composite(c, (x, y))
    frame.convert("RGB").save(target)

    state.write_text(f"{state}\n{base_src or '-'}\n{prop}\n", encoding="utf-8")
    if prop != "-":
        subprocess.run(["xfconf-query", "-c", "xfce4-desktop", "-p", prop, "-s", str(target)], check=False)
    if shutil.which("feh"):
        subprocess.run(["feh", "--bg-fill", str(target)], check=False)
    print("kart duvar kağıdına gömüldü:", target, f"({W}x{H})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path.home() / ".cache/idm-linux-film/system-card.png"))
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--info", action="store_true")
    ap.add_argument("--bake", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--x", type=int, default=30)
    ap.add_argument("--y", type=int, default=26)
    a = ap.parse_args()
    info = collect()
    if a.info:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0
    out = render(info, Path(a.out), a.scale)
    print(out)
    if a.bake or a.restore:
        return bake(out, restore=a.restore, x=a.x, y=a.y)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
