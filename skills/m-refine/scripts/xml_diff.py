#!/usr/bin/env python3
"""Which per-tilt-series terms did an MCore (or EstimateWeights) round actually change? Compares PARSED values of a
snapshot folder against the live processing folder. Stdlib only (Python 3.6+).

  xml_diff.py --before <snapshot_dir> --after <processing_dir> [--expect GridMovement:GridAngle | --expect none]
              [--tol 1e-6]

Why parsed values: MCore re-serialises every XML (new attributes, reordered params), so files differ byte-wise even
after --iter 0. A byte/cmp guard false-positives; this reports real changes per term:
  geometry  AxisOffsetX/Y, Angles, UseTilt, GridMovementX/Y (image warp), GridAngleX/Y/Z (stage angles),
            GridVolumeWarpX/Y/Z, MagnificationCorrection
  CTF       Cs, Defocus (scalar), ZernikeCoeffsOdd/Even, GridCTF (per-tilt defocus: M writes refined defocus HERE,
            not into the scalar Defocus), GridCTFDefocusDelta/Angle, GridCTFPhase
  weights   Bfactor, Weight (per series), GridDoseWeights, GridDoseBfacs*, GridLocationWeights/Bfacs (EstimateWeights)
Comparison is NUMERIC with tolerance --tol: a list that is empty or shorter on one side is zero-padded, so MCore's
first-write rewrite of an empty ZernikeCoeffsOdd/Even ("") as "0;0;0;..." is NOT a change (reported as 'reformatted').
Metadata MCore fills on its first write (VolumeDimensionsAngstrom whose old value was a placeholder <= 1 A, e.g. Z = 1
-> the real thickness) is printed as 'info' and never gates. A real change of a non-placeholder dimension is a change.
--expect: term prefixes the round was MEANT to change, separated by ':' ',' or spaces (prefer ':' -- commas get split
  by `sbatch --export`). Anything else that moved is UNEXPECTED. 'none' = nothing may change (iter 0).
  Omit --expect to report without gating.
A grid whose SIZE changed is reported as 'resized WxHxD -> WxHxD' with before/after value stats (never a max |delta|,
which is meaningless across grids). A resize that stays all-zero is informational. Otherwise it counts as a change of
that term for --expect, and it is an ERROR for GridMovement / GridVolumeWarp when the old grid held a non-zero field
(MCore resamples the stored field to the requested size, destroying the inherited deformation) unless --allow_resize.
Exit: 0 ok; 1 UNEXPECTED term changed or a warp grid was lossily resized; 2 no XMLs compared.
"""
import argparse
import glob
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

GRIDS = ["GridMovementX", "GridMovementY", "GridAngleX", "GridAngleY", "GridAngleZ", "GridVolumeWarpX",
         "GridVolumeWarpY", "GridVolumeWarpZ", "GridCTF", "GridCTFDefocusDelta", "GridCTFDefocusAngle", "GridCTFPhase",
         "GridDoseWeights", "GridDoseBfacs", "GridDoseBfacsDelta", "GridDoseBfacsAngle", "GridLocationWeights",
         "GridLocationBfacs"]
WARP_GRIDS = ("GridMovement", "GridVolumeWarp")          # resizing these loses signal
LISTS = ["AxisOffsetX", "AxisOffsetY", "Angles"]
CTF_PARAMS = ("Cs", "Defocus", "ZernikeCoeffsOdd", "ZernikeCoeffsEven")
ROOT_ATTRS = ("MagnificationCorrection", "Bfactor", "Weight")
META_ATTRS = ("VolumeDimensionsAngstrom",)               # filled by MCore on first write; placeholder components <= 1
PLACEHOLDER = 1.0


def nums(s):
    return [float(x) for x in re.split(r"[;,\s]+", (s or "").strip()) if x]


def parse(p):
    r = ET.parse(p).getroot()
    out, meta = {}, {}
    for t in LISTS:
        e = r.find(t)
        if e is not None:
            out[t] = nums(e.text)
    e = r.find("UseTilt")
    if e is not None and e.text:
        out["UseTilt"] = [1.0 if x == "True" else 0.0 for x in e.text.split()]
    ctf = r.find("CTF")
    if ctf is not None:
        for prm in ctf.iter("Param"):
            if prm.get("Name") in CTF_PARAMS:
                try:
                    out[prm.get("Name")] = nums(prm.get("Value", ""))
                except ValueError:
                    pass
    for k in ROOT_ATTRS:
        if r.get(k) is not None:
            try:
                out[k] = nums(r.get(k))
            except ValueError:
                pass
    for k in META_ATTRS:
        if r.get(k) is not None:
            try:
                meta[k] = nums(r.get(k))
            except ValueError:
                pass
    dims = {}
    for g in GRIDS:
        e = r.find(g)
        if e is not None:
            out[g] = [float(nd.get("Value")) for nd in e.iter("Node") if nd.get("Value") is not None]
            dims[g] = "x".join(str(e.get(k)) for k in ("Width", "Height", "Depth") if e.get(k) is not None)
    return out, meta, dims


def pad(b, c):
    n = max(len(b), len(c))
    return b + [0.0] * (n - len(b)), c + [0.0] * (n - len(c))


def vstats(v):
    if not v:
        return "empty"
    a = [abs(x) for x in v]
    return "n %d, max|v| %.4g, rms %.4g" % (len(v), max(a), math.sqrt(sum(x * x for x in v) / len(v)))


