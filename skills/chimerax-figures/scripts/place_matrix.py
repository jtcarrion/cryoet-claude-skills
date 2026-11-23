#!/usr/bin/env python3
"""Flip a map into the reference hand WITHOUT resampling and compute its exact ChimeraX placement, with gates.

Input: a docking transform in a JSON file (no docking tool is shipped; any rigid-body search works - see
references/multimap.md):
    {"A": [[a11,a12,a13],[a21,a22,a23],[a31,a32,a33]], "b_A": [b1,b2,b3]}      (key names: --A-key / --b-key)
    meaning  x_ref = A . x_mov + b   for physical coordinates in Angstrom, CENTRED on each box (centre = n * pixel / 2),
    in numpy (z, y, x) order. A is 3x3 and may include a mirror (det -1) when the maps are of opposite hand.
HAND FLIP CONVENTION (this script): if det(A) < 0 the moving map is mirrored along Z = numpy array axis 0 (the MRC
section axis; same axis as ChimeraX's `volume flip` default). Voxels are only reordered (mov[::-1]); any map that must
stay registered with it (local-resolution map, mask) gets the same flip via --also. A mirror along x or y would be an
equally valid hand flip, but the matrix below is derived for z: do not mix conventions within one bundle.
    A_x = P A P, b_x = P b  (P swaps x and z);  R = A_x . Fz  (Fz = diag(1,1,-1) when flipped, else identity)
    t = A_x (e - c_mov) + b_x + c_ref,  e = (0,0,(n_mov-1) a_mov) when flipped else 0,  c = n * pixel / 2
Gates (nothing is written if any fails):
  geometry     det(R) = +1 and orthonormal to 1e-6 (never overridable).
  correlation  the moving map sampled through exactly that matrix onto the reference grid, both maps Gaussian-low-passed
               to ONE common resolution (--lowpass; default = the coarser of --ref-res / --mov-res, else 10 A), inside
               the reference mask if given, must beat its CONTROLS by a margin, not an absolute number:
                 shift  the same placement shifted by +-d along x, y, z (d = --control-shift, default lowpass / 2):
                        cc - max(cc_shift) >= --min-margin-shift (0.05) -> the placement is a sharp optimum;
                 hand   the same matrix applied to the moving map WITHOUT (or, if det(A) > 0, WITH) the z flip:
                        cc - cc_hand >= --min-margin-hand (0.10) -> the flip and the matrix belong together.
               plus a sanity floor cc >= --min-cc (0.30). Why margins: maps of different resolution, processing or
               hand (a mirrored EMDB map vs a 7 A in-cell map) correlate well below 0.9 even when the placement is
               exact (seen: 0.76 at full resolution, 0.82 at an 8 A common low-pass, one-voxel shifts 0.65-0.67,
               unmirrored 0.16), so a fixed 0.90 rejects correct placements while a margin over controls still
               catches a wrong one. The hand control checks the flip convention only - it does NOT decide which hand
               is correct (re-docking the mirror image fits almost as well; decide hand against an atomic model).
  --force      write even when the correlation gate fails (say so in the figure notes); also overwrites outputs.
Requires cubic boxes and isotropic pixels, and bundle maps with origin 0 (set_origin.py).

  "$CRYOET_PYTHON" place_matrix.py --ref ref.mrc --mov mov.mrc --dock dock.json [--ref-mask m.mrc]
        [--ref-res 7.3 --mov-res 9.0 | --lowpass 9] [--also mov_locres.mrc mov_mask.mrc] [--shift-x 400]
        [--outdir bundle/maps] [--json placement.json] [--force]
--also: maps on the moving map's grid that get the SAME flip. --shift-x adds a side-by-side offset (A) to t_x.
Output: flipped maps (*_zflip.mrc, origin 0) and the 12 numbers for  view matrix models #N,....  Nested children
(#N.5) follow their parent automatically - do not give them their own matrix.
MEMORY: the CC gate maps the full reference grid twice (map + hand control; spline prefilter and complex FFTs, ~40 x
box^3 bytes; box 438 ~ 3.5 GB, box 600 ~ 9 GB) - run it on a compute node or workstation, not a shared login node.
"""
import argparse, json, os, sys

np = mrcfile = ndimage = None     # imported in main() so --help works without them
FORCE = False


