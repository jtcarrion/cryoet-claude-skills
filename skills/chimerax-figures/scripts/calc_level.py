#!/usr/bin/env python3
"""Contour levels for ChimeraX figures, computed without ChimeraX. Pick ONE rule per figure; the SAME rule for every
map in a comparison. Every result also reports the volume the level encloses, for the .cxc header.

Rules
  (none)            3D-CNN level per map (calc_level_ChimeraX, Kinman, Carreira et al. 2024,
                    https://github.com/mariacarreira/calc_level_ChimeraX, AGPL-3.0). Needs CALC_LEVEL_REPO (a clone
                    with weights.tar.gz extracted) and torch. If it is not configured the script stops and tells you
                    to use --mw / --volume instead.
  --match-volume    the first map's CNN level (or --ref-level) defines an enclosed volume; every map gets the level
                    enclosing that same volume on its own grid. Use for side-by-side comparisons.
  --mw KDA          level enclosing KDA * 1000 * 1.21 A^3 (protein/RNA density ~0.83 Da/A^3). 70S ribosome ~2500 kDa.
  --volume A3       level enclosing A3 cubic angstroms.
  --ligand-median MODEL --ligand RES   0.8 x median map value at the ligand's heavy atoms (close-up mesh, needs gemmi).

  "$CRYOET_PYTHON" calc_level.py map1.mrc [map2.mrc ...] [--mw 2500 | --volume 3e6 | --match-volume] [--json out.json]
Needs numpy + mrcfile (+ torch for the CNN, gemmi + scipy for --ligand-median). The CNN Fourier-crops each map to
64^3 (memory ~16 x box^3 bytes, e.g. ~2 GB at box 512: not on a login node for big boxes); it uses a GPU if torch sees
one, else CPU (seconds per map). Non-cubic maps are refused by the CNN path (use --mw/--volume).
The CNN file is loaded WITHOUT editing it: its last line registers a ChimeraX command and needs a ChimeraX session,
so that one line is dropped at load time, and calc_level_dev() must exist (checked; tested against upstream cf1d29b).
"""
import argparse
import json
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
np = mrcfile = None   # imported in main() so that --help works without numpy

A3_PER_DA = 1.21


def cfg_value(key):
    if os.environ.get(key):
        return os.environ[key]
    try:
        import cryoet_config as cc
        return cc.load().get(key, "")
    except (SystemExit, Exception):
        return ""


def load_map(p, apix=None):
    with mrcfile.open(p, permissive=True) as m:
        return np.asarray(m.data, np.float32), float(apix or m.voxel_size.x)


def map_origin_xyz(p):
    """Physical position (A, x,y,z) of voxel (0,0,0), the way ChimeraX places an MRC: header origin, else nstart*pixel."""
    with mrcfile.open(p, permissive=True, header_only=True) as m:
        h = m.header; apix = float(m.voxel_size.x)
        o = np.array([float(h.origin.x), float(h.origin.y), float(h.origin.z)])
        if not o.any():
            o = np.array([int(h.nxstart), int(h.nystart), int(h.nzstart)], float) * apix
    return o


def repo_commit(repo):
    try:
        head = open(os.path.join(repo, ".git", "HEAD")).read().strip()
        if head.startswith("ref:"):
            return open(os.path.join(repo, ".git", head.split()[1])).read().strip()[:12]
        return head[:12]
    except OSError:
        return "unknown"


def cnn_module(repo):
    src = os.path.join(repo, "calc_level.py")
    if not os.path.isfile(src):
        sys.exit("CALC_LEVEL_REPO=%s has no calc_level.py (git clone "
                 "https://github.com/mariacarreira/calc_level_ChimeraX)" % repo)
    if not os.path.isfile(os.path.join(repo, "weights_5e6.pth")):
        sys.exit("CNN weights missing: cd %s && tar -xzf weights.tar.gz" % repo)
    try:
        import torch  # noqa: F401
    except ImportError:
        sys.exit("the CNN needs torch in this python (%s); or use --mw / --volume" % sys.executable)
    lines = [l for l in open(src).read().splitlines() if l.strip() != "register_command(session)"]
    mod = types.ModuleType("calc_level_cnn"); mod.__file__ = src
    exec(compile("\n".join(lines), src, "exec"), mod.__dict__)
    if not callable(getattr(mod, "calc_level_dev", None)):
        sys.exit("%s has no calc_level_dev(); upstream changed - pin a known commit or use --mw / --volume" % src)
    return mod


def enclosed(v, apix, level):
    return float((v >= level).sum() * apix ** 3)


def level_for_volume(v, apix, vol):
    s = np.sort(v.ravel())[::-1]
    return float(s[min(int(round(vol / apix ** 3)), s.size - 1)])


