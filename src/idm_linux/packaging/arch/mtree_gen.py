#!/usr/bin/env python3
"""v3.14.2 — makepkg-uyumlu .MTREE üretici (ALPM/pacman paketi için).

Arka plan: pamac/pacman "geçersiz veya bozuk paket" hatasının bir kök nedeni
paket içinde .MTREE dosyasının hiç bulunmamasıydı. makepkg HER paketinde
.MTREE'yi (gzip'li mtree-format manifest) üretir; pamac doğrulaması bu
manifeste güvenir. Bu betik pkgdir (staging) ağacını tarayarak makepkg'nin
ürettiğiyle aynı formatta manifest yazar:

    #mtree
    /set type=file uid=0 gid=0 mode=0644
    ./.PKGINFO time=... size=... md5digest=... sha256digest=...
    ./usr type=dir time=... mode=0755
    ./usr/bin/idm-linux mode=0755 time=... size=... md5digest=... sha256digest=...

Kurallar (makepkg/bsdtar davranışı):
  • yollar "./" önekli
  • her giriş: time (ns hassasiyetli), size + md5digest + sha256digest (dosya),
    type=dir + mode=0755 (dizin), type=link + link=<hedef> (symlink)
  • uid/gid root (0); mod /set'ten gelir, farklıysa satırda belirtilir
  • .MTREE kendisi manifeste DAHİL EDİLMEZ; .PKGINFO DAHİL edilir
  • çıktı gzip ile (mtime=0) paketlenir — makepkg 'gzip -n' davranışı

Kullanım:  python3 mtree_gen.py <STAGE_DİZİNİ>   →  <STAGE>/.MTREE yazar
"""
from __future__ import annotations

import gzip
import hashlib
import os
import stat
import sys
from pathlib import Path


def _time_str(st: os.stat_result) -> str:
    """bsdtar mtree biçiminde ns hassasiyetli zaman: '1719792000.000000000'."""
    return f"{st.st_mtime_ns // 1_000_000_000}.{st.st_mtime_ns % 1_000_000_000:09d}"


def _digests(path: Path) -> tuple[str, str]:
    md5, sha = hashlib.md5(), hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def build_mtree(stage: Path) -> str:
    lines: list[str] = ["#mtree", "/set type=file uid=0 gid=0 mode=0644"]

    # .PKGINFO ilk giriş (makepkg de metadata'yı ilk tarlar)
    pkginfo = stage / ".PKGINFO"
    if pkginfo.is_file():
        st = pkginfo.lstat()
        md5, sha = _digests(pkginfo)
        lines.append(
            f"./.PKGINFO time={_time_str(st)} size={st.st_size} "
            f"md5digest={md5} sha256digest={sha}"
        )

    # ağaç yürüyüşü: parent dizinler önce, her düzeyde sıralı (deterministik)
    def _sorted_entries(p: Path) -> tuple[list[Path], list[Path]]:
        dirs, files = [], []
        for child in sorted(p.iterdir(), key=lambda c: c.name):
            if child.name in (".PKGINFO", ".MTREE"):
                continue
            (dirs if child.is_dir() and not child.is_symlink() else files).append(child)
        return dirs, files

    def _emit_dir(rel: str, st: os.stat_result) -> None:
        lines.append(f"./{rel} type=dir uid=0 gid=0 mode=0755 time={_time_str(st)}")

    def _emit_file(rel: str, path: Path) -> None:
        st = path.lstat()
        md5, sha = _digests(path)
        mode = "0755" if stat.S_IMODE(st.st_mode) & 0o111 else ""  # /set 0644; exec satırda
        extra = f"mode={mode} " if mode else ""
        lines.append(
            f"./{rel} {extra}time={_time_str(st)} size={st.st_size} "
            f"md5digest={md5} sha256digest={sha}"
        )

    def _emit_link(rel: str, path: Path) -> None:
        st = path.lstat()
        target = os.readlink(path)
        lines.append(
            f"./{rel} type=link uid=0 gid=0 mode=0777 "
            f"time={_time_str(st)} link={target}"
        )

    def _walk(dir_path: Path) -> None:
        sub_dirs, files = _sorted_entries(dir_path)
        for d in sub_dirs:
            rel = d.relative_to(stage).as_posix()
            _emit_dir(rel, d.lstat())
            _walk(d)
        for f in files:
            rel = f.relative_to(stage).as_posix()
            if f.is_symlink():
                _emit_link(rel, f)
            elif f.is_file():
                _emit_file(rel, f)

    _walk(stage)
    return "\n".join(lines) + "\n"


def main() -> int:
    if len(sys.argv) != 2:
        print("Kullanım: mtree_gen.py <STAGE_DİZİNİ>", file=sys.stderr)
        return 2
    stage = Path(sys.argv[1]).resolve()
    if not stage.is_dir():
        print(f"HATA: stage dizini yok: {stage}", file=sys.stderr)
        return 2
    content = build_mtree(stage)
    out = stage / ".MTREE"
    out.write_bytes(gzip.compress(content.encode("utf-8"), mtime=0))
    print(f".MTREE üretildi: {out} ({out.stat().st_size} bayt, {content.count(chr(10))} giriş)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
