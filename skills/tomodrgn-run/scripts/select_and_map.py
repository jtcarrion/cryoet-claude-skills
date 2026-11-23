#!/usr/bin/env python3
"""Turn the USER's class choice into particle sets: the tomoDRGN-input STAR subset, and the same particles in any
other RELION/Warp STAR (e.g. a finer-sampled, premultiplied export for refinement) - joined on (tomogram name,
centre in Angstrom), never on _rlnTomoParticleName (renumbered on every export, so a name join can look perfect per
tilt series while matching the wrong particles).

  select_and_map.py --analyze <workdir>/analyze.<E>_k<k> --classes 3,7,12-19 --tomodrgn-star <star>
                    [--map-to <other.star> ...] [--coords-angpix A] [--tol-A 2.0]
                    [--on-duplicate fail|warn] --out-stem <dir>/<name>

--tomodrgn-star: the STAR whose particle order labels.pkl follows. Prefer the <workdir>/*_tomodrgn_preprocessed.star
  that train_vae writes (it reflects any filtering train_vae applied); the prep output <stem>_tomodrgn.star is the
  same when nothing was filtered. Lengths are asserted.
Centre in A = coordinate x pixel size - _rlnOrigin*Angst. Pixel size per STAR: _rlnImagePixelSize of the particle's
  optics group if there is a data_optics block, else --coords-angpix (Warp per-series coordinate STARs use the
  --coords_angpix units of ts_export_particles). Tomogram key: _rlnTomoName, else _rlnMicrographName without
  extension (Warp per-series STARs).
Uniqueness: a target particle can be the nearest neighbour of several kept particles (duplicates/re-picks, or a
  tolerance that is too loose). Such many-to-one matches inflate the apparent coverage, so they are counted and
  reported; --on-duplicate fail (default) stops without writing that target, warn writes it and prints the count.
Unmatched kept particles are reported, not guessed (> 0.5% unmatched usually means a units/frame problem).
Writes <stem>_kept_tomodrgn.star, <stem>_kept_ind.pkl (0-based particle indices; the form `tomodrgn filter_star --ind`
takes), and for each --map-to: <stem>_kept_<basename>.star. Needs numpy + scipy: run with $CRYOET_PYTHON.
Equivalent official command for the tomoDRGN-side subset:
  tomodrgn filter_star <optset> --starfile-type optimisation_set --labels <labels.pkl> --labels-sel <c1 c2 ..> -o <out>
"""
import argparse
import glob
import os
import pickle
import sys

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
import starlite  # noqa: E402


def parse_classes(s):
    out = []
    for part in s.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return sorted(set(out))


def kmeans_dir(analyze):
    ks = sorted(glob.glob(os.path.join(analyze, "kmeans*", "labels.pkl")))
    if len(ks) != 1:
        sys.exit("FAIL expected exactly one kmeans*/labels.pkl in %s, found %d: %s (point --analyze at one "
                 "analyze.<E>_k<k> folder)" % (analyze, len(ks), ks))
    return os.path.dirname(ks[0])


