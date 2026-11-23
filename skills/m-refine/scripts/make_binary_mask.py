#!/usr/bin/env python3
"""Tight BINARY mask for MTools create_species (M grows it itself by ~3 x current resolution before its FSC).

  make_binary_mask.py --map postprocess.mrc --out mask_binary.mrc (--volume A3 | --mw-kda KDA)
                      [--soft-mask relion_soft.mrc] [--lowpass 15] [--apix A]

Recipe: low-pass the map (Gaussian, exp(-2 (r*lp)^2)), threshold at the level enclosing the molecular volume
(--volume in A^3, or 1.21 A^3/Da x --mw-kda), keep the largest connected component, and keep it inside the RELION soft
mask if given. There is no default volume: give the particle's size. Cubic maps only. Written at the MAP's pixel size -
create_species checks that half-map and mask pixel sizes match BEFORE any --angpix override, so stage header-corrected
copies if needed (create_population.sbatch does).
Do NOT measure FSC on this mask: it is too tight (fscrand_hi far above 0.05). Measure on the RELION soft mask with
measure_halfmaps.py. If the AND with the soft mask removes much of the target volume, the printed volume says so.
"""
import argparse
import numpy as np, mrcfile
from scipy import ndimage


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--map", required=True); ap.add_argument("--out", required=True); ap.add_argument("--soft-mask")
    g = ap.add_mutually_exclusive_group(required=True); g.add_argument("--volume", type=float); g.add_argument("--mw-kda", type=float)
    ap.add_argument("--lowpass", type=float, default=15.0); ap.add_argument("--apix", type=float)
    a = ap.parse_args()
    with mrcfile.open(a.map, permissive=True) as m:
        v = np.asarray(m.data, np.float32); apix = a.apix or float(m.voxel_size.x)
    vol = a.volume if a.volume else a.mw_kda * 1000 * 1.21
    if len(set(v.shape)) != 1:
        raise SystemExit("map is not cubic: %s" % (v.shape,))
    n = v.shape[0]; f = np.fft.fftfreq(n, d=apix)
    r = np.sqrt(f[:, None, None] ** 2 + f[None, :, None] ** 2 + f[None, None, :] ** 2)
    lp = np.real(np.fft.ifftn(np.fft.fftn(v) * np.exp(-(r * a.lowpass) ** 2 * 2)))
    s = np.sort(lp.ravel())[::-1]; thr = s[min(int(vol / apix ** 3), s.size - 1)]
    b = lp >= thr
    lab, nl = ndimage.label(b)
    if nl > 1:
        sizes = ndimage.sum(b, lab, range(1, nl + 1)); b = lab == (1 + int(np.argmax(sizes)))
    if a.soft_mask:
        with mrcfile.open(a.soft_mask, permissive=True) as m:
            sm = np.asarray(m.data, np.float32)
        if sm.shape != b.shape:
            raise SystemExit(f"soft mask {sm.shape} != map {b.shape}: resample it to the map grid first")
        b &= sm > 0.5
    with mrcfile.new(a.out, overwrite=False) as o:
        o.set_data(b.astype(np.float32)); o.voxel_size = apix
    print(f"binary mask {a.out}: {b.sum() * apix ** 3:.3g} A^3 (target {vol:.3g}), {nl} components before cleanup, apix {apix}")


if __name__ == "__main__":
    main()
