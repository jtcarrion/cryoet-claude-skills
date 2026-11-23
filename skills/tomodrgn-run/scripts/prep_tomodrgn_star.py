#!/usr/bin/env python3
"""Make a WarpTools --2d --dont_premultiply particle export safe for tomoDRGN train_vae and write its optimisation set.

  prep_tomodrgn_star.py --star <export>_abspath.star [--tomograms <export>_tomograms.star] [--min-tilts 10]
                        [--cs MM] [--polarity-n 200] [--out-stem <dir>/<name>]

Input: a RELION-5-style particle-series STAR from ts_export_particles --2d --dont_premultiply with ABSOLUTE .mrcs paths
(relion-refine's export step writes <stem>_abspath.star + <stem>_abspath_optimisation_set.star). The tomograms STAR is
taken from --tomograms, else from the neighbouring *_optimisation_set.star, else <stem>_tomograms.star.
Checks and fixes, each with its reason:
  * _rlnCtfDataAreCtfPremultiplied must be 0 in optics AND per particle (train on non-premultiplied series).
  * Negative coordinates: tomoDRGN rejects them -> FAIL; drop or clamp them upstream and re-export.
  * Stale per-particle optics columns (_rlnImageSize, _rlnTomoSubtomogramBinning, ...) are STRIPPED: ts_export_particles
    passes unknown input columns through, and tomoDRGN's optics merge prefers the PARTICLE copy, so an old
    _rlnImageSize silently gives every image a wrong-sized CTF. RELION ignores them; tomoDRGN does not.
  * Tilts per particle (_rlnTomoVisibleFrames, else the stack depth from every stack header) >= --min-tilts.
  * Cs: all optics groups should share the nominal Cs (from --cs, else config MICROSCOPE_CS_MM, else the most common
    value). Per-group refined Cs (e.g. leaked from an M refinement) -> WARN: reset it in the metadata and re-export
    (scripts/_lib/reset_ctf_cs.py).
  * Data polarity, CPU only: central disc vs surrounding ring over --polarity-n particle stacks. Protein BRIGHT
    (centre > ring) -> keep tomoDRGN's default inversion; protein DARK -> train with UNINVERT=1. Assumes particles are
    roughly centred and fill 30-90% of the box; confirm on a trained model with review_classes.py --polarity.
  * In-RAM size estimate (particles x tilts x box^2 x 4 B): if it does not fit the job's memory, train with LAZY=1.
Writes <stem>_tomodrgn.star and <stem>_tomodrgn_optimisation_set.star (absolute paths). Particle ORDER is preserved:
tomoDRGN's labels.pkl follows it (one row per particle in --2d), which select_and_map.py relies on.
Needs numpy + mrcfile for the polarity check only (skipped with a NOTE otherwise). Run with $CRYOET_PYTHON.
"""
import argparse
import collections
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
import starlite  # noqa: E402

STALE = ["_rlnImageSize", "_rlnTomoSubtomogramBinning", "_rlnImageDimensionality", "_rlnVoltage",
         "_rlnSphericalAberration", "_rlnAmplitudeContrast", "_rlnTomoTiltSeriesPixelSize", "_rlnImagePixelSize"]


def config_cs():
    try:
        import cryoet_config as cc
        return cc.cs_mm(cc.load())
    except (SystemExit, Exception):
        return None


def find_tomograms(star, explicit):
    if explicit:
        return os.path.realpath(explicit)
    base = star[:-5]
    opt = base + "_optimisation_set.star"
    if os.path.exists(opt):
        for line in open(opt):
            p = line.split()
            if len(p) >= 2 and p[0] == "_rlnTomoTomogramsFile":
                return os.path.realpath(os.path.join(os.path.dirname(opt), p[1]))
    return base.replace("_abspath", "") + "_tomograms.star"


