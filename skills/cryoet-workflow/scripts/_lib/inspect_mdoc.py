#!/usr/bin/env python3
"""Read a dataset's MDOCs (+ one image header) and propose the acquisition values for init_project.sh, flagging the
traps we have hit. Values are proposals - confirm each with the user / acquisition notes before using them.

  python3 inspect_mdoc.py --mdocs /path/to/mdocs [--frames /path/to/frames] [--pattern '*.mdoc'] [--json]

SHARED: canonical copy in lib/, vendored to every skill's scripts/_lib/. --json prints proposals + warnings as JSON
on stdout (the human report goes to stderr) - the cryoet-workflow intake uses it to pre-fill dataset answers.

Reports: series count, tilts per series, tilt range and step, pixel size, voltage, dose per tilt (ExposureDose) and per
frame (FrameDosesAndNumber / NumSubFrames), tilt axis, image size, target defocus, SubFramePath extensions, DateTime
presence, and checks:
  * MDOC ImageSize vs the real image header (X/Y swapped -> the MDOC tilt axis is probably quoted in a swapped frame,
    i.e. 90 deg off; the symptom downstream is an IMOD residual many times the usual ~1 nm). Confirm with IMOD's own
    fit ("rotation angle seems to be closer to ...") on one series before the batch.
  * SubFramePath extension vs the files on disk (e.g. .eer in the MDOC, .mrc on disk -> every tilt "not found", the
    worker blacklisted, alignment spinning forever). Rewrite COPIES of the MDOCs.
  * Missing DateTime (ts_import orders dose by DateTime x --tilt_exposure).
  * Files on disk with no MDOC entry (e.g. a counting-reference exposure: ignored by ts_import, harmless).
"""
import argparse, glob, os, re, statistics, struct, sys

TIFF_EXT = (".tif", ".tiff", ".eer")          # EER is TIFF-based
from collections import Counter


def parse(path):
    hdr, sec, cur = {}, [], None
    for line in open(path, errors="replace"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"\[ZValue\s*=\s*(\d+)\]", line)
        if m:
            cur = {}; sec.append(cur); continue
        m = re.match(r"\[T\s*=\s*(.*)\]", line)
        if m and cur is None:
            hdr.setdefault("_T", []).append(m.group(1)); continue
        if "=" in line:
            k, v = [x.strip() for x in line.split("=", 1)]
            (cur if cur is not None else hdr)[k] = v
    return hdr, sec


