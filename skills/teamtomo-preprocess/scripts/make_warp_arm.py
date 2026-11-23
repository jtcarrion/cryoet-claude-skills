#!/usr/bin/env python3
"""OPTIONAL hand-off: turn a tsa_to_tomograms output root into a WarpTools processing folder (an alignment "arm"),
plus (recommended) a matched control arm with the ORIGINAL alignment cleaned identically. Only when the user asks.

  python make_warp_arm.py --root <project>/teamtomo/tsa_to_tomograms_<tag> --dest <project>/<arm name>
                          --clean-template <folder of the same series' XMLs with nominal Cs and no odd Zernikes>
                          [--control-dest <project>/<arm name>_ctrl] [--cs MM] [--series a b ...] [--dry-run]

How the arm XML is made: teamtomo's <series>.xml is the input XML with only Angles, AxisAngle and AxisOffsetX/Y
replaced (teamtomo_workflows/warp_xml.py) - everything else is the input's, including prior-M products. So this
script GRAFTS just those four fields onto a copy of the CLEAN template XML of the same series, then neutralises what
is frame-locked to the old alignment or left over from M:
  * GridMovementX/Y, GridAngleX/Y/Z, GridVolumeWarpX/Y/Z -> all nodes 0   (frame-locked to the old alignment;
    carried across alignments they make the map much WORSE, not slightly)
  * MagnificationCorrection -> identity 1, 0, 0, 1                        (an M refinement product)
  * Cs and odd Zernikes are REPORTED; the template must already be clean (Cs == nominal, odd Zernikes 0) - refused
    otherwise. Nominal Cs = --cs, else the source project's warp_tiltseries.settings, else MICROSCOPE_CS_MM from the
    cryoet-skills config; if none is known the Cs check is skipped with a warning (odd Zernikes are still checked).
The control arm (--control-dest) = the same clean template with the SAME neutralisation and its own alignment, so the
two arms differ ONLY in Angles/AxisAngle/AxisOffset (verified and printed). Without it a production folder keeps the
M image-warp benefit the TSA arm cannot have, and the comparison is unfair.
Without --clean-template the TSA XML itself is the template (grids/mag still neutralised; Cs/Zernikes only reported).

Checks: tilt count of the TSA XML == template; per-series axis-angle and nominal-vs-refined tilt-angle offset printed.
TSA keeps NOMINAL tilt angles (eTomo/AreTomo may refine a tilt offset of several degrees) -> the 3D frames differ and
particle COORDINATES do not carry over between the arms; transfer them through the projection model or re-pick.
Next (warptools-preprocess, same --variant per arm, both arms identically): ts_defocus_hand --check (TeamTomo cannot
decide the hand; settle it BEFORE ts_ctf) -> ts_ctf (MANDATORY after a new alignment) -> ts_reconstruct -> export ->
relion-refine; rank arms by downstream STA resolution.
"""
import argparse, json, os, re, shutil, sys, xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))

GEOM_GRIDS = ("GridMovementX", "GridMovementY", "GridAngleX", "GridAngleY", "GridAngleZ",
              "GridVolumeWarpX", "GridVolumeWarpY", "GridVolumeWarpZ")
ALIGN = ("Angles", "AxisAngle", "AxisOffsetX", "AxisOffsetY")
PROTECTED_NAMES = ("warp_tiltseries", "warp_frameseries", "tomostar")


def nominal_cs(cli, warp_project):
    """CLI > <warp project>/warp_tiltseries.settings Cs > config MICROSCOPE_CS_MM > None. Returns (value, source)."""
    if cli is not None:
        return cli, "--cs"
    if warp_project:
        st = Path(warp_project) / "warp_tiltseries.settings"
        if st.exists():
            m = re.search(r'Name="Cs"\s+Value="([^"]+)"', st.read_text())
            if m:
                return float(m.group(1)), str(st)
    try:
        import cryoet_config as cc
        v = cc.cs_mm(cc.load())
        if v is not None:
            return v, "config MICROSCOPE_CS_MM"
    except SystemExit:
        pass
    return None, None


def need(el, tag, where):
    """el.find(tag) or a clear error (instead of AttributeError on .text)."""
    x = el.find(tag)
    if x is None:
        sys.exit(f"{where}: XML has no <{tag}> element - not a Warp 2 tilt-series XML, or a different schema")
    return x


