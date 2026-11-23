#!/usr/bin/env python3
"""reset_ctf_cs.py -- put Warp/M tilt-series (or frame-series) XMLs back to a nominal spherical aberration.

CANONICAL COPY: lib/reset_ctf_cs.py; vendored to <skill>/scripts/_lib/ by tools/sync_lib.sh. Stdlib only, Python 3.6+.

Why: MCore writes refined CTF terms back into the XMLs of whatever processing folder its source points at. After a run
with --ctf_cs (Cs is also a proxy for pixel size) or --ctf_zernike3/5 the folder no longer carries the microscope's
nominal Cs or zero odd aberrations, and a NEW population seeded from it silently inherits those fitted values. Seed every
new population from a reset copy.

  reset_ctf_cs.py XML_OR_DIR [...] --out_dir DIR [--cs_mm 2.7] [--zero_zernike_odd] [--dry_run]
  reset_ctf_cs.py DIR --in_place --zero_zernike_odd          # only on a private copy you own

What it edits, and nothing else (the file is patched as text, so formatting, attribute order and the BOM are kept):
  * <CTF> <Param Name="Cs" Value=..>                  -> --cs_mm (or MICROSCOPE_CS_MM from the cryoet-skills config)
  * <CTF> <Param Name="ZernikeCoeffsOdd" Value=a;b;..> -> 0;0;.. (same count) with --zero_zernike_odd
The <OptionsCTF> block (the settings ts_ctf used) is reported but left alone; ZernikeCoeffsEven, defocus, grids,
magnification and warp fields are untouched. Prints one before/after line per file. Exit 0 = all files processed,
1 = a file failed to parse or had no <CTF> block, 2 = bad arguments.
A directory argument means its *.xml files (not recursive). Other files in a folder (processed_items.json, .settings,
.tomostar) are NOT copied to --out_dir: copy the folder first and use --in_place on the copy if you need them.
"""
import argparse
import glob
import os
import re
import sys
import xml.etree.ElementTree as ET

CTF_BLOCK = re.compile(r"<CTF(?:\s[^>]*)?>(.*?)</CTF>", re.S)
OPT_BLOCK = re.compile(r"<OptionsCTF(?:\s[^>]*)?>(.*?)</OptionsCTF>", re.S)


def param_rx(name):
    return re.compile(r'<Param\b[^>]*\bName="%s"[^>]*/>' % re.escape(name))


VALUE_RX = re.compile(r'(\bValue=")([^"]*)(")')


def get_param(block, name):
    m = param_rx(name).search(block)
    if not m:
        return None
    v = VALUE_RX.search(m.group(0))
    return v.group(2) if v else None


def set_param(block, name, value):
    rx = param_rx(name)
    m = rx.search(block)
    if not m:
        return block, False
    new_tag = VALUE_RX.sub(lambda v: v.group(1) + value + v.group(3), m.group(0), count=1)
    return block[:m.start()] + new_tag + block[m.end():], True


def split_coeffs(v):
    return [x for x in re.split(r"[;,\s]+", v or "") if x]


def fmt_cs(x):
    return repr(float(x))


def resolve_cs(cli):
    if cli is not None:
        return cli, "--cs_mm"
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    try:
        import cryoet_config as cc
        cfg = cc.load()
        v = cc.cs_mm(cfg)
        if v is not None:
            return v, "MICROSCOPE_CS_MM (%s)" % cc.config_path()
    except (ImportError, SystemExit, Exception):  # no config / no key: fall through to the error below
        pass
    return None, None


