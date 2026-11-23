#!/usr/bin/env python3
"""Transfer check after create_population + MCore --iter 0: did the RELION particles arrive in M where RELION had them,
and does the iter-0 map measure like the RELION map? Independent of the XML audit (xml_diff) - run it even when the
audit fails, so a false audit alarm never hides whether iteration 0 is valid. numpy only (Python 3.8+).

  check_transfer.py --population P.population --particles run_data.star [--species NAME]
                    [--relion-res A] [--max-gap A] [--tol-pos A] [--csv rounds_measured.csv]

1. Positions: every M particle (_wrpCoordinateX1/Y1/Z1, Angstrom) must sit within --tol-pos (0.5 A) of a RELION
   particle of the same tilt series at  coord * _rlnImagePixelSize - _rlnOrigin*Angst  (both directions, nearest
   neighbour per series), and the counts must agree. Symptom of a failure: origins not applied, wrong pixel size in
   the coordinates, series names that do not map, or a stale particle table. (An M table given as --particles,
   i.e. with _wrpCoordinateX1, is compared as is.)
2. Resolution: the iter0 row of --csv (written by m_status.py --save-round iter0 --mask ...) must have
   fscrand_hi <= 0.05 and FSC0.143 no more than --max-gap (default 0.5 A; "a few tenths") worse than --relion-res
   (the RELION number on the SAME mask). Without --relion-res it falls back to _rlnCurrentResolution in the
   run_model.star next to --particles and only WARNS (that number uses RELION's own mask).
Exit: 0 PASS; 5 FAIL (positions, count or resolution); 2 bad input.
"""
import argparse
import csv
import glob
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
import starlite  # noqa: E402
import xml.etree.ElementTree as ET  # noqa: E402


def series_key(s):
    b = os.path.basename(s)
    for ext in (".tomostar", ".xml", ".mrc", ".st"):
        if b.endswith(ext):
            b = b[: -len(ext)]
    return b


def relion_positions(path):
    blocks = starlite.read(path)
    p = starlite.particles(blocks)
    if "_wrpCoordinateX1" in p.cols:                       # an M table given as input
        xyz = np.array([p.floats("_wrpCoordinate%s1" % a) for a in "XYZ"]).T
        return xyz, [series_key(s) for s in p.values("_wrpSourceName")]
    pix = None
    if "_rlnImagePixelSize" in p.cols:
        pix = np.array(p.floats("_rlnImagePixelSize"))
    elif "data_optics" in blocks:
        o = blocks["data_optics"]
        m = dict(zip(o.values("_rlnOpticsGroup"), o.floats("_rlnImagePixelSize")))
        pix = np.array([m[g] for g in p.values("_rlnOpticsGroup")])
    if pix is None:
        raise ValueError("no _rlnImagePixelSize in %s" % path)
    c = np.array([p.floats("_rlnCoordinate" + a) for a in "XYZ"]).T
    og = np.zeros_like(c)
    for i, a in enumerate("XYZ"):
        if "_rlnOrigin%sAngst" % a in p.cols:
            og[:, i] = p.floats("_rlnOrigin%sAngst" % a)
    return c * pix[:, None] - og, [series_key(s) for s in p.values("_rlnTomoName")]