def load(p):
    with mrcfile.open(p, permissive=True) as m:
        return np.asarray(m.data, np.float32), float(m.voxel_size.x)


def write(p, arr, apix):
    with mrcfile.new(p, overwrite=FORCE) as o:
        o.set_data(arr.astype(np.float32)); o.voxel_size = apix
        o.header.origin = (0.0, 0.0, 0.0); o.header.nxstart = o.header.nystart = o.header.nzstart = 0


def freqs(shape, apix):
    k = [np.fft.fftfreq(n, d=apix) for n in shape]
    return k[0][:, None, None], k[1][None, :, None], k[2][None, None, :]


def lowpass_ft(v, apix, res):
    """Fourier transform of v, Gaussian-low-passed so the amplitude at 1/res is exp(-1/2)."""
    kz, ky, kx = freqs(v.shape, apix)
    return np.fft.fftn(v) * np.exp(-((kz ** 2 + ky ** 2 + kx ** 2) * res ** 2) / 2)


def corr(x, y, m):
    return float(np.corrcoef(x[m], y[m])[0, 1])


def correlation_gate(ref, movR, movH, m, apix, res, dshift):
    """cc of the placed map, of +-dshift (A) shifted copies along x, y, z and of the other-hand control, all on one
    common low-pass. Shifts are Fourier phase ramps (circular; fine for maps padded with solvent)."""
    x = np.real(np.fft.ifftn(lowpass_ft(ref, apix, res)))
    F = lowpass_ft(movR, apix, res)
    cc = corr(x, np.real(np.fft.ifftn(F)), m)
    kz, ky, kx = freqs(ref.shape, apix)
    shifts = {}
    for name, kax in (("x", kx), ("y", ky), ("z", kz)):
        for sg in (1, -1):
            ys = np.real(np.fft.ifftn(F * np.exp(-2j * np.pi * kax * sg * dshift)))
            shifts["%s%+g" % (name, sg * dshift)] = corr(x, ys, m)
    cc_hand = corr(x, np.real(np.fft.ifftn(lowpass_ft(movH, apix, res))), m)
    return cc, shifts, cc_hand


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ref", required=True); ap.add_argument("--mov", required=True); ap.add_argument("--dock", required=True)
    ap.add_argument("--ref-mask"); ap.add_argument("--also", nargs="*", default=[])
    ap.add_argument("--A-key", default="A"); ap.add_argument("--b-key", default="b_A")
    ap.add_argument("--ref-apix", type=float, help="nominal reference pixel (e.g. 2.25 when the header says 2.2526)")
    ap.add_argument("--shift-x", type=float, default=0.0)
    ap.add_argument("--ref-res", type=float, help="reference map resolution (A); sets the default common low-pass")
    ap.add_argument("--mov-res", type=float, help="moving map resolution (A); sets the default common low-pass")
    ap.add_argument("--lowpass", type=float, help="common low-pass (A) for the gate (default: coarser of the two "
                    "resolutions, else 10)")
    ap.add_argument("--control-shift", type=float, help="shift-control distance (A; default lowpass / 2)")
    ap.add_argument("--min-margin-shift", type=float, default=0.05, help="cc must beat every shifted control by this")
    ap.add_argument("--min-margin-hand", type=float, default=0.10, help="cc must beat the other-hand control by this")
    ap.add_argument("--min-cc", type=float, default=0.30, help="sanity floor on cc (NOT the main criterion)")
    ap.add_argument("--outdir"); ap.add_argument("--json")
    ap.add_argument("--force", action="store_true",
                    help="write even if the correlation gate fails (geometry gates still apply); overwrite outputs")
    a = ap.parse_args()
    global np, mrcfile, ndimage, FORCE
    import numpy as np, mrcfile
    from scipy import ndimage
    FORCE = a.force
    P = np.array([[0, 0, 1], [0, 1, 0], [1, 0, 0]], float)
    d = json.load(open(a.dock)); Az = np.array(d[a.A_key], float); bz = np.array(d[a.b_key], float)
    ref, aR = load(a.ref); aR = a.ref_apix or aR; mov, aM = load(a.mov); nR, nM = ref.shape[0], mov.shape[0]
    for nm, v in (("ref", ref), ("mov", mov)):
        if not (v.shape[0] == v.shape[1] == v.shape[2]):
            sys.exit("%s map %s is not cubic; this script assumes cubic boxes" % (nm, v.shape))
    flip = np.linalg.det(Az) < 0
    movf = mov[::-1].copy() if flip else mov
    Ax, bx = P @ Az @ P, P @ bz
    Fz = np.diag([1.0, 1.0, -1.0]) if flip else np.eye(3)
    R = Ax @ Fz
    e = np.array([0.0, 0.0, (nM - 1) * aM]) if flip else np.zeros(3)
    t = Ax @ (e - np.full(3, nM * aM / 2)) + bx + np.full(3, nR * aR / 2)
    det = float(np.linalg.det(R)); orth = float(np.abs(R @ R.T - np.eye(3)).max())
    q = np.indices(ref.shape, dtype=np.float32)
    uR = np.stack([q[2], q[1], q[0]], 0).reshape(3, -1) * aR
    uM = np.linalg.solve(R, uR - t[:, None])
    idx = (uM / aM)[::-1].reshape((3,) + ref.shape)
    movR = ndimage.map_coordinates(movf, idx, order=3, mode="constant", cval=0.0)
    movH = ndimage.map_coordinates(mov if flip else mov[::-1].copy(), idx, order=3, mode="constant", cval=0.0)
    del idx, uM, uR, q
    m = (np.asarray(mrcfile.read(a.ref_mask), np.float32) > 0.5) if a.ref_mask else np.ones(ref.shape, bool)
    given = [r for r in (a.ref_res, a.mov_res) if r]
    res = a.lowpass or (max(given) if given else 10.0)
    dsh = a.control_shift or res / 2.0
    cc, shifts, cc_hand = correlation_gate(ref, movR, movH, m, aR, res, dsh)
    m_shift, m_hand = cc - max(shifts.values()), cc - cc_hand
    t_out = t + np.array([a.shift_x, 0, 0])
    mat = [R[0, 0], R[0, 1], R[0, 2], t_out[0], R[1, 0], R[1, 1], R[1, 2], t_out[1], R[2, 0], R[2, 1], R[2, 2], t_out[2]]
    geo_ok = abs(det - 1) < 1e-6 and orth < 1e-6
    cc_ok = cc >= a.min_cc and m_shift >= a.min_margin_shift and m_hand >= a.min_margin_hand
    rep = dict(flipped_z=bool(flip), det=det, orthonormality_error=orth,
               lowpass_A=res, lowpass_source="--lowpass" if a.lowpass else ("coarser map resolution" if given
                                                                            else "default 10 A (give --ref-res/--mov-res)"),
               cc=cc, cc_shift_controls=shifts, control_shift_A=dsh, cc_other_hand=cc_hand,
               margin_shift=m_shift, margin_hand=m_hand,
               gate=dict(geometry=bool(geo_ok), correlation=bool(cc_ok), min_cc=a.min_cc,
                         min_margin_shift=a.min_margin_shift, min_margin_hand=a.min_margin_hand, forced=bool(a.force)),
               matrix=[float(v) for v in mat],
               view_matrix="view matrix models #N," + ",".join(f"{v:.8f}" for v in mat))
    print(json.dumps(rep, indent=1))
    if not geo_ok:
        sys.exit("GEOMETRY GATE FAILED (det/orthonormality) - nothing written (check dock convention)")
    if not cc_ok:
        msg = ("CORRELATION GATE FAILED: cc %.3f, margin over shifted controls %.3f (need %.2f), over the other hand %.3f "
               "(need %.2f), floor %.2f - check dock direction / hand / pixel sizes / --lowpass"
               % (cc, m_shift, a.min_margin_shift, m_hand, a.min_margin_hand, a.min_cc))
        if not a.force:
            sys.exit(msg + " - nothing written (--force to write anyway)")
        print("WARNING " + msg + " - writing anyway (--force); state this in the figure notes", file=sys.stderr)
    if a.outdir:
        os.makedirs(a.outdir, exist_ok=True)
        for p in [a.mov] + a.also:
            v, ap_ = load(p)
            if v.shape != mov.shape:
                sys.exit(f"{p} is not on the moving map's grid")
            stem, ext = os.path.splitext(os.path.basename(p))
            name = stem + ("_zflip" if flip else "") + (ext or ".mrc")
            write(os.path.join(a.outdir, name), v[::-1] if flip else v, ap_)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1)


if __name__ == "__main__":
    main()
