#!/usr/bin/env python3
"""Rewrite MRC headers so bundled maps share one frame: origin 0 (default) or the origin of a reference map.
Data are copied unchanged (no resampling); only origin / nxstart,nystart,nzstart (and optionally the pixel size) change.

  "$CRYOET_PYTHON" set_origin.py MAP [MAP ...] --outdir bundle/maps            # origin 0, nstart 0
  "$CRYOET_PYTHON" set_origin.py A_locres.mrc --like A.mrc --outdir bundle/maps  # copy A.mrc's origin/nstart
  options: --apix 2.25 (write this pixel size, e.g. nominal instead of 2.2526), --force (overwrite outputs)

Why: ChimeraX places voxel (0,0,0) at the header origin (or nstart * pixel when the origin is 0), so a density and
its local-resolution map / mask with different origins detach, and place_matrix.py's matrix assumes origin 0.
CAUTION: an atomic model fitted to a map lives in that map's ORIGINAL frame. If you zero the map's origin, the model no
longer sits in it; the script prints the shift (A, x,y,z) so you can either keep the original origin for every map
(use --like) or move the model by the printed shift (view matrix models #M,1,0,0,-sx,0,1,0,-sy,0,0,1,-sz).
Prints one JSON record per map.
"""
import argparse
import json
import os
import sys


def frame(m):
    h = m.header; apix = float(m.voxel_size.x)
    org = [float(h.origin.x), float(h.origin.y), float(h.origin.z)]
    nst = [int(h.nxstart), int(h.nystart), int(h.nzstart)]
    phys = org if any(org) else [n * apix for n in nst]       # where ChimeraX puts voxel (0,0,0), A
    return org, nst, phys, apix


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("maps", nargs="+")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--like", help="copy this map's origin/nstart instead of zeroing")
    ap.add_argument("--apix", type=float)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    import mrcfile, numpy as np                                  # here so --help works without them
    os.makedirs(a.outdir, exist_ok=True)
    if a.like:
        with mrcfile.open(a.like, permissive=True, header_only=True) as r:
            t_org, t_nst, t_phys, _ = frame(r)
    else:
        t_org, t_nst, t_phys = [0.0] * 3, [0] * 3, [0.0] * 3
    for p in a.maps:
        out = os.path.join(a.outdir, os.path.basename(p))
        if os.path.abspath(out) == os.path.abspath(p):
            sys.exit("%s: output would overwrite the input; choose another --outdir" % p)
        with mrcfile.open(p, permissive=True) as m:
            data = np.asarray(m.data).copy(); org, nst, phys, apix = frame(m)
        apix_out = a.apix or apix
        with mrcfile.new(out, overwrite=a.force) as o:
            o.set_data(data); o.voxel_size = apix_out
            o.header.origin = tuple(t_org); o.header.nxstart, o.header.nystart, o.header.nzstart = t_nst
        shift = [phys[i] - t_phys[i] for i in range(3)]     # how far voxel (0,0,0) moved back, A
        print(json.dumps(dict(map=p, out=out, apix_in=apix, apix_out=apix_out, origin_in=org, nstart_in=nst,
                              origin_out=t_org, nstart_out=t_nst, shift_A_xyz=[round(s, 4) for s in shift])))


if __name__ == "__main__":
    main()