def nn_dist(a, b, chunk=1024):
    out = np.empty(len(a))
    for i in range(0, len(a), chunk):
        d = ((a[i:i + chunk, None, :] - b[None, :, :]) ** 2).sum(-1)
        out[i:i + chunk] = np.sqrt(d.min(1))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--population", required=True)
    ap.add_argument("--particles", required=True, help="the PARTICLES table the population was created from")
    ap.add_argument("--species", help="species name (default: the only/first active species)")
    ap.add_argument("--relion-res", type=float, help="RELION FSC0.143 (A) on the same fixed mask")
    ap.add_argument("--max-gap", type=float, default=0.5, help="allowed iter0 - RELION FSC0.143 gap (A)")
    ap.add_argument("--tol-pos", type=float, default=0.5, help="position tolerance (A)")
    ap.add_argument("--csv", help="rounds_measured.csv (default: next to the population)")
    a = ap.parse_args(argv)
    popdir = os.path.dirname(os.path.abspath(a.population))
    try:
        specs = [os.path.join(popdir, s.get("Path")) for s in ET.parse(a.population).getroot().iter("Species")
                 if s.get("Path")]
    except (ET.ParseError, OSError) as e:
        print("ERROR cannot read %s: %s" % (a.population, e)); return 2
    sp = None
    for s in specs:
        name = next((q.get("Value") for q in ET.parse(s).getroot().iter("Param") if q.get("Name") == "Name"), None)
        if a.species in (None, name):
            sp = (s, name); break
    if sp is None:
        print("ERROR species %s not found in %s" % (a.species or "<any>", a.population)); return 2
    sdir, name = os.path.dirname(sp[0]), sp[1]
    cand = glob.glob(os.path.join(popdir, "rounds", "iter0_%s" % name, "%s_particles.star" % name)) or \
        [os.path.join(sdir, "%s_particles.star" % name)]
    mstar = cand[0]
    if not os.path.exists(mstar):
        print("ERROR no M particle table (%s)" % mstar); return 2
    ok = True
    print("=== transfer check: species %s, M table %s" % (name, mstar))
    m = starlite.particles(starlite.read(mstar))
    mxyz = np.array([m.floats("_wrpCoordinate%s1" % ax) for ax in "XYZ"]).T
    msrc = [series_key(s) for s in m.values("_wrpSourceName")] if "_wrpSourceName" in m.cols else ["?"] * len(mxyz)
    rxyz, rsrc = relion_positions(a.particles)
    print("  particles: M %d, input %d" % (len(mxyz), len(rxyz)))
    if len(mxyz) != len(rxyz):
        print("  FAIL particle count differs"); ok = False
    rs, ms = np.array(rsrc), np.array(msrc)
    common = sorted(set(rsrc) & set(msrc))
    if not common:
        print("  WARN no series names shared between the tables - comparing all positions together")
        groups = [(np.ones(len(rs), bool), np.ones(len(ms), bool))]
    else:
        groups = [(rs == k, ms == k) for k in common]
        miss = sorted(set(rsrc) ^ set(msrc))
        if miss:
            print("  FAIL series in only one table: %s" % " ".join(miss[:10])); ok = False
    dmax = dmed = 0.0
    for gr, gm in groups:
        if gr.sum() == 0 or gm.sum() == 0:
            continue
        d1, d2 = nn_dist(rxyz[gr], mxyz[gm]), nn_dist(mxyz[gm], rxyz[gr])
        dmax = max(dmax, d1.max(), d2.max()); dmed = max(dmed, float(np.median(d1)))
    print("  positions: RELION coord*pixel - origin -> nearest M particle (per series, both ways): max %.3f A, "
          "median %.4f A (tol %.2f)" % (dmax, dmed, a.tol_pos))
    if dmax > a.tol_pos:
        print("  FAIL M positions differ from RELION's (origins not applied, pixel size, series mapping?)"); ok = False
    if "_wrpRandomSubset" in m.cols:
        vals = m.values("_wrpRandomSubset")
        print("  half sets: " + "  ".join("%s:%d" % (k, vals.count(k)) for k in sorted(set(vals))))
    # resolution
    csvp = a.csv or os.path.join(popdir, "rounds_measured.csv")
    rows = [r for r in csv.DictReader(open(csvp))] if os.path.exists(csvp) else []
    rows = [r for r in rows if r.get("label", "").startswith("iter0")]
    if not rows:
        print("  WARN no iter0 row in %s - resolution part skipped (was the round measured with --mask?)" % csvp)
    else:
        r = rows[-1]; f, frh = float(r["fsc0143"]), float(r["fscrand_hi"])
        rel, strict = a.relion_res, True
        if rel is None:
            ms_ = os.path.join(os.path.dirname(os.path.abspath(a.particles)), "run_model.star")
            if os.path.exists(ms_):
                for line in open(ms_):
                    if line.startswith("_rlnCurrentResolution"):
                        rel, strict = float(line.split()[1]), False
                        break
        print("  iter0 on the fixed mask: FSC0.143 %.2f A, fscrand_hi %.3f; RELION %s%s" % (
            f, frh, "%.2f A" % rel if rel else "unknown",
            "" if strict else " (run_model.star estimate, RELION's own mask - set --relion-res to compare properly)"))
        if frh > 0.05:
            print("  FAIL fscrand_hi > 0.05 (mask manufactures correlation)"); ok = False
        if rel and f - rel > a.max_gap:
            msg = "iter0 is %.2f A worse than RELION (> %.2f): transfer problem (pixel size, hand, particle table)" % (
                f - rel, a.max_gap)
            if strict:
                print("  FAIL " + msg); ok = False
            else:
                print("  WARN " + msg)
    print("TRANSFER CHECK %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
