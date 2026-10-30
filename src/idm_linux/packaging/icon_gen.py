#!/usr/bin/env python3
"""IDM LINUX marka ikonu üretici (256x256 PNG).

Repoda gerçek ikon varsa build script'leri onu kullanır; bu üretici yalnızca
yedek/varsayılan olarak çalışır.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

W = H = 256


def _font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def main() -> None:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Arka plan: koyu lacivert, yuvarlatılmış köşeler, camgöbeği çerçeve
    d.rounded_rectangle(
        [8, 8, W - 8, H - 8],
        radius=48,
        fill=(24, 34, 64, 255),
        outline=(0, 174, 239, 255),
        width=6,
    )

    d.text((W / 2, H / 2 - 26), "IDM", font=_font(84), fill=(255, 255, 255, 255), anchor="mm")
    d.text((W / 2, H / 2 + 54), "LINUX", font=_font(40), fill=(0, 174, 239, 255), anchor="mm")

    out = sys.argv[1] if len(sys.argv) > 1 else "idm-linux.png"
    img.save(out)
    print(f"ikon üretildi: {out}")


if __name__ == "__main__":
    main()
