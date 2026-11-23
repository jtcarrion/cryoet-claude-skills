#!/usr/bin/env python3
"""Per-series status of a WarpTools tilt-series processing folder (or two folders side by side).

  python3 qc_summary.py <processing_folder> [--compare <other_folder>] [--csv out.csv] [--cs MM]

For each tilt-series XML: tilts used / total, CTF resolution estimate, mean defocus (um), Cs, AreAnglesInverted, unselected
flags, .xf present in tiltstack/, IMOD weighted-mean residual (align.log), tomogram present in reconstruction/.
Summary: counts, CTF-resolution median and range, hand consensus, series missing an alignment or a tomogram,
Cs not at nominal (refined Cs written back by an earlier MCore run), processed_items.json entry count.
Nominal Cs: --cs, else the config's MICROSCOPE_CS_MM, else the most common Cs across the folder's XMLs (stated).
With --compare: shows which series differ in geometry (AxisOffset / Angles) - a "variant" with zero geometry change was
never really re-aligned (wrong --variant downstream, or the import did not apply).
Notes: CTF resolution tracks ice/lamella thickness more than alignment quality; IMOD residuals are comparable only
WITHIN one alignment method (different point counts and fit variables make cross-method residuals meaningless).
"""
import argparse, glob, json, os, re, statistics, sys
import xml.etree.ElementTree as ET
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))


def nominal_cs(cli, series):
    """CLI > config MICROSCOPE_CS_MM > modal Cs of the XMLs. Returns (value or None, source)."""
    if cli is not None:
        return cli, "--cs"
    try:
        import cryoet_config as cc
        v = cc.cs_mm(cc.load())
        if v is not None:
            return v, "config MICROSCOPE_CS_MM"
    except (SystemExit, Exception):   # no config / no lib: fall through to the data
        pass
    vals = [round(s["cs"], 3) for s in series if s.get("cs") == s.get("cs")]
    if vals:
        return Counter(vals).most_common(1)[0][0], "most common value in the XMLs"
    return None, "unknown"


def lines_of(root, tag):
    e = root.find(tag)
    return [x for x in (e.text or "").split()] if e is not None and e.text else []


