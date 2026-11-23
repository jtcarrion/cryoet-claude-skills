#!/usr/bin/env python3
"""Measure an M (or RELION) half-map pair on a FIXED mask, plus the cross-FSC overfitting guard.

  measure_halfmaps.py --half1 h1.mrc --half2 h2.mrc --mask relion_mask.mrc [--label TAG]
                      [--ref independent_map.mrc --ref-apix A] [--csv out.csv]

Method (self-contained; numpy + scipy + mrcfile; cubic boxes only):
  * the mask is RESCALED by pixel size (ndimage.zoom) BEFORE centre-padding/cropping to the half-map box. Padding a
    mask made at a coarser pixel into a finer box without rescaling shrinks it in Angstrom and manufactures a fake,
    better resolution - the fscrand_hi check below catches it.
  * corrected FSC: phase-randomise both halves beyond the shell where the UNMASKED FSC first drops below 0.8,
    then FSC_true = (FSC_masked - FSC_rand) / (1 - FSC_rand) beyond that shell + 2.
  * fscrand_hi = max |FSC of the masked phase-randomised halves| at resolutions finer than 12 A. Must be <= 0.05,
    or the mask edge is manufacturing correlation.
Why: M grows any input mask by ~1.5 x GlobalRes (A) before its own FSC, so M's reported number is NOT comparable to a
RELION number on the same particles. Always re-measure M half-maps on the RELION mask.
--ref: cross-FSC of the UNFILTERED half-map average vs a GUARD reference. A real gain raises own-FSC AND cross-FSC;
overfitting of per-series terms (image warp, stage angles, CTF grids - fitted from both halves) raises own-FSC while
cross-FSC stalls or falls. Never use M's *_filt.mrc (low-passed at M's own resolution); keep the SAME --ref for a whole
series of rounds (the iter0 baseline included).
--ref-kind external (default when --ref-max-res is not given and the name is not run_class*): a map NOT built from these
  particles (EMDB entry of the same complex, hand- and pixel-matched, or a held-out-particle reconstruction); all
  frequencies count.
--ref-kind relion: the RELION run_class001.mrc of the SAME particles. It shares noise with the M half-maps, so beyond
  the RELION resolution its cross-FSC is inflated (high at iter 0, falling when M moves poses) and would flag real gains
  as overfitting. Samples finer than --ref-max-res (the RELION FSC0.143; default: _rlnCurrentResolution in the
  run_model.star next to --ref) are reported n/a, and a caveat is printed.
Reports cross-FSC at 20/12/8/6.5 A and its 0.5 crossing, appends guard_ref/guard_kind/guard_maxres to --csv, and
prints a GUARD line against the previous --csv row measured with the same reference (cross-FSC fell by > 0.01 at any
valid sample = overfitting signature). Exit non-zero on any failure (the GUARD verdict itself never changes the exit).
"""
import argparse, csv, os, re, sys
import numpy as np, mrcfile
from scipy import fft as sfft, ndimage

RAND_THRESH, DIAG_RES_A = 0.8, 12.0
rng = np.random.default_rng(0)


def load(p):
    with mrcfile.open(p, permissive=True) as f:
        return np.asarray(f.data, dtype=np.float32), float(f.voxel_size.x)


def shell_index(n):
    fz = np.fft.fftfreq(n) * n; fy = np.fft.fftfreq(n) * n; fx = np.fft.rfftfreq(n) * n
    return np.rint(np.sqrt(fz[:, None, None] ** 2 + fy[None, :, None] ** 2 + fx[None, None, :] ** 2)).astype(np.int32)


def shell_fsc(F1, F2, sf, nsh):
    num = np.bincount(sf, weights=(F1 * np.conj(F2)).real.ravel(), minlength=nsh)[:nsh]
    d1 = np.bincount(sf, weights=(F1.real ** 2 + F1.imag ** 2).ravel(), minlength=nsh)[:nsh]
    d2 = np.bincount(sf, weights=(F2.real ** 2 + F2.imag ** 2).ravel(), minlength=nsh)[:nsh]
    den = np.sqrt(d1 * d2); out = np.zeros(nsh); g = den > 0; out[g] = num[g] / den[g]
    return out


def randomize_beyond(vol, sh, i_from):
    F = sfft.rfftn(vol, workers=-1); sel = sh > i_from
    F[sel] = (np.abs(F[sel]) * np.exp(1j * rng.uniform(0, 2 * np.pi, size=int(sel.sum())))).astype(F.dtype)
    return sfft.irfftn(F, s=vol.shape, workers=-1).astype(np.float32)


