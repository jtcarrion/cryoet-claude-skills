#!/usr/bin/env python3
"""Fill a local-resolution map outside its mask, for display (the "hard edge" / level-dependent colour bug).

Local-resolution programs write filler values outside the mask (observed: RELION --locres 0 far outside and ~29-50 A in a
ring just outside; M's _localres.mrc 60 A everywhere outside - version-dependent,
check your own map's outside values). A contour surface crossing the mask edge samples those fillers (0 = best colour,
60 = worst) and colours jump when the level changes. Every voxel outside the mask (or <= 0) takes the value of the NEAREST valid in-mask voxel (Euclidean
distance transform). In-mask values are unchanged (asserted). Display only - never use the filled map for statistics.

  "$CRYOET_PYTHON" fill_locres.py --locres X_locres.mrc --mask X_mask.mrc [--out X_locres_filled.mrc] [--mask-threshold 0.5]
Without --out the file is rewritten in place after moving the original to *_raw.mrc (refuses if that backup exists).
Keeps the input's origin/nstart (so it stays registered with its density; use set_origin.py on ALL bundle maps
together if you need origin 0) and prints a JSON report (outside min/max before and after, inside range).
"""
import argparse, json, os, shutil, sys


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--locres", required=True); ap.add_argument("--mask", required=True)
    ap.add_argument("--out"); ap.add_argument("--mask-threshold", type=float, default=0.5)
    a = ap.parse_args()
    import numpy as np, mrcfile                       # imported here so --help works without them
    from scipy import ndimage
    with mrcfile.open(a.locres, permissive=True) as m:
        lr = np.asarray(m.data, np.float32).copy(); apix = float(m.voxel_size.x)
        h = m.header; org = (float(h.origin.x), float(h.origin.y), float(h.origin.z))
        nst = (int(h.nxstart), int(h.nystart), int(h.nzstart))
    mk = np.asarray(mrcfile.read(a.mask), np.float32) > a.mask_threshold
    if mk.shape != lr.shape:
        sys.exit(f"mask {mk.shape} and local-resolution map {lr.shape} differ - resample the mask onto the same grid first")
    valid = mk & (lr > 0)
    if not valid.any():
        sys.exit("no valid in-mask voxels")
    idx = ndimage.distance_transform_edt(~valid, return_indices=True, return_distances=False)
    filled = lr[tuple(idx)]
    assert np.array_equal(filled[valid], lr[valid]), "in-mask values changed"
    out = a.out
    if not out:
        stem, ext = os.path.splitext(a.locres)
        raw = stem + "_raw" + (ext or ".mrc")
        if os.path.exists(raw):
            sys.exit(f"REFUSING: {raw} exists (already filled?)")
        shutil.move(a.locres, raw); out = a.locres
    with mrcfile.new(out, overwrite=bool(a.out)) as o:
        o.set_data(filled.astype(np.float32)); o.voxel_size = apix
        o.header.origin = org; o.header.nxstart, o.header.nystart, o.header.nzstart = nst
    rep = dict(out=out, apix=apix, valid_fraction=float(valid.mean()),
               outside_before=dict(min=float(lr[~valid].min()), max=float(lr[~valid].max())),
               outside_after=dict(min=float(filled[~valid].min()), max=float(filled[~valid].max())),
               inside=dict(min=float(lr[valid].min()), median=float(np.median(lr[valid])), max=float(lr[valid].max())))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