def series_info(folder):
    out = {}
    for x in sorted(glob.glob(os.path.join(folder, "*.xml"))):
        name = os.path.splitext(os.path.basename(x))[0]
        try:
            r = ET.parse(x).getroot()
        except ET.ParseError:
            out[name] = {"error": "unparseable"}; continue
        if r.tag != "TiltSeries":
            continue
        use = lines_of(r, "UseTilt"); ang = lines_of(r, "Angles")
        ctf = {p.get("Name"): p.get("Value") for p in r.iter("Param")}
        resid = None
        al = os.path.join(folder, "tiltstack", name, "align.log")
        if os.path.exists(al):
            for line in open(al, errors="replace"):
                if "Residual error weighted mean" in line:
                    nums = re.findall(r"[-\d.]+", line); resid = float(nums[-1]) if nums else None; break
        recon = glob.glob(os.path.join(folder, "reconstruction", f"{name}_*.mrc"))
        # inherited M products: refinement grids and magnification correction (strip them for fair arm comparisons)
        mprod = {}
        for g in ("GridMovementX", "GridMovementY", "GridAngleX", "GridAngleY", "GridAngleZ",
                  "GridVolumeWarpX", "GridVolumeWarpY", "GridVolumeWarpZ"):
            e = r.find(g)
            if e is not None:
                vals = [abs(float(v)) for n_ in e.iter() for k, v in n_.attrib.items() if k == "Value"]
                if vals and max(vals) > 1e-6:
                    mprod[g] = max(vals)
        mag = [float(x) for x in (r.get("MagnificationCorrection") or "1,0,0,1").replace(" ", "").split(",")]
        magdev = max(abs(mag[0] - 1), abs(mag[1]), abs(mag[2]), abs(mag[3] - 1)) if len(mag) == 4 else 0.0
        out[name] = dict(
            tilts_used=sum(1 for u in use if u == "True"), tilts=len(use),
            ctf_res=float(r.get("CTFResolutionEstimate", "nan") or "nan"),
            defocus=float(ctf.get("Defocus", "nan")), cs=float(ctf.get("Cs", "nan")),
            inverted=r.get("AreAnglesInverted"), unselected=(r.get("UnselectFilter") == "True" or r.get("UnselectManual") == "True"),
            xf=os.path.exists(os.path.join(folder, "tiltstack", name, f"{name}.xf")), resid=resid,
            tomo=bool([f for f in recon if "half" not in os.path.basename(f) and "deconv" not in os.path.basename(f)]),
            offx=lines_of(r, "AxisOffsetX"), angles=ang, mprod=mprod, magdev=magdev)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder"); ap.add_argument("--compare"); ap.add_argument("--csv")
    ap.add_argument("--cs", type=float, help="nominal Cs in mm (default: config MICROSCOPE_CS_MM, else modal XML value)")
    a = ap.parse_args()
    S = series_info(a.folder)
    if not S:
        sys.exit(f"no TiltSeries XMLs in {a.folder}")
    print(f"{a.folder}: {len(S)} tilt series")
    print(f"{'series':<14}{'tilts':>9}{'CTF A':>8}{'defocus':>9}{'Cs':>6}{'inv':>6}{'xf':>4}{'resid nm':>9}{'tomo':>6}")
    for n, s in S.items():
        if "error" in s:
            print(f"{n:<14} {s['error']}"); continue
        print(f"{n:<14}{s['tilts_used']:>4}/{s['tilts']:<4}{s['ctf_res']:>8.1f}{s['defocus']:>9.2f}{s['cs']:>6.2f}"
              f"{str(s['inverted'])[:5]:>6}{'y' if s['xf'] else '-':>4}{(s['resid'] if s['resid'] is not None else float('nan')):>9.2f}"
              f"{'y' if s['tomo'] else '-':>6}{'  UNSELECTED' if s['unselected'] else ''}")
    ok = [s for s in S.values() if "error" not in s]
    res = [s["ctf_res"] for s in ok if s["ctf_res"] == s["ctf_res"]]
    if res:
        print(f"CTF resolution estimate: median {statistics.median(res):.2f} A, range {min(res):.2f}-{max(res):.2f} ({len(res)} series)")
    print(f"AreAnglesInverted: {dict((v, sum(1 for s in ok if s['inverted'] == v)) for v in set(s['inverted'] for s in ok))}")
    rr = [s["resid"] for s in ok if s["resid"] is not None]
    if rr:
        print(f"IMOD residual (nm): median {statistics.median(rr):.2f}, max {max(rr):.2f}; >2x median: "
              f"{[n for n, s in S.items() if s.get('resid') and s['resid'] > 2 * statistics.median(rr)][:15]}")
    noxf = [n for n, s in S.items() if s.get("xf") is False]; notomo = [n for n, s in S.items() if s.get("tomo") is False]
    cs0, cs_src = nominal_cs(a.cs, ok)
    badcs = [n for n, s in S.items() if cs0 is not None and s.get("cs") == s.get("cs") and abs(s["cs"] - cs0) > 0.01]
    if noxf: print(f"no .xf ({len(noxf)}): {noxf[:20]}")
    if notomo: print(f"no tomogram ({len(notomo)}): {notomo[:20]}")
    if cs0 is not None:
        print(f"nominal Cs {cs0} mm ({cs_src})")
    if badcs: print(f"WARN Cs != {cs0} in {len(badcs)} series (refined Cs from an MCore run leaked into this folder?): {badcs[:10]}")
    withm = {g: sum(1 for s in ok if g in s["mprod"]) for g in ("GridMovementX", "GridAngleX", "GridVolumeWarpX")}
    magn = sum(1 for s in ok if s["magdev"] > 1e-4)
    if any(withm.values()) or magn:
        print(f"NOTE inherited M products (non-zero): image warp in {withm['GridMovementX']}, stage angles in "
              f"{withm['GridAngleX']}, volume warp in {withm['GridVolumeWarpX']}, magnification != identity in {magn} series "
              f"(max dev {max((s['magdev'] for s in ok), default=0):.4f}). Arms compared against each other must carry or strip "
              "these identically; a fresh alignment arm has none.")
    pij = os.path.join(a.folder, "processed_items.json")
    if os.path.exists(pij):
        try:
            print(f"processed_items.json: {len(json.load(open(pij)))} entries")
        except Exception as e:
            print(f"processed_items.json unreadable: {e}")
    if a.compare:
        T = series_info(a.compare); same = diff = 0; changed = []
        for n in sorted(set(S) & set(T)):
            if S[n].get("offx") == T[n].get("offx") and S[n].get("angles") == T[n].get("angles"):
                same += 1
            else:
                diff += 1; changed.append(n)
        print(f"--compare {a.compare}: {diff} series differ in geometry, {same} identical")
        if diff == 0:
            print("WARN no geometry difference at all: this 'variant' was never re-aligned (check --variant / import)")
    if a.csv:
        with open(a.csv, "w") as f:
            f.write("series,tilts_used,tilts,ctf_res,defocus,cs,inverted,unselected,xf,resid_nm,tomogram\n")
            for n, s in S.items():
                if "error" not in s:
                    f.write(f"{n},{s['tilts_used']},{s['tilts']},{s['ctf_res']},{s['defocus']},{s['cs']},{s['inverted']},"
                            f"{s['unselected']},{s['xf']},{s['resid']},{s['tomo']}\n")


if __name__ == "__main__":
    main()