def nums(el):
    return [float(v) for v in (el.text or "").replace(",", " ").split()] if el is not None else []


def ctf_state(root):
    cs, odd = None, False
    ctf = root.find("CTF")
    for p in (ctf.iter("Param") if ctf is not None else []):
        if p.get("Name") == "Cs":
            cs = float(p.get("Value"))
        if p.get("Name") == "ZernikeCoeffsOdd" and any(abs(float(v)) > 0 for v in (p.get("Value") or "").replace(";", " ").split()):
            odd = True
    return cs, odd


def neutralise(root):
    n = 0
    for g in GEOM_GRIDS:
        el = root.find(g)
        for node in (el.iter("Node") if el is not None else []):
            if float(node.get("Value", 0)) != 0:
                n += 1
            node.set("Value", "0")
    mag = root.get("MagnificationCorrection")
    if mag is not None:
        root.set("MagnificationCorrection", "1, 0, 0, 1")
    return n, mag


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True); ap.add_argument("--dest", required=True)
    ap.add_argument("--clean-template"); ap.add_argument("--control-dest")
    ap.add_argument("--cs", type=float, help="nominal Cs in mm for the clean-template check (default: from the source "
                    "project's warp_tiltseries.settings, else MICROSCOPE_CS_MM)")
    ap.add_argument("--series", nargs="+"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    root = Path(a.root).resolve(); dests = [Path(a.dest).resolve()] + ([Path(a.control_dest).resolve()] if a.control_dest else [])
    tmpl = Path(a.clean_template).resolve() if a.clean_template else None
    if a.control_dest and not tmpl:
        sys.exit("--control-dest needs --clean-template (the control is the clean template with its own alignment)")
    for d in dests:
        if any(p.startswith(PROTECTED_NAMES) for p in d.parts) or d == root or root in d.parents:
            sys.exit(f"REFUSING destination {d} (inside a Warp processing folder or the teamtomo output root)")
        if d.exists():
            sys.exit(f"REFUSING: {d} exists (no-overwrite; pick a new arm name)")
    picked, skipped = [], []
    for rj in sorted(root.glob("*/run.json")):
        r = json.loads(rj.read_text()); s = r.get("series", rj.parent.name)
        if a.series and s not in a.series:
            continue
        if r.get("workflow") != "tsa_to_tomograms":
            sys.exit(f"{s}: workflow {r.get('workflow')} - only tsa_to_tomograms writes a new alignment")
        (picked if r.get("status") == "done" and (rj.parent / f"{s}.xml").exists() else skipped).append(s)
    if not picked:
        sys.exit("no finished series with a written Warp XML")
    wp = json.loads((root / picked[0] / "run.json").read_text())["config"]["input"].get("warp_project")
    src_proc = Path(wp) / "warp_tiltseries" if wp else None
    cs_nom, cs_src = nominal_cs(a.cs, wp)
    print(f"nominal Cs: {cs_nom} mm ({cs_src})" if cs_nom is not None else
          "WARNING: nominal Cs unknown (no --cs, no settings Cs, no MICROSCOPE_CS_MM) - template Cs is reported, not checked")
    print(f"arm {dests[0]}: {len(picked)} series" + (f"; skipped (not done): {skipped}" if skipped else "")
          + (f"; template {tmpl}" if tmpl else "; template = TSA XML itself (no --clean-template)"))
    out = {d: {} for d in dests}; audit = {}
    for s in picked:
        tsa = ET.parse(root / s / f"{s}.xml").getroot()
        if tmpl:
            if not (tmpl / f"{s}.xml").exists():
                sys.exit(f"{s}: not in the clean template folder {tmpl}")
            base = ET.parse(tmpl / f"{s}.xml").getroot()
            cs, odd = ctf_state(base)
            if (cs is not None and cs_nom is not None and abs(cs - cs_nom) > 0.01) or odd:
                sys.exit(f"{s}: --clean-template is not clean (Cs {cs} vs nominal {cs_nom}, odd Zernikes {odd}) - make a "
                         "clean copy with scripts/_lib/reset_ctf_cs.py <XMLs> --out_dir <copy> --zero_zernike_odd")
            nb, nt = len(nums(need(base, "Angles", f"template {s}"))), len(nums(need(tsa, "Angles", f"TSA {s}")))
            if nb != nt:
                sys.exit(f"{s}: tilt count differs (template {nb} vs TSA {nt})")
            arm = ET.fromstring(ET.tostring(base))
            for f in ALIGN:
                need(arm, f, f"template {s}").text = need(tsa, f, f"TSA {s}").text
            ctrl = ET.fromstring(ET.tostring(base)) if a.control_dest else None
        else:
            arm, ctrl = tsa, None
        ng, mag = neutralise(arm)
        if ctrl is not None:
            neutralise(ctrl)
        ta, ba = nums(tsa.find("Angles")), nums((base if tmpl else tsa).find("Angles"))
        dang = sum(x - y for x, y in zip(ba, ta)) / len(ta) if tmpl else 0.0
        cs, odd = ctf_state(arm)
        audit[s] = {"grid_nodes_zeroed": ng, "mag_was": mag, "cs": cs, "odd_zernike": odd,
                    "axis_tsa": nums(tsa.find("AxisAngle"))[:1], "axis_template": nums((base if tmpl else tsa).find("AxisAngle"))[:1],
                    "mean_tilt_angle_template_minus_tsa_deg": round(dang, 2)}
        out[dests[0]][s] = arm
        if ctrl is not None:
            out[dests[1]][s] = ctrl
    for s, v in audit.items():
        print(f"  {s}: axis TSA {v['axis_tsa'][0]:.2f} vs template {v['axis_template'][0]:.2f} deg; template tilt angles "
              f"{v['mean_tilt_angle_template_minus_tsa_deg']:+.2f} deg vs TSA (nominal); zeroed {v['grid_nodes_zeroed']} grid nodes; "
              f"mag {v['mag_was']} -> identity; Cs {v['cs']}, odd Zernikes {'NON-ZERO' if v['odd_zernike'] else '0'}")
    if any(abs(v["mean_tilt_angle_template_minus_tsa_deg"]) > 0.5 for v in audit.values()):
        print("  NOTE: tilt angles differ between arms -> different 3D frames; particle coordinates must be transferred or re-picked")
    if not tmpl and any((v["cs"] is not None and cs_nom is not None and abs(v["cs"] - cs_nom) > 0.01) or v["odd_zernike"]
                        for v in audit.values()):
        print("  WARNING: Cs/odd-Zernike contamination kept (no --clean-template) - make a clean copy with "
              "scripts/_lib/reset_ctf_cs.py <XMLs> --out_dir <copy> --zero_zernike_odd and pass it as --clean-template")
    if len(dests) == 2:   # verify the arms differ only in the alignment fields
        for s in picked:
            A, C = out[dests[0]][s], out[dests[1]][s]
            ka, kc = list(A), list(C)
            diff = [e.tag for e, f in zip(ka, kc) if e.tag != f.tag or (e.tag not in ALIGN and ET.tostring(e) != ET.tostring(f))]
            diff += ["child count"] if len(ka) != len(kc) else []
            if diff or A.attrib != C.attrib:
                sys.exit(f"{s}: arms differ outside the alignment fields: {diff or 'attributes'}")
        print("  verified: TSA and control arms differ ONLY in " + ", ".join(ALIGN))
    if a.dry_run:
        return
    for d, xmls in out.items():
        d.mkdir(parents=True)
        for s, el in xmls.items():
            ET.ElementTree(el).write(d / f"{s}.xml", encoding="utf-8", xml_declaration=False)
        if src_proc and (src_proc / "processed_items.json").exists():
            shutil.copy2(src_proc / "processed_items.json", d / "processed_items.json")
        (d / "ARM_PROVENANCE.json").write_text(json.dumps(
            {"role": "tsa" if d == dests[0] else "control", "source_root": str(root), "clean_template": str(tmpl) if tmpl else None,
             "nominal_cs_mm": cs_nom, "nominal_cs_source": cs_src, "series": picked, "audit": audit}, indent=1))
        print(f"  wrote {len(xmls)} XMLs + ARM_PROVENANCE.json -> {d}")
    print("  XML DataDirectory is kept (points at the project's tomostar): fine for a --variant inside the same project;"
          " a standalone arm with its own tomostar/frameseries must rewrite it (it overrides the settings DataFolder).")
    print("  next (warptools-preprocess, both arms identically, --variant <arm>): ts_defocus_hand --check -> ts_ctf -> ts_reconstruct")


if __name__ == "__main__":
    main()
