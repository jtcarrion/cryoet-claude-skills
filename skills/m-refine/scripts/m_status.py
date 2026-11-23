#!/usr/bin/env python3
"""State of an M population: active species, version, GlobalResolution, particles per tilt series, the next round's
refinement box (box-128 check), and optionally save + measure this round's half-maps.

  m_status.py --population P.population [--species NAME] [--save-round LABEL]
              [--mask relion_soft_mask.mrc] [--ref guard_map.mrc --ref-apix A [--ref-kind external|relion]
              [--relion-res A]] [--min-per-ts 150]

* Species are read from the .population file (removed species stay on disk - never infer them from folders).
* Refinement box ~= species box x 2 x PixelSize / GlobalResolution, rounded to even (Species.cs in the Warp 2.0 source;
  re-check the formula after a Warp upgrade). Exactly 128 px -> every series logs "Final score: 0", nothing is refined,
  and the round still reports success (126/130 work). Workaround: nudge the species' GlobalResolution so the box lands
  on 126 or 130 - edit the .species only with the user's OK.
* Particles per tilt series is a HEURISTIC predictor of whether M refinement helps (seen on two datasets: gains at
  several hundred/TS, losses well below ~150/TS). Below --min-per-ts the script recommends iter 0 / geometry only.
* --save-round copies the active half-maps, fsc.star, .species and particles.star to <pop dir>/rounds/<LABEL>_<species>/
  (M writes one species version per INVOCATION; half-maps are a few hundred MB each - keep rounds on project storage,
  not scratch).
* --mask: re-measure on the fixed RELION soft mask (measure_halfmaps.py). M's own number uses a mask grown by
  ~1.5 x GlobalRes and is NOT comparable to RELION's.
* --ref / --ref-kind / --relion-res: the cross-FSC guard map (see measure_halfmaps.py). A 'relion' map (same particles)
  is evaluated only at resolutions coarser than --relion-res.
Exit: 0 ok; 1 measurement failed; 2 bad input.
"""
import argparse
import os
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))


def species_params(path):
    return {p.get("Name"): p.get("Value") for p in ET.parse(path).getroot().iter("Param")}


def mrc_box(p):
    with open(p, "rb") as f:
        return struct.unpack("<3i", f.read(12))[0]


def count_particles(pstar):
    """(n_particles, Counter by _wrpSourceName or None if that column is missing)."""
    cols, col, n, src = [], None, 0, Counter()
    for line in open(pstar):
        t = line.split()
        if not t:
            continue
        if t[0].startswith("_"):
            cols.append(t[0]); continue
        if t[0].startswith(("loop_", "data_", "#")):
            continue
        if cols and len(t) >= len(cols):
            if col is None and n == 0:
                col = cols.index("_wrpSourceName") if "_wrpSourceName" in cols else -1
            n += 1
            if col >= 0:
                src[t[col]] += 1
    return n, (src if col is not None and col >= 0 else None)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--population", required=True); ap.add_argument("--species"); ap.add_argument("--save-round")
    ap.add_argument("--mask"); ap.add_argument("--ref"); ap.add_argument("--ref-apix", type=float)
    ap.add_argument("--ref-kind", choices=("external", "relion"))
    ap.add_argument("--relion-res", type=float, help="RELION FSC0.143 (A): cutoff for a 'relion' guard map")
    ap.add_argument("--min-per-ts", type=float, default=float(os.environ.get("M_MIN_PTCL_PER_TS", 150)),
                    help="particles/TS below which refinement is discouraged (heuristic; env M_MIN_PTCL_PER_TS)")
    a = ap.parse_args(argv)
    popdir = os.path.dirname(os.path.abspath(a.population))
    root = ET.parse(a.population).getroot()
    specs = [os.path.join(popdir, s.get("Path")) for s in root.iter("Species") if s.get("Path")]
    if a.species:
        specs = [s for s in specs if species_params(s).get("Name") == a.species]
    if not specs:
        print("no active species found in the .population file", file=sys.stderr)
        return 2
    rc = 0
    for sp in specs:
        P = species_params(sp); name = P.get("Name"); sdir = os.path.dirname(sp)
        h1 = os.path.join(sdir, "%s_half1.mrc" % name); h2 = os.path.join(sdir, "%s_half2.mrc" % name)
        box = mrc_box(h1); apix = float(P["PixelSize"]); gres = float(P["GlobalResolution"])
        rbox = int(round(box * 2 * apix / gres / 2.0)) * 2
        pstar = os.path.join(sdir, "%s_particles.star" % name)
        n, src = count_particles(pstar) if os.path.exists(pstar) else (0, None)
        print("species %s  version %s (previous %s)" % (name, P.get("Version"), P.get("PreviousVersion")))
        print("  box %d @ %s A/px  GlobalResolution %.3f A (M's own mask convention)  denoiser %s"
              % (box, apix, gres, P.get("ApplyDenoising")))
        if src is None:
            print("  particles %d; WARN no _wrpSourceName column - particles/TS unknown (check the table)" % n)
        else:
            per = n / float(max(len(src), 1))
            print("  particles %d in %d tilt series = %.0f/TS%s" % (
                n, len(src), per, ("   <- low density: fitting NEW shared terms from this set alone is risky (iter 0 / geometry"
                                   " only, or carry geometry from a denser set / companion species)"
                                   if per < a.min_per_ts else "")))
        print("  next refinement box ~ %d px%s" % (rbox, "   <- 128 = SILENT NO-OP (Final score: 0); nudge "
                                                          "GlobalResolution so it is 126/130" if rbox == 128 else ""))
        if a.save_round:
            dst = os.path.join(popdir, "rounds", "%s_%s" % (a.save_round, name))
            os.makedirs(dst)                                   # refuse to overwrite a saved round
            for f in (h1, h2, sp, os.path.join(sdir, "%s_fsc.star" % name), pstar):
                if os.path.exists(f):
                    shutil.copy2(f, dst)
            print("  saved round -> %s" % dst)
            h1, h2 = os.path.join(dst, os.path.basename(h1)), os.path.join(dst, os.path.basename(h2))
        if a.mask:
            cmd = [sys.executable, os.path.join(HERE, "measure_halfmaps.py"), "--half1", h1, "--half2", h2,
                   "--mask", a.mask, "--label", "%s %s" % (a.save_round or "now", name),
                   "--csv", os.path.join(popdir, "rounds_measured.csv")]
            if a.ref:
                cmd += ["--ref", a.ref] + (["--ref-apix", str(a.ref_apix)] if a.ref_apix else [])
                cmd += (["--ref-kind", a.ref_kind] if a.ref_kind else [])
                if a.relion_res and a.ref_kind != "external":
                    cmd += ["--ref-max-res", str(a.relion_res)]
            r = subprocess.call(cmd)
            if r != 0:
                print("  ERROR measure_halfmaps.py failed (rc %d) - this round is NOT measured" % r, file=sys.stderr)
                rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