def ligand_median(v, apix, model, resname, origin):
    import gemmi
    from scipy import ndimage
    st = gemmi.read_structure(model)
    xyz = np.array([a.pos.tolist() for ch in st[0] for r in ch if r.name == resname for a in r
                    if a.element.name != "H"])
    if xyz.size == 0:
        sys.exit("no heavy atoms of residue %s in %s" % (resname, model))
    idx = ((xyz - origin)[:, ::-1] / apix).T          # model x,y,z (A) -> array z,y,x indices, honouring the origin
    vals = ndimage.map_coordinates(v, idx, order=1, mode="nearest")
    return float(np.median(vals)), int(len(xyz))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("maps", nargs="+")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--volume", type=float, metavar="A3")
    g.add_argument("--mw", type=float, metavar="KDA", help="molecular weight in kDa")
    g.add_argument("--ligand-median", metavar="MODEL")
    ap.add_argument("--match-volume", action="store_true")
    ap.add_argument("--ref-level", type=float, help="with --match-volume and no CNN: level on the FIRST map")
    ap.add_argument("--ligand", help="ligand residue name for --ligand-median (e.g. ATP)")
    ap.add_argument("--ligand-fraction", type=float, default=0.8)
    ap.add_argument("--apix", type=float, help="nominal pixel size if the header differs (e.g. 2.25 vs 2.2526)")
    ap.add_argument("--repo", help="calc_level_ChimeraX clone (default: CALC_LEVEL_REPO)")
    ap.add_argument("--json")
    a = ap.parse_args()
    global np, mrcfile
    import numpy as np
    import mrcfile
    if a.match_volume and (a.volume or a.mw or a.ligand_median):
        ap.error("--match-volume is for the CNN / --ref-level rule; --mw/--volume already give every map the same volume")

    out = {"rule": None, "rule_kind": None, "maps": {}}
    data = {p: load_map(p, a.apix) for p in a.maps}
    if a.volume or a.mw:
        if a.mw and a.mw > 5e4:
            print("note: --mw is in kDa; %.4g kDa = %.4g MDa. Check this is not a value in Da." % (a.mw, a.mw / 1e3),
                  file=sys.stderr)
        vol = a.volume or a.mw * 1e3 * A3_PER_DA
        out["rule_kind"] = "mw" if a.mw else "volume"
        out["rule"] = "enclosed volume %.4g A^3" % vol + (" (MW %.4g kDa x %.2f A^3/Da)" % (a.mw, A3_PER_DA) if a.mw else "")
        for p, (v, apix) in data.items():
            lev = level_for_volume(v, apix, vol)
            out["maps"][p] = dict(level=lev, apix=apix, enclosed_A3=enclosed(v, apix, lev))
    elif a.ligand_median:
        if not a.ligand:
            sys.exit("--ligand-median needs --ligand RESNAME")
        out["rule_kind"] = "ligand_median"
        out["rule"] = "%g x median map value at %s heavy atoms of %s" % (a.ligand_fraction, a.ligand,
                                                                         os.path.basename(a.ligand_median))
        for p, (v, apix) in data.items():
            med, n = ligand_median(v, apix, a.ligand_median, a.ligand, map_origin_xyz(p))
            lev = a.ligand_fraction * med
            out["maps"][p] = dict(level=lev, apix=apix, ligand_median=med, ligand_atoms=n,
                                  enclosed_A3=enclosed(v, apix, lev))
    elif a.match_volume and a.ref_level is not None:
        first = a.maps[0]; v0, ap0 = data[first]; ref_vol = enclosed(v0, ap0, a.ref_level)
        out.update(rule_kind="match_volume_ref_level", reference_map=first,
                   rule="level %g on %s -> same enclosed volume (%.4g A^3) for every map" % (a.ref_level, first, ref_vol))
        for p, (v, apix) in data.items():
            lev = a.ref_level if p == first else level_for_volume(v, apix, ref_vol)
            out["maps"][p] = dict(level=lev, apix=apix, enclosed_A3=enclosed(v, apix, lev))
    else:
        repo = a.repo or cfg_value("CALC_LEVEL_REPO")
        if not repo or not os.path.isdir(repo):
            sys.exit("CNN not available: CALC_LEVEL_REPO is %s. Clone https://github.com/mariacarreira/"
                     "calc_level_ChimeraX (and tar -xzf weights.tar.gz) and set CALC_LEVEL_REPO, or use a rule that "
                     "needs no CNN: --mw KDA, --volume A3, or --match-volume --ref-level L. (Users with ChimeraX can "
                     "also run its 'volume calc_level #1' command locally and pass that as --ref-level.)"
                     % ("unset" if not repo else "not a directory (%s)" % repo))
        mod = cnn_module(repo)
        ref_vol = None
        out["cnn_repo_commit"] = repo_commit(repo)
        for p, (v, apix) in data.items():
            if not (v.shape[0] == v.shape[1] == v.shape[2]):
                sys.exit("%s: box %s is not cubic; the CNN needs a cube - use --mw/--volume instead" % (p, v.shape))
            cnn = float(np.asarray(mod.calc_level_dev(v)).ravel()[0])
            rec = dict(cnn_level=cnn, apix=apix, cnn_enclosed_A3=enclosed(v, apix, cnn))
            if a.match_volume:
                if ref_vol is None:
                    ref_vol = rec["cnn_enclosed_A3"]; out["reference_map"] = p
                rec["level"] = level_for_volume(v, apix, ref_vol); rec["enclosed_A3"] = enclosed(v, apix, rec["level"])
            else:
                rec["level"] = cnn; rec["enclosed_A3"] = rec["cnn_enclosed_A3"]
            out["maps"][p] = rec
        out["rule_kind"] = "cnn_match_volume" if a.match_volume else "cnn"
        out["rule"] = ("CNN level of the reference map -> same enclosed volume for every map" if a.match_volume
                       else "3D-CNN level per map (calc_level_ChimeraX %s)" % out["cnn_repo_commit"])
    print(json.dumps(out, indent=1))
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
