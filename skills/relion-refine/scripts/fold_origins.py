#!/usr/bin/env python3
"""Build a ts_export_particles input STAR from a REFINED RELION star: fold _rlnOrigin*Angst into the centres.

A refined run_data.star stores the particle centre as coordinate x _rlnImagePixelSize - _rlnOrigin*Angst (refined
origins of 10+ A median are common, mostly along Z). Re-exporting from the raw coordinates throws those shifts away and re-cuts
every particle off-centre. This writes centres in ANGSTROM with zero origins, so export with --coords_angpix 1.
Angles, _rlnRandomSubset, _rlnTomoName and every other column are carried through unchanged.

  "$CRYOET_PYTHON" fold_origins.py --star Refine3D/jobNNN/run_data.star --out export_input_folded_A.star
Then run dedup_audit.py --coords-angstrom on the OUTPUT (re-picks converge during refinement, so refined centres can
show several times more pairs within 20 A than the raw coordinates did).
Before re-exporting at all: if pixel size, box and tilt-series geometry are unchanged, the existing stacks are still
valid - build an abspath optimisation set from the refined star instead (make_optset.py) and skip the export.
"""
import argparse, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
import starlite


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--star", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    B = starlite.read(a.star); P = starlite.particles(B); O = B["data_optics"]
    apix = dict(zip(O.values("_rlnOpticsGroup"), O.floats("_rlnImagePixelSize")))
    g = P.values("_rlnOpticsGroup")
    shifts = []
    for c in "XYZ":
        coord = P.floats(f"_rlnCoordinate{c}")
        org = P.floats(f"_rlnOrigin{c}Angst") if f"_rlnOrigin{c}Angst" in P.cols else [0.0] * len(coord)
        P.set_values(f"_rlnCoordinate{c}", [f"{x * apix[k] - o:.3f}" for x, k, o in zip(coord, g, org)])
        if f"_rlnOrigin{c}Angst" in P.cols:
            P.set_values(f"_rlnOrigin{c}Angst", ["0.000"] * len(coord))
        shifts.append(org)
    mag = sorted((x * x + y * y + z * z) ** 0.5 for x, y, z in zip(*shifts))
    starlite.write(a.out, B)
    print(f"{len(mag):,} particles; |origin| folded: median {mag[len(mag) // 2]:.1f} A, max {mag[-1]:.1f} A")
    print(f"wrote {a.out}  -> export with --coords_angpix 1 (centres are now in Angstrom)")


if __name__ == "__main__":
    main()