def stack_depth(path):
    with open(path, "rb") as f:
        return struct.unpack("<3i", f.read(12))[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--star", required=True, help="particle STAR with absolute .mrcs paths")
    ap.add_argument("--tomograms", help="tomograms STAR (default: from the neighbouring optimisation set)")
    ap.add_argument("--min-tilts", type=int, default=10)
    ap.add_argument("--cs", type=float, help="nominal Cs in mm (default: config MICROSCOPE_CS_MM, else majority value)")
    ap.add_argument("--polarity-n", type=int, default=200, help="stacks sampled for the polarity check")
    ap.add_argument("--out-stem", help="default: input path without .star/_abspath")
    a = ap.parse_args()
    star = os.path.realpath(a.star)
    stem = a.out_stem or star[:-5].replace("_abspath", "")
    tomos = find_tomograms(star, a.tomograms)
    if not os.path.exists(tomos):
        sys.exit("FAIL tomograms STAR not found: %s (pass --tomograms)" % tomos)
    B = starlite.read(star)
    P = starlite.particles(B)
    if "data_optics" not in B:
        sys.exit("FAIL no data_optics block: not a RELION-5 / WarpTools particle-series export")
    O = B["data_optics"]
    if not P.rows:
        sys.exit("FAIL %s has no particles" % star)
    fails, notes = [], []

    pm = set(O.values("_rlnCtfDataAreCtfPremultiplied")) if "_rlnCtfDataAreCtfPremultiplied" in O.cols else {"?"}
    if pm != {"0"}:
        fails.append("optics _rlnCtfDataAreCtfPremultiplied = %s; re-export with --dont_premultiply" % sorted(pm))
    if "_rlnCtfDataAreCtfPremultiplied" in P.cols and set(P.values("_rlnCtfDataAreCtfPremultiplied")) != {"0"}:
        fails.append("per-particle _rlnCtfDataAreCtfPremultiplied is not all 0")
    for c in ("_rlnCoordinateX", "_rlnCoordinateY", "_rlnCoordinateZ"):
        if c in P.cols:
            neg = sum(1 for v in P.floats(c) if v < 0)
            if neg:
                fails.append("%d particles with negative %s (tomoDRGN rejects them; drop before export)" % (neg, c))

    stripped = [c for c in STALE if c in P.cols]
    for c in stripped:
        i = P.col(c)
        P.cols.pop(i)
        for r in P.rows:
            r.pop(i)
    if stripped:
        notes.append("stripped stale per-particle optics columns: %s" % stripped)

    images = [v.split("@")[-1] for v in P.values("_rlnImageName")]
    if "_rlnTomoVisibleFrames" in P.cols:
        nt = [v.strip("[]").replace(" ", "").split(",").count("1") for v in P.values("_rlnTomoVisibleFrames")]
        src = "_rlnTomoVisibleFrames"
    else:   # every particle, not a sample: one 12-byte header read per unique stack
        depth = {}
        for p in images:
            if p not in depth:
                depth[p] = stack_depth(p)
        nt = [depth[p] for p in images]
        src = "stack headers (%d files)" % len(depth)
    low = sum(1 for n in nt if n < a.min_tilts)
    if low:
        fails.append("%d of %d particles have < %d tilts" % (low, len(nt), a.min_tilts))

    if "_rlnSphericalAberration" in O.cols:
        cs = O.floats("_rlnSphericalAberration")
        nominal = a.cs if a.cs is not None else config_cs()
        how = "given" if a.cs is not None else ("config MICROSCOPE_CS_MM" if nominal is not None else "majority value")
        if nominal is None:
            nominal = collections.Counter(round(c, 3) for c in cs).most_common(1)[0][0]
        bad = [c for c in cs if abs(c - nominal) > 0.01]
        if bad:
            notes.append("WARN Cs differs from nominal %.3f mm (%s) in %d/%d optics groups (%.2f..%.2f mm): per-group "
                         "refined Cs (e.g. from M) is used by tomoDRGN's CTF - reset it and re-export"
                         % (nominal, how, len(bad), len(cs), min(cs), max(cs)))

    box = None
    try:
        import numpy as np
        import mrcfile
        import random
        random.seed(0)
        sample = random.sample(images, min(a.polarity_n, len(images)))
        bright = n_ok = 0
        for p in sample:
            with mrcfile.mmap(p, permissive=True) as m:
                im = np.asarray(m.data, np.float32)
            im = im.mean(0) if im.ndim == 3 else im
            n_ = im.shape[0]
            box = n_
            yy, xx = np.indices(im.shape) - (n_ - 1) / 2.0
            r = np.hypot(yy, xx)
            c = im[r < 0.15 * n_].mean()
            ring = im[(r > 0.30 * n_) & (r < 0.45 * n_)].mean()
            bright += int(c > ring)
            n_ok += 1
        frac = bright / float(max(n_ok, 1))
        verdict = ("protein BRIGHT -> keep the default inversion (no UNINVERT)" if frac > 0.8 else
                   "protein DARK -> train with UNINVERT=1 (--uninvert-data)" if frac < 0.2 else
                   "UNCLEAR - inspect a few particle images before training")
        notes.append("polarity: centre brighter than ring in %.1f%% of %d sampled stacks -> %s"
                     % (100 * frac, n_ok, verdict))
    except Exception as e:  # noqa: BLE001
        notes.append("polarity check skipped (%s); run it with a python that has numpy + mrcfile" % e)

    if box is None and "_rlnImageSize" in O.cols:
        box = int(float(O.values("_rlnImageSize")[0]))
    if box:
        gb = sum(nt) * box * box * 4 / 1e9
        notes.append("in-RAM image size ~%.1f GB (%d images, box %d): request ~1.5x that as --mem, or train with LAZY=1"
                     % (gb, sum(nt), box))

    srt = sorted(nt)
    print("particles %d; tilts per particle (from %s) min %d median %d max %d"
          % (len(nt), src, srt[0], srt[len(srt) // 2], srt[-1]))
    for n in notes:
        print("NOTE", n)
    for f in fails:
        print("FAIL", f)
    if fails:
        sys.exit(1)
    out_star = stem + "_tomodrgn.star"
    out_opt = stem + "_tomodrgn_optimisation_set.star"
    starlite.write(out_star, B)
    with open(out_opt, "w") as f:
        f.write("\n# version 50001\n\ndata_\n\n_rlnTomoParticlesFile   %s\n_rlnTomoTomogramsFile   %s\n"
                % (os.path.abspath(out_star), os.path.abspath(tomos)))
    print("wrote %s\nwrote %s   <- train_vae input" % (out_star, out_opt))


if __name__ == "__main__":
    main()
