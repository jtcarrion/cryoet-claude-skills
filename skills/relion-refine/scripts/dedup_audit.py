#!/usr/bin/env python3
"""Cross-half duplicate audit (and optional dedup) for a RELION 5 particle-series STAR. Run BEFORE every refinement.

Duplicate twins in opposite gold-standard halves correlate the half-maps directly, so the FSC is invalid, not just
optimistic (a few hundred cross-half pairs can turn a ~7 A map into a fake ~5 A one). fscrand_hi cannot see it; the tell is an FSC
that plateaus at 0.10-0.14 towards Nyquist instead of decaying. It cannot be fixed after refinement.

Centres in Angstrom = coordinate x _rlnImagePixelSize (EXPORT pixels, not tilt-series pixels) - _rlnOrigin*Angst.
(Using the tilt-series pixel by mistake silently changes the radius: a "20 A audit" becomes a ~33 A one.)
Pairs are found per tomogram within --radius A (default 20; anything 5-150 A drops the same set on 70S data).

Usage: "$CRYOET_PYTHON" dedup_audit.py --star particles_abspath.star [--radius 20] [--against other.star] [--write deduped.star]
  --against: also count pairs between this set and an EXISTING pool (supply new particles only once);
             --against-coords-angstrom if that pool's coordinates are already in A.
  Pair counts include within-half twins; only cross-half pairs bias the FSC, but --policy drop removes both kinds.
  --write:   write a new STAR, fixing pairs by --policy:
             drop      (default) remove the lower-ranked member of every pair (by --rank-col, e.g.
                       _rlnMaxValueProbDistribution; default keeps the first)
             same-half keep every particle but move each cross-half partner into its twin's half (0 cross-half
                       pairs, N unchanged; within-half twins double-weight but cannot inflate the FSC)
"""
import argparse, os, sys
import numpy as np
from scipy.spatial import cKDTree
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
import starlite


def centres(path, angstrom=False):
    B = starlite.read(path); P = starlite.particles(B); O = B["data_optics"]
    apix = dict(zip(O.values("_rlnOpticsGroup"), O.floats("_rlnImagePixelSize")))
    g = P.values("_rlnOpticsGroup"); px = np.ones(len(g)) if angstrom else np.array([apix[x] for x in g])
    xyz = np.stack([np.array(P.floats(f"_rlnCoordinate{c}")) * px for c in "XYZ"], 1)
    for k, c in enumerate("XYZ"):
        if f"_rlnOrigin{c}Angst" in P.cols:
            xyz[:, k] -= np.array(P.floats(f"_rlnOrigin{c}Angst"))
    half = np.array(P.values("_rlnRandomSubset")) if "_rlnRandomSubset" in P.cols else np.full(len(xyz), "?")
    return B, P, np.array(P.values("_rlnTomoName")), xyz, half


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--star", required=True); ap.add_argument("--radius", type=float, default=20.0)
    ap.add_argument("--against"); ap.add_argument("--write"); ap.add_argument("--rank-col")
    ap.add_argument("--policy", choices=["drop", "same-half"], default="drop")
    ap.add_argument("--coords-angstrom", action="store_true", help="coordinates already in A (fold_origins.py output)")
    ap.add_argument("--against-coords-angstrom", action="store_true", help="--against STAR coordinates already in A")
    a = ap.parse_args()
    B, P, tomo, xyz, half = centres(a.star, a.coords_angstrom)
    n = len(xyz); pairs = []
    for t in np.unique(tomo):
        idx = np.where(tomo == t)[0]
        if len(idx) < 2:
            continue
        for i, j in cKDTree(xyz[idx]).query_pairs(a.radius):
            pairs.append((idx[i], idx[j]))
    cross = [(i, j) for i, j in pairs if half[i] != half[j]]
    print(f"{n:,} particles; pairs within {a.radius:g} A: {len(pairs)} ({len(cross)} cross-half = "
          f"{100 * len(cross) / max(n, 1):.2f}% of particles)")
    nn = []
    for t in np.unique(tomo):
        idx = np.where(tomo == t)[0]
        if len(idx) > 1:
            d, _ = cKDTree(xyz[idx]).query(xyz[idx], k=2); nn.extend(d[:, 1])
    if nn:
        p = np.percentile(nn, [1, 10, 25, 50])
        print(f"nearest-neighbour distance p1/p10/p25/p50 = {p[0]:.1f} / {p[1]:.1f} / {p[2]:.1f} / {p[3]:.1f} A "
              "(a bimodal jump from ~1 A to ~particle size means exact re-picks)")
    if a.against:
        _, _, tomo2, xyz2, _ = centres(a.against, a.against_coords_angstrom); hit = 0
        for t in np.unique(tomo):
            i1 = np.where(tomo == t)[0]; i2 = np.where(tomo2 == t)[0]
            if len(i2):
                d, _ = cKDTree(xyz2[i2]).query(xyz[i1]); hit += int((d <= a.radius).sum())
        print(f"{hit:,} of {n:,} particles lie within {a.radius:g} A of a particle in {a.against} (not new supply)")
    if a.write and a.policy == "same-half":
        hi = P.col("_rlnRandomSubset"); moved = 0
        for i, j in cross:
            P.rows[j][hi] = P.rows[i][hi]; moved += 1
        starlite.write(a.write, B)
        print(f"wrote {a.write}: moved {moved} partners into their twin's half, kept all {len(P.rows):,}")
        return
    if a.write:
        drop = set()
        if a.rank_col:
            r = np.array(P.floats(a.rank_col))
            for i, j in pairs:
                drop.add(j if r[i] >= r[j] else i)
        else:
            for i, j in pairs:
                drop.add(max(i, j))
        P.rows = [row for k, row in enumerate(P.rows) if k not in drop]
        starlite.write(a.write, B)
        print(f"wrote {a.write}: removed {len(drop):,}, kept {len(P.rows):,}")


if __name__ == "__main__":
    main()