def image_dims(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".mrc", ".mrcs", ".st"):
            with open(path, "rb") as f:
                nx, ny, nz = struct.unpack("<3i", f.read(12)); return nx, ny
        if ext in TIFF_EXT:
            with open(path, "rb") as f:
                b = f.read(16); e = "<" if b[:2] == b"II" else ">"
                magic = struct.unpack(e + "H", b[2:4])[0]
                w = h = None
                if magic == 42:                       # classic TIFF
                    off = struct.unpack(e + "I", b[4:8])[0]
                    f.seek(off); n = struct.unpack(e + "H", f.read(2))[0]
                    for _ in range(n):
                        tag, typ, cnt, val = struct.unpack(e + "HHI4s", f.read(12))
                        v = struct.unpack(e + ("H" if typ == 3 else "I"), val[:2] if typ == 3 else val)[0]
                        if tag == 256: w = v
                        if tag == 257: h = v
                elif magic == 43:                     # BigTIFF
                    off = struct.unpack(e + "Q", b[8:16])[0]
                    f.seek(off); n = struct.unpack(e + "Q", f.read(8))[0]
                    for _ in range(n):
                        tag, typ, cnt, val = struct.unpack(e + "HHQ8s", f.read(20))
                        fmt = {3: "H", 4: "I", 16: "Q"}.get(typ, "I")
                        v = struct.unpack(e + fmt, val[:struct.calcsize(fmt)])[0]
                        if tag == 256: w = v
                        if tag == 257: h = v
                return (w, h) if w and h else None
    except Exception:
        return None
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mdocs", required=True); ap.add_argument("--frames"); ap.add_argument("--pattern", default="*.mdoc")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    import json
    out = {}
    say = (lambda *x, **k: print(*x, file=sys.stderr, **k)) if a.json else print
    files = sorted(glob.glob(os.path.join(a.mdocs, a.pattern)))
    if not files:
        sys.exit("no MDOCs found")
    ntilt, angles, px, kv, dose_t, dose_f, nsub, axis, size, tdef, exts, nodate = [], [], Counter(), Counter(), [], [], Counter(), Counter(), Counter(), [], Counter(), 0
    names = set()
    for p in files:
        h, sec = parse(p); ntilt.append(len(sec))
        for t in h.get("_T", []):
            m = re.search(r"Tilt axis angle\s*=\s*([-\d.]+)", t)
            if m: axis[float(m.group(1))] += 1
        for s in sec:
            if "TiltAngle" in s: angles.append(float(s["TiltAngle"]))
            if "PixelSpacing" in s: px[s["PixelSpacing"]] += 1
            if "Voltage" in s: kv[s["Voltage"]] += 1
            if "ExposureDose" in s: dose_t.append(float(s["ExposureDose"]))
            if "NumSubFrames" in s: nsub[s["NumSubFrames"]] += 1
            if "FrameDosesAndNumber" in s:
                d, n = s["FrameDosesAndNumber"].split()[:2]; dose_f.append(float(d))
            if "TargetDefocus" in s: tdef.append(float(s["TargetDefocus"]))
            if "SubFramePath" in s:
                b = re.split(r"[\\/]", s["SubFramePath"])[-1]; names.add(os.path.splitext(b)[0]); exts[os.path.splitext(b)[1]] += 1
            if "DateTime" not in s: nodate += 1
        if "ImageSize" in h: size[h["ImageSize"]] += 1
    out.update(n_series=len(files), tilts_per_series_median=statistics.median(ntilt))
    if px: out["angpix"] = float(px.most_common(1)[0][0])
    if kv: out["kv"] = float(kv.most_common(1)[0][0])
    if angles: out["tilt_min"], out["tilt_max"] = min(angles), max(angles)
    if dose_t: out["dose_per_tilt"] = statistics.median(dose_t)
    if dose_f: out["dose_per_frame"] = statistics.median(dose_f)
    elif dose_t and nsub: out["dose_per_frame"] = statistics.median(dose_t) / int(nsub.most_common(1)[0][0])
    if nsub: out["nframes"] = int(nsub.most_common(1)[0][0])
    if tdef: out["defocus_um_min"], out["defocus_um_max"] = min(abs(x) for x in tdef), max(abs(x) for x in tdef)
    if axis: out["tilt_axis_mdoc"] = axis.most_common(1)[0][0]
    if exts: out["frame_ext_mdoc"] = exts.most_common(1)[0][0]
    say(f"MDOCs: {len(files)}   tilts per series: min {min(ntilt)} median {statistics.median(ntilt):.0f} max {max(ntilt)}")
    if angles:
        st = sorted(set(round(x, 1) for x in angles)); steps = Counter(round(b - a_, 1) for a_, b in zip(st, st[1:]))
        say(f"tilt range {min(angles):.1f} .. {max(angles):.1f}, commonest step {steps.most_common(1)[0][0] if steps else '?'}")
    say(f"PixelSpacing {dict(px)}   Voltage {dict(kv) or 'not in MDOC - ask the user / facility'}   NumSubFrames {dict(nsub)}")
    if dose_t: say(f"ExposureDose (per tilt) median {statistics.median(dose_t):.5g}  -> DOSE_PER_TILT")
    if dose_f: say(f"FrameDosesAndNumber dose/frame median {statistics.median(dose_f):.5g}  -> DOSE_PER_FRAME (positive; negated for --exposure)")
    elif dose_t and nsub:
        n = int(nsub.most_common(1)[0][0]); say(f"no FrameDosesAndNumber: dose/frame ~ {statistics.median(dose_t) / n:.5g} (ExposureDose / {n})")
    if nsub:
        nf = nsub.most_common(1)[0][0]
        say(f"NumSubFrames {nf} -> NFRAMES={nf} (for EER use the --eer_ngroups value instead)")
    else:
        say("no NumSubFrames in the MDOC -> read NFRAMES from one movie header (frames = nz / pages)")
    if tdef:
        ad = [abs(x) for x in tdef]
        say(f"TargetDefocus {min(tdef):.2f} .. {max(tdef):.2f} um  -> bracket {min(ad):.2f}..{max(ad):.2f} with DEFOCUS_MIN/MAX (positive um = underfocus)")
    say(f"tilt axis (header) {dict(axis)}   ImageSize {dict(size)}   SubFramePath extensions {dict(exts)}")
    warn = []
    if nodate: warn.append(f"{nodate} tilt sections lack DateTime - ts_import orders dose by DateTime")
    if a.frames:
        disk = [f for f in os.listdir(a.frames) if not f.startswith(".")]
        dext = Counter(os.path.splitext(f)[1] for f in disk)
        say(f"frames on disk: {len(disk)} files {dict(dext)}")
        if exts and not (set(exts) & set(dext)):
            warn.append(f"MDOC SubFramePath extension {set(exts)} != files on disk {set(dext)}: rewrite COPIES of the MDOCs "
                        "or every tilt is 'not found'")
        extra = {os.path.splitext(f)[0] for f in disk} - names
        if extra: warn.append(f"{len(extra)} files on disk with no MDOC entry (e.g. {sorted(extra)[0]}) - ignored by ts_import")
        sample = next((os.path.join(a.frames, f) for f in sorted(disk) if os.path.splitext(f)[1].lower() in TIFF_EXT + (".mrc", ".mrcs")), None)
        dims = image_dims(sample) if sample else None
        if dims:
            out["image_dims"] = [dims[0], dims[1]]
            say(f"image header {os.path.basename(sample)}: {dims[0]} x {dims[1]}  -> TOMO_DIM {dims[0]}x{dims[1]}x<Z>")
            for s in size:
                w, h_ = [int(x) for x in s.split()[:2]]
                close = lambda x, y: abs(x - y) <= 0.01 * max(x, y)
                if w != h_ and close(w, dims[1]) and close(h_, dims[0]) and not (close(w, dims[0]) and close(h_, dims[1])):
                    warn.append(f"MDOC ImageSize {s} is the image header TRANSPOSED: the MDOC tilt axis is likely quoted in a "
                                "swapped frame (90 deg off). Expect OVERRIDE_AXIS=1 with axis - 90; confirm from IMOD's "
                                "'rotation angle seems to be closer to' warning on a test series")
    for w in warn:
        say("WARN", w)
    out["warnings"] = warn
    if a.json:
        print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
