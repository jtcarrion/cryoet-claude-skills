#!/usr/bin/env python3
"""Put a reference map and a solvent mask on EXACTLY the export grid (pixel size + box), centred, for relion_refine.

  "$CRYOET_PYTHON" prep_reference.py --ref map.mrc --angpix 2.25 --box 208 --lowpass 40 --out ref_2p25A_box208_lp40.mrc
  "$CRYOET_PYTHON" prep_reference.py --mask mask.mrc --angpix 2.25 --box 208 --out mask_2p25A_box208.mrc [--mask-volume-check 3.0e6]
  optional: --flip z|y|x  (hand flip by array reversal BEFORE resampling) ; --header-apix A (override a wrong header,
            e.g. RELION writes 2.2526 for 2.25)

Why: a reference/mask on a different grid is silently misinterpreted. Resampling is real-space (scipy
map_coordinates, cubic for maps / linear for masks) about the box centre. Masks are clamped to [0,1] and their stats
recomputed from the ARRAY (Fourier rescaling rings: values -0.01..1.025 made relion_postprocess abort, and the header
min/max lied). Reports the mask's enclosed volume: size masks by VOLUME, not diameter (a sphere "a bit larger than
the particle" can enclose several times the molecule, and an oversized mask stops the refine from converging).
--lowpass L is a Gaussian, amplitude exp(-(k*L)^2/2): 0.61 at 1/L (other tools call a steeper filter "low-pass").
HAND: check a public/external reference's hand against your data before a long run (a wrong-hand seed converges to
the wrong hand and stalls far below the data's resolution); the defocus-hand check does not see this. Make the mirror
with --flip z and compare both in bench_iter1.sbatch, without --firstiter_cc.
"""
import argparse, sys
import numpy as np, mrcfile
from scipy import ndimage


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--ref"); g.add_argument("--mask")
    ap.add_argument("--angpix", type=float, required=True); ap.add_argument("--box", type=int, required=True)
    ap.add_argument("--out", required=True); ap.add_argument("--lowpass", type=float, help="Gaussian low-pass (A), refs only")
    ap.add_argument("--flip", choices=["x", "y", "z"]); ap.add_argument("--header-apix", type=float)
    ap.add_argument("--mask-volume-check", type=float, help="expected molecular volume (A^3) to compare against")
    a = ap.parse_args()
    src = a.ref or a.mask; is_mask = bool(a.mask)
    with mrcfile.open(src, permissive=True) as m:
        v = np.asarray(m.data, np.float32); apix = a.header_apix or float(m.voxel_size.x)
    if a.flip:
        v = {"z": v[::-1], "y": v[:, ::-1], "x": v[:, :, ::-1]}[a.flip].copy()
    n_in = np.array(v.shape, float); c_in = (n_in - 1) / 2; c_out = (a.box - 1) / 2
    q = (np.indices((a.box,) * 3, dtype=np.float32) - c_out) * (a.angpix / apix)
    coords = q + c_in.reshape(3, 1, 1, 1)
    out = ndimage.map_coordinates(v, coords, order=1 if is_mask else 3, mode="constant", cval=0.0).astype(np.float32)
    if a.lowpass and not is_mask:
        f = np.fft.fftn(out); k = [np.fft.fftfreq(a.box, d=a.angpix)] * 3
        kk = np.sqrt(k[0][:, None, None] ** 2 + k[1][None, :, None] ** 2 + k[2][None, None, :] ** 2)
        out = np.real(np.fft.ifftn(f * np.exp(-(kk * a.lowpass) ** 2 / 2))).astype(np.float32)
    if is_mask:
        out = np.clip(out, 0, 1)
    with mrcfile.new(a.out, overwrite=False) as o:
        o.set_data(out); o.voxel_size = a.angpix
        o.header.origin = (0.0, 0.0, 0.0); o.header.nxstart = o.header.nystart = o.header.nzstart = 0
        o.update_header_stats()
    print(f"{src}: {tuple(v.shape)} @ {apix:.4f} A -> {a.out}: box {a.box} @ {a.angpix} A"
          f"{' flipped ' + a.flip if a.flip else ''}{' lp ' + str(a.lowpass) + ' A' if a.lowpass else ''}")
    print(f"array min/max {out.min():.4g} / {out.max():.4g}")
    if is_mask:
        vol = float((out >= 0.5).sum()) * a.angpix ** 3
        print(f"mask core (>=0.5) volume {vol:.3g} A^3" + (f" = {vol / a.mask_volume_check:.2f} x expected" if a.mask_volume_check else ""))
        if a.mask_volume_check and vol / a.mask_volume_check > 2.0:
            print("WARN mask core is >2x the molecule: oversized masks dilute the FSC that drives sampling")
    with mrcfile.open(a.out, permissive=True, header_only=True) as m:
        cz = float(m.header.cella.z)
    if abs(cz - a.box * a.angpix) > 0.01:
        sys.exit(f"FAIL header cella.z {cz} != box x angpix {a.box * a.angpix}")


if __name__ == "__main__":
    main()