def list_inputs(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            out.extend(sorted(glob.glob(os.path.join(p, "*.xml"))))
        elif os.path.isfile(p):
            out.append(p)
        else:
            raise SystemExit("reset_ctf_cs: no such file or directory: %s" % p)
    return out


def process(path, cs, zero_odd):
    """Return (new_text or None if unchanged, summary dict). Raises ValueError on a bad file."""
    raw = open(path, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    m = CTF_BLOCK.search(text)
    if not m:
        raise ValueError("no <CTF> block")
    block = m.group(1)
    s = {"cs_before": get_param(block, "Cs"), "odd_before": split_coeffs(get_param(block, "ZernikeCoeffsOdd"))}
    om = OPT_BLOCK.search(text)
    s["opt_cs"] = get_param(om.group(1), "Cs") if om else None
    if s["cs_before"] is None:
        raise ValueError('no <Param Name="Cs"> in <CTF>')
    block, _ = set_param(block, "Cs", fmt_cs(cs))
    if zero_odd and get_param(block, "ZernikeCoeffsOdd") is not None:
        n = len(s["odd_before"])
        block, _ = set_param(block, "ZernikeCoeffsOdd", ";".join(["0"] * n))
    new = text[:m.start(1)] + block + text[m.end(1):]
    ET.fromstring(new.encode("utf-8"))  # must still be well-formed XML
    s["changed"] = new != text
    return (("﻿" if bom else "") + new) if s["changed"] else None, s


def describe(name, s, cs, zero_odd):
    odd = [abs(float(x)) for x in s["odd_before"]]
    nz = sum(1 for x in odd if x > 0)
    line = "%-28s Cs %s -> %s" % (name, s["cs_before"], fmt_cs(cs))
    if zero_odd:
        line += "   odd Zernike %d/%d non-zero (max |c| %.4g) -> 0" % (nz, len(odd), max(odd) if odd else 0.0)
    else:
        line += "   odd Zernike %d/%d non-zero (kept)" % (nz, len(odd))
    if s["opt_cs"] is not None and abs(float(s["opt_cs"]) - cs) > 1e-3:
        line += "   [OptionsCTF Cs %s differs - left alone]" % s["opt_cs"]
    return line + ("" if s["changed"] else "   (already nominal)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="tilt-series XML files and/or directories holding them")
    dst = ap.add_mutually_exclusive_group(required=True)
    dst.add_argument("--out_dir", help="write edited copies here (created; must differ from every input folder)")
    dst.add_argument("--in_place", action="store_true", help="overwrite the inputs (only on a private copy!)")
    ap.add_argument("--cs_mm", type=float, help="nominal Cs in mm (default: MICROSCOPE_CS_MM from the config)")
    ap.add_argument("--zero_zernike_odd", action="store_true", help="also zero ZernikeCoeffsOdd (beam tilt, trefoil)")
    ap.add_argument("--dry_run", action="store_true", help="print the summary, write nothing")
    a = ap.parse_args(argv)

    cs, origin = resolve_cs(a.cs_mm)
    if cs is None:
        ap.error("no Cs: pass --cs_mm (read it from the microscope / the XML's <OptionsCTF> / the .settings) "
                 "or set MICROSCOPE_CS_MM in the cryoet-skills config")
    if not 0.0 <= cs <= 10.0:
        ap.error("--cs_mm %.3f is outside 0-10 mm; Warp stores Cs in millimetres" % cs)
    files = list_inputs(a.inputs)
    if not files:
        raise SystemExit("reset_ctf_cs: no *.xml found in %s" % " ".join(a.inputs))
    if a.out_dir:
        od = os.path.realpath(a.out_dir)
        if any(os.path.realpath(os.path.dirname(f)) == od for f in files):
            ap.error("--out_dir is an input folder; use --in_place explicitly if that is what you want")
        names = [os.path.basename(f) for f in files]
        if len(set(names)) != len(names):
            ap.error("two inputs share a file name; they would overwrite each other in --out_dir")
        if not a.dry_run:
            os.makedirs(a.out_dir, exist_ok=True)

    print("reset_ctf_cs: Cs -> %s mm (from %s)%s%s" % (fmt_cs(cs), origin, ", zeroing odd Zernikes" if a.zero_zernike_odd
                                                      else "", "  [DRY RUN]" if a.dry_run else ""))
    bad = changed = 0
    for f in files:
        name = os.path.basename(f)
        try:
            new, s = process(f, cs, a.zero_zernike_odd)
        except (ValueError, ET.ParseError, UnicodeDecodeError) as e:
            print("%-28s SKIPPED: %s" % (name, e)); bad += 1
            continue
        print(describe(name, s, cs, a.zero_zernike_odd))
        changed += bool(new is not None)
        if a.dry_run:
            continue
        if a.out_dir:
            target = os.path.join(a.out_dir, name)
            data = new if new is not None else open(f, "rb").read().decode("utf-8")
        elif new is not None:
            target, data = f, new
        else:
            continue
        tmp = target + ".tmp_reset"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(data)
        os.replace(tmp, target)
    where = "(dry run, nothing written)" if a.dry_run else ("in place" if a.in_place else "-> %s" % a.out_dir)
    print("%d file(s): %d changed, %d already nominal, %d skipped %s" % (len(files), changed, len(files) - changed - bad,
                                                                          bad, where))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