def cross(res, f, thr):
    for i in range(1, len(f)):
        if f[i] < thr <= f[i - 1]:
            t = (f[i - 1] - thr) / (f[i - 1] - f[i])
            return 1.0 / ((1 / res[i - 1]) + t * ((1 / res[i]) - (1 / res[i - 1])))
    return float("nan")


def pad_or_crop(vol, box):
    n = vol.shape[0]
    if n == box:
        return vol
    out = np.zeros((box,) * 3, dtype=np.float32)
    if n > box:
        s = (n - box) // 2; out[:] = vol[s:s + box, s:s + box, s:s + box]
    else:
        s = (box - n) // 2; out[s:s + n, s:s + n, s:s + n] = vol
    return out


def to_grid(v, apix_in, n, apix_out):
    if abs(apix_in - apix_out) > 1e-3:
        v = ndimage.zoom(v, apix_in / apix_out, order=1, prefilter=False).astype(np.float32)
    return pad_or_crop(v, n)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--half1", required=True); ap.add_argument("--half2", required=True)
    ap.add_argument("--mask", required=True); ap.add_argument("--label", default="")
    ap.add_argument("--apix", type=float, help="override the half-map header pixel size")
    ap.add_argument("--ref"); ap.add_argument("--ref-apix", type=float); ap.add_argument("--csv")
    ap.add_argument("--ref-kind", choices=("external", "relion"),
                    help="external = independent map (all frequencies); relion = same-particle RELION map (cut off)")
    ap.add_argument("--ref-max-res", type=float, help="finest resolution (A) at which a 'relion' guard map counts")
    a = ap.parse_args()
    h1, apix = load(a.half1); h2, _ = load(a.half2); apix = a.apix or apix
    mask, mapix = load(a.mask)
    mask = np.clip(to_grid(mask, mapix, h1.shape[0], apix), 0, 1)
    print(f"  mask rescaled {mapix:.4f} -> {apix:.4f} A/px, extent {mask.shape[0] * apix:.1f} A, "
          f"integrated {mask.sum() * apix ** 3 / 1e6:.3f}e6 A^3")
    n = h1.shape[0]; nsh = n // 2 + 1; sh = shell_index(n); sf = sh.ravel()
    res = np.full(nsh, np.inf); res[1:] = n * apix / np.arange(1, nsh)
    un = shell_fsc(sfft.rfftn(h1, workers=-1), sfft.rfftn(h2, workers=-1), sf, nsh)
    b = np.where(un[1:] < RAND_THRESH)[0]; ir = int(b[0] + 1) if b.size else nsh - 1
    ma = shell_fsc(sfft.rfftn(h1 * mask, workers=-1), sfft.rfftn(h2 * mask, workers=-1), sf, nsh)
    r1 = randomize_beyond(h1, sh, ir); r2 = randomize_beyond(h2, sh, ir)
    rd = shell_fsc(sfft.rfftn(r1 * mask, workers=-1), sfft.rfftn(r2 * mask, workers=-1), sf, nsh)
    co = ma.copy(); by = np.arange(nsh) > ir + 2; den = 1 - rd; s = by & (np.abs(den) > 1e-6)
    co[s] = (ma[s] - rd[s]) / den[s]
    frh = float(np.max(np.abs(rd[np.where(res < DIAG_RES_A)[0]])))
    line = (f"  [{a.label}] box {n} @ {apix:.4f}  FSC0.5 {cross(res, co, 0.5):.3f}  FSC0.25 {cross(res, co, 0.25):.3f}  "
            f"FSC0.143 {cross(res, co, 0.143):.3f}  fscrand_hi {frh:.3f}" + ("" if frh <= 0.05 else "  <- MASK TOO TIGHT"))
    print(line)
    row = dict(label=a.label, fsc05=cross(res, co, 0.5), fsc0143=cross(res, co, 0.143), fscrand_hi=frh)
    row.update({"xfsc_%sA" % r: "" for r in XFSC_AT})
    row.update(guard_ref="", guard_kind="", guard_maxres="")
    if a.ref:
        kind, maxres = guard_kind(a)
        rv, rap = load(a.ref); rv = to_grid(rv, a.ref_apix or rap, n, apix)
        avg = 0.5 * (h1 + h2)
        cf = shell_fsc(sfft.rfftn(avg * mask, workers=-1), sfft.rfftn(rv * mask, workers=-1), sf, nsh)
        at = {r: float(np.interp(1 / r, 1 / res[1:], cf[1:])) for r in XFSC_AT}   # 1/res increases with shell
        xc = cross(res, cf, 0.5)
        xtxt = "%.2f A" % xc
        if maxres:
            at = {r: (v if r >= maxres else float("nan")) for r, v in at.items()}
            if not (xc >= maxres):                          # NaN or beyond the trusted band
                xtxt = "not reached above the %.2f A cutoff" % maxres
        print("  cross-FSC vs " + a.ref.split("/")[-1] + " [%s%s]: " % (kind, ", only >= %.2f A" % maxres if maxres else "")
              + "  ".join(f"{r} A " + ("n/a" if v != v else f"{v:.3f}") for r, v in at.items())
              + "  | 0.5 crossing " + xtxt)
        if kind == "relion":
            print("  CAVEAT the guard map is RELION's reconstruction of the SAME particles: it shares their noise, so its "
                  "cross-FSC is only meaningful below the RELION resolution%s. Prefer an external map (EMDB entry of the "
                  "same complex, hand/pixel-matched) or a held-out-particle reconstruction as the guard."
                  % (" (%.2f A)" % maxres if maxres else " - cutoff UNKNOWN, set --ref-max-res"))
        row.update({"xfsc_%sA" % r: ("" if v != v else v) for r, v in at.items()})
        row.update(guard_ref=os.path.basename(a.ref), guard_kind=kind, guard_maxres=maxres or "")
    if a.csv:
        prev = append_csv(a.csv, row)
        if a.ref:
            guard_verdict(row, prev)


