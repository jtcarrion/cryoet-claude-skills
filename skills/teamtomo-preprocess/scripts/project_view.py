#!/usr/bin/env python3
"""Build a "Warp project view" that teamtomo-workflows can read, without touching the real project:
  (a) a VARIANT processing folder (an alignment arm made with warptools-preprocess --variant NAME, i.e. <PROJ>/NAME)
      presented under the fixed names teamtomo expects, and/or
  (b) XMLs from older (pre-2.0) Warp builds that lack ImageDimensionsAngstrom / VolumeDimensionsAngstrom (teamtomo
      crashes in discovery with "TypeError: 'NoneType' object is not iterable").

  python project_view.py --base-project <Warp project root> --out <project>/teamtomo/views/<name>
                         [--processing <variant processing folder>] [--settings <.settings>] [--frameseries D] [--tomostar D]

teamtomo expects inside warp_project: warp_tiltseries/ (XMLs + tiltstack/), warp_frameseries/ (average/), tomostar/,
warp_tiltseries.settings. The view is symlinks, except when XMLs need patching: then warp_tiltseries/ is a real folder
of PATCHED XML COPIES (+ a tiltstack symlink). The patch only ADDS the two root attributes, with the values the newer
Warp build writes itself (checked against XMLs rewritten by a current MCore):
  ImageDimensionsAngstrom  = full-size average width, height (px) x settings PixelSize   (e.g. 5760 x 1.368 = 7879.68)
  VolumeDimensionsAngstrom = settings DimensionsX, Y, Z x PixelSize                      (tomogram canvas)
Everything else is byte-identical. The source folder is never written to. Write views under <project>/teamtomo/views/.
Needs mrcfile only when XMLs must be patched (run it with the teamtomo env's python).
"""
import argparse, os, re, sys
from pathlib import Path


def settings_vals(p):
    s = Path(p).read_text()
    g = lambda n: float(re.search(rf'Name="{n}" Value="([^"]+)"', s).group(1))
    px = g("PixelSize")
    return px, (g("DimensionsX") * px, g("DimensionsY") * px, g("DimensionsZ") * px)


def first_movie(tomostar):
    for line in Path(tomostar).read_text().splitlines():
        m = re.search(r"(\S+\.(?:tif|tiff|eer|mrc))\b", line)
        if m and not line.lstrip().startswith("_"):
            return Path(m.group(1)).stem
    return None


def fmt(v):
    return f"{float(v):.4f}".rstrip("0").rstrip(".")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-project", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--processing"); ap.add_argument("--settings"); ap.add_argument("--frameseries"); ap.add_argument("--tomostar")
    a = ap.parse_args()
    base = Path(a.base_project).resolve(); out = Path(a.out).resolve()
    proc = Path(a.processing).resolve() if a.processing else base / "warp_tiltseries"
    fs = Path(a.frameseries).resolve() if a.frameseries else base / "warp_frameseries"
    ts = Path(a.tomostar).resolve() if a.tomostar else base / "tomostar"
    st = Path(a.settings).resolve() if a.settings else base / "warp_tiltseries.settings"
    for k, v in (("processing", proc), ("frameseries", fs), ("tomostar", ts), ("settings", st)):
        if not v.exists():
            sys.exit(f"missing {k}: {v}")
    xmls = sorted(proc.glob("*.xml"))
    if not xmls:
        sys.exit(f"no tilt-series XMLs in {proc}")
    if out.exists() and any(out.iterdir()):
        sys.exit(f"REFUSING: {out} exists and is not empty")
    need = [x for x in xmls if "ImageDimensionsAngstrom=" not in x.read_text()[:4000]]
    out.mkdir(parents=True, exist_ok=True)
    for k, v in (("warp_frameseries", fs), ("tomostar", ts), ("warp_tiltseries.settings", st)):
        os.symlink(v, out / k); print(f"  {k:<26} -> {v}")
    if not need:
        os.symlink(proc, out / "warp_tiltseries"); print(f"  {'warp_tiltseries':<26} -> {proc}  ({len(xmls)} XMLs, no patch needed)")
        return
    import mrcfile
    px, vol = settings_vals(st)
    tv = out / "warp_tiltseries"; tv.mkdir()
    for extra in ("tiltstack", "processed_items.json"):
        if (proc / extra).exists():
            os.symlink(proc / extra, tv / extra)
    n_p = n_c = 0; bad = []
    for x in xmls:
        text = x.read_text()
        if x not in need:
            (tv / x.name).write_text(text); n_c += 1; continue
        mv = first_movie(ts / f"{x.stem}.tomostar") if (ts / f"{x.stem}.tomostar").exists() else None
        avg = fs / "average" / f"{mv}.mrc" if mv else None
        if avg is None or not avg.exists():
            bad.append(x.stem); continue
        with mrcfile.mmap(avg, permissive=True) as m:
            h, w = m.data.shape[-2:]
        attrs = f' ImageDimensionsAngstrom="{fmt(w * px)}, {fmt(h * px)}"'
        if "VolumeDimensionsAngstrom=" not in text[:4000]:
            attrs += f' VolumeDimensionsAngstrom="{fmt(vol[0])}, {fmt(vol[1])}, {fmt(vol[2])}"'
        i = text.index("<TiltSeries"); j = text.index(">", i)
        (tv / x.name).write_text(text[:j] + attrs + text[j:]); n_p += 1
    if bad:
        print(f"  WARNING: {len(bad)} series without a full-size average to size from - NOT in the view: {bad[:10]}")
    print(f"  {'warp_tiltseries':<26} -> {tv} (real folder: {n_p} patched + {n_c} copied XMLs; tiltstack symlinked)")
    print(f"  patch: ImageDimensionsAngstrom from average size x {px} A; VolumeDimensionsAngstrom {', '.join(fmt(v) for v in vol)}")


if __name__ == "__main__":
    main()