def split_expect(s):
    return [x for x in re.split(r"[:,;\s]+", s or "") if x]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", required=True, help="snapshot folder (copied before the round)")
    ap.add_argument("--after", required=True, help="live processing folder")
    ap.add_argument("--expect", default=None, help="term prefixes allowed to change, ':'-separated; 'none' = nothing")
    ap.add_argument("--allow_resize", action="store_true", help="a deliberate new warp-grid size (user-approved)")
    ap.add_argument("--tol", type=float, default=1e-6, help="absolute tolerance below which a value is unchanged")
    a = ap.parse_args(argv)
    gate = a.expect is not None
    exp = [] if (a.expect or "").strip().lower() in ("", "none") else split_expect(a.expect)
    stats, resized, reformatted, info, n = {}, {}, {}, {}, 0
    for pb in sorted(glob.glob(os.path.join(a.before, "*.xml"))):
        pa = os.path.join(a.after, os.path.basename(pb))
        if not os.path.exists(pa):
            continue
        try:
            (B, MB, DB), (A, MA, DA) = parse(pb), parse(pa)
        except ET.ParseError as e:
            print("  WARN cannot parse %s: %s" % (os.path.basename(pb), e))
            continue
        name = os.path.basename(pb)
        n += 1
        for k in set(MB) | set(MA):                         # metadata MCore fills on its first write
            b, c = MB.get(k, []), MA.get(k, [])
            bp, cp = pad(b, c)
            moved = [i for i in range(len(bp)) if abs(bp[i] - cp[i]) > a.tol]
            if not moved:
                continue
            if all(abs(bp[i]) <= PLACEHOLDER for i in moved):
                info.setdefault(k, []).append((name, b, c))
            else:
                st = stats.setdefault(k, [0, 0.0])
                st[0] += 1; st[1] = max(st[1], max(abs(bp[i] - cp[i]) for i in moved))
        for k in set(B) | set(A):
            b, c = B.get(k), A.get(k)
            if (k in DB or k in DA) and DB.get(k) != DA.get(k):
                before_nz = any(abs(v) > a.tol for v in (b or []))
                after_nz = any(abs(v) > a.tol for v in (c or []))
                resized.setdefault(k, []).append((name, DB.get(k), DA.get(k), before_nz, after_nz, b or [], c or []))
                continue
            if b is None or c is None:
                st = stats.setdefault(k, [0, 0.0])        # term appeared or vanished entirely
                st[0] += 1; st[1] = float("nan")
                continue
            bp, cp = pad(b, c)
            d = max([abs(x - y) for x, y in zip(bp, cp)] or [0.0])
            if d > a.tol:
                st = stats.setdefault(k, [0, 0.0])
                st[0] += 1; st[1] = max(st[1], d)
            elif len(b) != len(c):
                reformatted.setdefault(k, []).append(name)
    print("compared %d tilt-series XMLs (parsed values, tol %g)" % (n, a.tol))
    if n == 0:
        print("ERROR nothing compared - wrong --before/--after folder?")
        return 2
    for k, lst in sorted(reformatted.items()):
        print("  ok    %-22s reformatted in %d series (e.g. empty -> zero list), values unchanged" % (k, len(lst)))
    for k, lst in sorted(info.items()):
        nm, b, c = lst[0]
        print("  info  %-22s filled in %d series (placeholder on first write, e.g. %s: %s -> %s) - not a refined term"
              % (k, len(lst), nm, ",".join("%g" % x for x in b), ",".join("%g" % x for x in c)))
    unexpected = []

    def flag(k):
        bad = gate and not any(k.startswith(e) for e in exp)
        if bad and k not in unexpected:
            unexpected.append(k)
        return "   <- UNEXPECTED" if bad else ""

    for k in sorted(stats):
        print("  %-28s changed in %4d series, max |delta| %.4g%s" % (k, stats[k][0], stats[k][1], flag(k)))
    bad_resize = False
    for k, lst in sorted(resized.items()):
        nm, db, da, _, _, vb, va = lst[0]
        n_before = sum(1 for x in lst if x[3])
        n_after = sum(1 for x in lst if x[4])
        if n_before == 0 and n_after == 0:
            print("  info  %-22s resized %s -> %s in %d series, all-zero before and after (no field to lose)"
                  % (k, db, da, len(lst)))
            continue
        lossy = k.startswith(WARP_GRIDS) and n_before > 0 and not a.allow_resize
        bad_resize = bad_resize or lossy
        print("  %-5s %-22s resized %s -> %s in %d series (e.g. %s: before %s; after %s); non-zero before in %d, "
              "after in %d%s%s" % ("ERROR" if lossy else "", k, db, da, len(lst), nm, vstats(vb), vstats(va),
                                   n_before, n_after, flag(k),
                                   " - the inherited warp field was resampled; repeat the existing grid size "
                                   "(or --allow_resize)" if lossy else ""))
    if not stats and not any(x[3] or x[4] for lst in resized.values() for x in lst):
        print("NO parameter changed. If this round refined something, suspect the box-128 no-op (every series "
              "'Final score: 0'), series skipped by --min_particles, or orphaned particles (tomostars rewritten).")
    if unexpected:
        print("UNEXPECTED changes: %s (expected only: %s)" % (" ".join(unexpected), " ".join(exp) or "none"))
    return 1 if (unexpected or bad_resize) else 0


if __name__ == "__main__":
    sys.exit(main())
