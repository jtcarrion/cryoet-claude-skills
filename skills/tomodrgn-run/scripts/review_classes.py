#!/usr/bin/env python3
"""Rank tomoDRGN k-means class volumes against a consensus map to help the USER pick classes (it never picks).

  python review_classes.py --analyze <workdir>/analyze.<E>_k<k> --ref <consensus.mrc> --apix <tomoDRGN A/px>
                           [--ref-apix A] [--mask-radius-A R] [--out <dir>]
  python review_classes.py --polarity <one generated volume .mrc> --ref <consensus.mrc> --apix A   # smoke test

Per class: particle count (labels.pkl), BAND CC (10-30 A band-pass of both maps inside a sphere; shared
mid-resolution DETAIL), lp20 CC, detail score (10-30 A band power / lp20 power, relative to the consensus: 1 = as
detailed, featureless blobs -> ~0), occupied volume relative to the consensus, best of same/mirror hand.
Why band CC as well as lp20 CC: a blurred, featureless envelope still scores 0.8-0.95 lp20 CC against a 20 A map, so
lp20 alone cannot flag 'blob' classes; on other sets lp20 separates junk better. The ranking combines both ranks;
read it together with detail, counts and the per-class particle images.
The consensus is resampled (real space, about the centre) onto the tomoDRGN grid (box from the class volumes, --apix);
it must be in the SAME particle frame (a RELION refinement of these particles is ideal).
--polarity: sign of the CC of a generated volume vs the consensus. Clearly negative = trained on the wrong data
polarity (flip UNINVERT for the real run, or generate volumes with --invert); report it before the full training.
Class volumes are tomoDRGN analyze's kmeans<k>/vol_<NNN>.mrc (NNN = 0-based class index = labels.pkl value).
Assumes cubic boxes centred on the particle in both maps. Point --analyze at ONE analyze.<E>_k<k> folder.
Outputs: classes.tsv, montage.png (central slices), summary.txt. CPU only, minutes. Needs numpy, scipy, mrcfile
(matplotlib for the montage): run with $CRYOET_PYTHON.
"""
import argparse, glob, os, pickle, sys
import numpy as np, mrcfile
from scipy import ndimage


def load(p):
    with mrcfile.open(p, permissive=True) as m:
        return np.asarray(m.data, np.float32), float(m.voxel_size.x)


def to_grid(v, apix_in, n, apix_out):
    c_in = (np.array(v.shape) - 1) / 2; c_out = (n - 1) / 2
    q = (np.indices((n,) * 3, dtype=np.float32) - c_out) * (apix_out / apix_in) + c_in.reshape(3, 1, 1, 1)
    return ndimage.map_coordinates(v, q, order=1, mode="constant").astype(np.float32)


def filt(v, apix, lo=None, hi=None):
    f = np.fft.fftfreq(v.shape[0], d=apix)
    r = np.sqrt(f[:, None, None] ** 2 + f[None, :, None] ** 2 + f[None, None, :] ** 2)
    g = np.exp(-(r * hi) ** 2 * 2) if hi else 1.0
    if lo:
        g = g * (1 - np.exp(-(r * lo) ** 2 * 2))
    return np.real(np.fft.ifftn(np.fft.fftn(v) * g))


def cc(a, b, m):
    a = a[m] - a[m].mean(); b = b[m] - b[m].mean()
    return float((a * b).sum() / np.sqrt((a * a).sum() * (b * b).sum() + 1e-30))


