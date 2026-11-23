#!/usr/bin/env python3
"""QC: compare teamtomo tomograms with WarpTools ts_reconstruct tomograms of the same series (same pixel size).

  python compare_tomograms.py --root <teamtomo output root> --warp-recon <warp processing>/reconstruction [--series a b]
                              [--csv out.csv]

Per series: Pearson correlation at full resolution and after a 1-voxel Gaussian, and the amplitude (std) ratio.
Reference values (teamtomo-workflows README validation, xml_to_tomograms vs WarpTools; see references/): 0.995 / 0.999 / 0.999.
Only meaningful for xml_to_tomograms with warp_compatible: true on the SAME XML the Warp tomogram was made from -
if the XMLs changed since ts_reconstruct ran (M grids, a new import), a lower value says nothing about teamtomo.
A NEGATIVE correlation = opposite contrast convention (e.g. Warp tomograms made without --dont_invert); if the XMLs
also changed after ts_reconstruct, |corr| below ~0.99 says nothing about teamtomo. Shapes must match; a ZYX transpose
or flip is reported rather than silently corrected.
Memory: holds ~6 copies of one float32 tomogram - run it in a CPU job (or a workstation), not on a shared login node.
"""
import argparse, csv, json
from pathlib import Path


def corr(a, b):
    a = a - a.mean(); b = b - b.mean()
    import numpy as np
    return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum()))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True); ap.add_argument("--warp-recon", required=True)
    ap.add_argument("--series", nargs="+"); ap.add_argument("--csv")
    a = ap.parse_args()
    import numpy as np, mrcfile                      # imported here so --help works without them
    from scipy.ndimage import gaussian_filter
    root = Path(a.root); wr = Path(a.warp_recon); rows = []
    for rj in sorted(root.glob("*/run.json")):
        r = json.loads(rj.read_text()); s = r["series"]
        if (a.series and s not in a.series) or r.get("status") != "done":
            continue
        tt = next((rj.parent / v for v in r["outputs"].values() if str(v).endswith(".mrc")), None)
        px = r["config"]["reconstruction"]["pixel_spacing"]
        w = wr / f"{s}_{px:.2f}Apx.mrc"
        if tt is None or not w.exists():
            print(f"{s}: no WarpTools tomogram {w.name} - skipped"); continue
        A = np.asarray(mrcfile.read(tt), np.float32); W = np.asarray(mrcfile.read(w), np.float32)
        row = {"series": s, "px": px, "shape_teamtomo": A.shape, "shape_warp": W.shape}
        if A.shape != W.shape:
            row["note"] = "transposed" if sorted(A.shape) == sorted(W.shape) else "shape mismatch"
            print(f"{s}: {row['note']} {A.shape} vs {W.shape}"); rows.append(row); continue
        row.update(corr_full=round(corr(A, W), 4), corr_smooth=round(corr(gaussian_filter(A, 1), gaussian_filter(W, 1)), 4),
                   amp_ratio=round(float(A.std() / W.std()), 4), corr_zflip=round(corr(A[::-1], W), 4))
        print(f"{s}: corr {row['corr_full']:.4f}  smoothed {row['corr_smooth']:.4f}  amplitude {row['amp_ratio']:.3f}"
              f"  (Z-flipped {row['corr_zflip']:.3f})")
        if row["corr_smooth"] < -0.3:
            row["note"] = "contrast inverted vs WarpTools"
            print(f"  -> NEGATIVE: opposite contrast convention (e.g. ts_reconstruct --dont_invert vs teamtomo's Warp default)."
                  f" Same structure if |corr| is high; compare |corr| {abs(row['corr_smooth']):.3f} with the 0.999 reference")
        rows.append(row)
    if a.csv and rows:
        with open(a.csv, "w", newline="") as f:
            k = sorted({k for r in rows for k in r}, key=lambda k: k != "series")
            w_ = csv.DictWriter(f, fieldnames=k); w_.writeheader(); w_.writerows(rows)


if __name__ == "__main__":
    main()