XFSC_AT = (20, 12, 8, 6.5)
FIELDS = ["label", "fsc05", "fsc0143", "fscrand_hi"] + ["xfsc_%sA" % r for r in XFSC_AT] + \
    ["guard_ref", "guard_kind", "guard_maxres"]


# NEEDS AUTHOR REVIEW: preferring an external guard map and cutting the RELION-map cross-FSC off at the RELION
# resolution is a scientific rule change proposed from one end-to-end test; the original author must approve it.
def guard_kind(a):
    """(kind, max_res) for the guard reference; see --ref-kind."""
    kind, maxres = a.ref_kind, a.ref_max_res
    looks_relion = bool(re.match(r"run_(it\d+_)?class\d+\.mrc$", os.path.basename(a.ref)))
    if kind is None:
        kind = "relion" if (looks_relion or maxres) else "external"
    if kind == "external":
        if looks_relion:
            print("  WARN --ref-kind external but %s looks like a RELION reconstruction of these particles"
                  % os.path.basename(a.ref))
        return kind, None
    if maxres is None:
        ms = os.path.join(os.path.dirname(os.path.abspath(a.ref)), "run_model.star")
        if os.path.exists(ms):
            for line in open(ms):
                if line.startswith("_rlnCurrentResolution"):
                    maxres = float(line.split()[1]); break
    return kind, maxres


def append_csv(path, row):
    """Append row with the fixed FIELDS header (an older file with fewer columns is rewritten); return previous rows."""
    old = list(csv.DictReader(open(path))) if os.path.exists(path) else []
    hdr = next(csv.reader(open(path)), []) if old else []
    mode = "a" if hdr == FIELDS else "w"
    with open(path, mode, newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if mode == "w":
            w.writeheader()
            for r in old:
                w.writerow({k: r.get(k, "") for k in FIELDS})
        w.writerow(row)
    return old


def guard_verdict(row, prev):
    same = [r for r in prev if r.get("guard_ref") == row["guard_ref"] and r.get("guard_kind") == row["guard_kind"]]
    if not same:
        print("  GUARD no earlier row measured against %s - this row is the baseline (re-measure iter0 with this "
              "reference before judging rounds)" % row["guard_ref"])
        return
    p = same[-1]; fell, rose = [], []
    for r in XFSC_AT:
        k = "xfsc_%sA" % r
        try:
            d = float(row[k]) - float(p[k])
        except (TypeError, ValueError):
            continue
        (fell if d < -0.01 else rose).append("%s A %+.3f" % (r, d))
    own = "own FSC0.143 %.2f -> %.2f A" % (float(p["fsc0143"]), float(row["fsc0143"]))
    if fell:
        print("  GUARD FELL vs %s (%s; cross-FSC %s) - overfitting signature: do not stack another round; "
              "review/revert" % (p["label"], own, ", ".join(fell + rose)))
    else:
        print("  GUARD ok vs %s (%s; cross-FSC %s)" % (p["label"], own, ", ".join(rose) or "no valid sample"))

if __name__ == "__main__":
    main()