def centres(B, coords_angpix, label):
    P = starlite.particles(B)
    if "data_optics" in B and "_rlnImagePixelSize" in B["data_optics"].cols and "_rlnOpticsGroup" in P.cols:
        O = B["data_optics"]
        apix = dict(zip(O.values("_rlnOpticsGroup"), O.floats("_rlnImagePixelSize")))
        px = np.array([apix[g] for g in P.values("_rlnOpticsGroup")])
    elif coords_angpix:
        px = np.full(len(P.rows), float(coords_angpix))
    else:
        sys.exit("FAIL %s has no optics pixel size: pass --coords-angpix (the units of its coordinates)" % label)
    xyz = np.stack([np.array(P.floats("_rlnCoordinate%s" % c)) * px for c in "XYZ"], 1)
    for k, c in enumerate("XYZ"):
        if "_rlnOrigin%sAngst" % c in P.cols:
            xyz[:, k] -= np.array(P.floats("_rlnOrigin%sAngst" % c))
    if "_rlnTomoName" in P.cols:
        tomo = P.values("_rlnTomoName")
    elif "_rlnMicrographName" in P.cols:
        tomo = [os.path.splitext(os.path.basename(v))[0] for v in P.values("_rlnMicrographName")]
    else:
        sys.exit("FAIL %s has neither _rlnTomoName nor _rlnMicrographName" % label)
    return P, np.array(tomo), xyz


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analyze", required=True, help="one analyze.<E>_k<k> folder")
    ap.add_argument("--classes", required=True, help="classes to KEEP, e.g. 1-4,7,9")
    ap.add_argument("--tomodrgn-star", required=True)
    ap.add_argument("--map-to", nargs="*", default=[])
    ap.add_argument("--coords-angpix", type=float, help="pixel size of coordinates in STARs without data_optics")
    ap.add_argument("--tol-A", type=float, default=2.0, help="max centre distance for a match (A)")
    ap.add_argument("--on-duplicate", choices=["fail", "warn"], default="fail",
                    help="many-to-one matches into a --map-to STAR: fail (default) or warn")
    ap.add_argument("--out-stem", required=True)
    a = ap.parse_args()
    kd = kmeans_dir(a.analyze)
    labels = np.asarray(pickle.load(open(os.path.join(kd, "labels.pkl"), "rb"))).astype(int)
    sel = parse_classes(a.classes)
    bad = [c for c in sel if c < 0 or c > labels.max()]
    if bad:
        sys.exit("FAIL classes %s not in this analysis (labels 0..%d)" % (bad, labels.max()))
    B = starlite.read(a.tomodrgn_star)
    P, tomo, xyz = centres(B, a.coords_angpix, a.tomodrgn_star)
    if len(labels) != len(P.rows):
        sys.exit("FAIL labels.pkl has %d entries but %s has %d particles (wrong STAR, or train_vae filtered "
                 "particles - use <workdir>/*_tomodrgn_preprocessed.star)" % (len(labels), a.tomodrgn_star, len(P.rows)))
    keep = np.isin(labels, sel)
    print("classes %s: %d of %d particles (%.1f%%)" % (sel, keep.sum(), len(labels), 100 * keep.mean()))
    d = os.path.dirname(os.path.abspath(a.out_stem))
    os.makedirs(d, exist_ok=True)
    P.rows = [r for r, k in zip(P.rows, keep) if k]
    starlite.write(a.out_stem + "_kept_tomodrgn.star", B)
    pickle.dump(np.where(keep)[0], open(a.out_stem + "_kept_ind.pkl", "wb"))
    print("wrote %s_kept_tomodrgn.star, %s_kept_ind.pkl" % (a.out_stem, a.out_stem))
    kt, kx = tomo[keep], xyz[keep]
    rc = 0
    for other in a.map_to:
        B2 = starlite.read(other)
        P2, t2, x2 = centres(B2, a.coords_angpix, other)
        hits = np.zeros(len(P2.rows), int)
        unmatched = 0
        for t in np.unique(kt):
            i1 = np.where(kt == t)[0]
            i2 = np.where(t2 == t)[0]
            if not len(i2):
                unmatched += len(i1)
                continue
            dist, j = cKDTree(x2[i2]).query(kx[i1])
            ok = dist <= a.tol_A
            np.add.at(hits, i2[j[ok]], 1)
            unmatched += int((~ok).sum())
        take = hits > 0
        n_dup_targets = int((hits > 1).sum())
        n_dup_extra = int((hits[hits > 1] - 1).sum())
        cover = take.sum() / float(max(len(kx), 1))
        print("%s: %d kept -> %d distinct target particles (of %d in that STAR); unmatched %d; many-to-one: %d "
              "targets hit by %d extra kept particles"
              % (other, len(kx), int(take.sum()), len(t2), unmatched, n_dup_targets, n_dup_extra))
        if n_dup_targets:
            msg = ("many-to-one matches into %s: duplicates in the kept set or a loose --tol-A (%.1f A). "
                   "Deduplicate (relion-refine's duplicate audit) or tighten the tolerance" % (other, a.tol_A))
            if a.on_duplicate == "fail":
                print("FAIL " + msg + "; nothing written for this target (rerun with --on-duplicate warn to accept)")
                rc = 1
                continue
            print("WARN " + msg)
        if cover < 0.995:
            print("WARN only %.1f%% of kept particles matched: check units (--coords-angpix), frame, tolerance"
                  % (100 * cover))
        P2.rows = [r for r, k in zip(P2.rows, take) if k]
        outp = "%s_kept_%s" % (a.out_stem, os.path.basename(other))
        starlite.write(outp, B2)
        print("  -> %s" % outp)
    sys.exit(rc)


if __name__ == "__main__":
    main()