def scores(vol, ref, m, apix, ref_detail, ref_occ):
    out = {}
    for hand, v in (("same", vol), ("mirror", vol[::-1].copy())):
        b = cc(filt(v, apix, 30, 10), filt(ref, apix, 30, 10), m); l = cc(filt(v, apix, None, 20), filt(ref, apix, None, 20), m)
        out[hand] = (b, l, v)
    hand = max(out, key=lambda h: out[h][0]); b, l, v = out[hand]
    lp = filt(v, apix, None, 20); bp = filt(v, apix, 30, 10)
    detail = float((bp[m] ** 2).sum() / ((lp[m] ** 2).sum() + 1e-30)) / ref_detail
    thr = np.percentile(lp[m], 90)
    occ = float((lp[m] > thr * 0.5).sum()) / ref_occ
    return hand, b, l, detail, occ


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--analyze"); ap.add_argument("--polarity"); ap.add_argument("--ref", required=True)
    ap.add_argument("--apix", type=float, required=True); ap.add_argument("--ref-apix", type=float)
    ap.add_argument("--mask-radius-A", type=float); ap.add_argument("--out")
    a = ap.parse_args()
    if not (a.analyze or a.polarity):
        sys.exit("give --analyze or --polarity")
    k_dir = None
    if a.analyze:
        kds = sorted(glob.glob(os.path.join(a.analyze, "kmeans*", "labels.pkl")))
        if len(kds) != 1:
            sys.exit("expected exactly one kmeans*/labels.pkl under %s, found %d (point --analyze at one "
                     "analyze.<E>_k<k> folder)" % (a.analyze, len(kds)))
        k_dir = os.path.dirname(kds[0])
    vols = [a.polarity] if a.polarity else sorted(glob.glob(os.path.join(k_dir, "vol_*.mrc")))
    if not vols:
        sys.exit("no class volumes (vol_*.mrc) found")
    v0, _ = load(vols[0]); n = v0.shape[0]
    ref, rap = load(a.ref); ref = to_grid(ref, a.ref_apix or rap, n, a.apix)
    rr = (a.mask_radius_A or 0.45 * n * a.apix) / a.apix
    z = np.indices((n,) * 3) - (n - 1) / 2; m = np.sqrt((z ** 2).sum(0)) <= rr
    rlp = filt(ref, a.apix, None, 20); rbp = filt(ref, a.apix, 30, 10)
    ref_detail = float((rbp[m] ** 2).sum() / ((rlp[m] ** 2).sum() + 1e-30))
    ref_occ = float((rlp[m] > np.percentile(rlp[m], 90) * 0.5).sum())
    if a.polarity:
        b_same = cc(filt(v0, a.apix, None, 20), rlp, m); b_mir = cc(filt(v0[::-1].copy(), a.apix, None, 20), rlp, m)
        best = max(b_same, b_mir, key=abs)
        verdict = ("OK: positive correlation - data polarity matches" if best > 0.2 else
                   "INVERTED: clearly negative - train with the opposite UNINVERT setting (or --invert the volumes)" if best < -0.2 else
                   "UNCLEAR: |CC| < 0.2 - a 1-epoch model may be too weak; look at the volume, or train a few epochs")
        print(f"polarity: lp20 CC same-hand {b_same:+.3f}, mirror {b_mir:+.3f} -> {verdict}")
        return
    labels = pickle.load(open(os.path.join(k_dir, "labels.pkl"), "rb"))
    counts = np.bincount(np.asarray(labels).astype(int))
    rows = []
    for p in vols:
        idx = int(os.path.basename(p).split("_")[1].split(".")[0])
        v, _ = load(p)
        hand, b, l, d, o = scores(v, ref, m, a.apix, ref_detail, ref_occ)
        rows.append((idx, int(counts[idx]) if idx < len(counts) else 0, b, l, d, o, hand, v))
    # relative, not absolute: a sharp consensus makes every class look "low detail", and fixed CC thresholds all pass
    med_detail = float(np.median([r[4] for r in rows])) or 1e-9
    rows = [(i, n_, b, l, d / med_detail, o, h, v) for (i, n_, b, l, d, o, h, v) in rows]
    rb = {r[0]: k for k, r in enumerate(sorted(rows, key=lambda r: -r[2]), 1)}
    rl = {r[0]: k for k, r in enumerate(sorted(rows, key=lambda r: -r[3]), 1)}
    rows.sort(key=lambda r: (rb[r[0]] + rl[r[0]], rb[r[0]]))
    out = a.out or a.analyze
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "classes.tsv"), "w") as f:
        f.write("combined_rank\tclass\tn_particles\tband_cc_10_30A\tband_rank\tlp20_cc\tlp20_rank\tdetail_vs_median\toccupancy_rel\thand\n")
        for k, r in enumerate(rows, 1):
            f.write(f"{k}\t{r[0]}\t{r[1]}\t{r[2]:.3f}\t{rb[r[0]]}\t{r[3]:.3f}\t{rl[r[0]]}\t{r[4]:.2f}\t{r[5]:.2f}\t{r[6]}\n")
    tot = int(counts.sum()); q = max(1, len(rows) // 4)
    bottom = rows[-q:]
    lines = [f"{os.path.basename(a.analyze)}: {len(rows)} classes, {tot:,} particles; ordered by combined rank "
             "(band CC 10-30 A + lp20 CC) - the USER decides",
             f"  bottom quarter by combined rank: {[r[0] for r in bottom]} ({sum(r[1] for r in bottom):,} particles)",
             f"  lowest band CC: {[r[0] for r in sorted(rows, key=lambda r: r[2])[:q]]};  lowest lp20 CC: "
             f"{[r[0] for r in sorted(rows, key=lambda r: r[3])[:q]]}",
             "  possible blobs (detail < 0.5 x median class, lp20 CC above median): "
             + str([r[0] for r in rows if r[4] < 0.5 and r[3] > np.median([x[3] for x in rows])]),
             "  Check each candidate's volume (montage.png / ChimeraX) and per-class particle images before deciding."]
    open(os.path.join(out, "summary.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        nc = 10; nr = int(np.ceil(len(rows) / nc))
        fig, axs = plt.subplots(nr, nc, figsize=(nc * 1.6, nr * 1.8))
        for ax, r in zip(np.ravel(axs), rows):
            ax.imshow(filt(r[7], a.apix, None, 15)[n // 2], cmap="gray"); ax.set_axis_off()
            ax.set_title(f"{r[0]} n={r[1]}\nb{r[2]:.2f} d{r[4]:.1f}", fontsize=6)
        for ax in np.ravel(axs)[len(rows):]:
            ax.set_axis_off()
        fig.tight_layout(); fig.savefig(os.path.join(out, "montage.png"), dpi=130)
    except Exception as e:
        print("montage skipped:", e)
    print(f"wrote {out}/classes.tsv, summary.txt, montage.png")


if __name__ == "__main__":
    main()
