#!/usr/bin/env python3
"""Generate ChimeraX .cxc scripts (main figure + recolor.cxc + optional closeup.cxc) from a small JSON spec.

  python3 write_cxc.py spec.json [--style NAME|PATH] [--ascii] [--chimerax-version 1.8]
  python3 write_cxc.py --print-style [--style NAME]        # show the resolved style and exit

Outputs are written next to the spec unless "out" is absolute. Stdlib only; Python 3.6+; files are always UTF-8
(use --ascii, or "ascii_labels": true in the style, for '<=4.5 A' instead of the Unicode key labels).
Appearance (background, lighting, silhouettes, colours, label placement) comes from the style (styles/*.json,
CHIMERAX_STYLE); the rules (close session, step 1, dust, nesting, #!N, no tile) are not style and always apply.

Spec (keys optional unless marked *):
{
  "out": "figure.cxc",                          * main script (overview / comparison)
  "level_rule": "enclosed volume 3.0e6 A^3 (calc_level.py --volume)",  * how the levels were computed
  "header": ["Map: ...", "Hand: ..."],            provenance lines, written as whole-line comments
  "style": "default", "style_overrides": {"background": "black"},
  "maps": [                                     * in display order, left to right
    {"file": "maps/A.mrc",                      * path RELATIVE to the .cxc
     "name": "Map A 4.1 A",                       model name
     "apix": 1.06,                              * nominal pixel size (A) - sets the default dust size
     "level": 0.0123,                           * from calc_level.py
     "locres": "maps/A_locres.mrc",               filled local-resolution map on the same grid -> coloured by it
     "color": "#b4b4b4",                          used when there is no locres (default: style map_color)
     "style": "surface",                          surface | mesh
     "transparency": 0.0,                         0-1; default 0 (or the style's overview value, see "overview")
     "matrix": [12 numbers],                      3x4 row-major [R|t] from place_matrix.py (overrides layout shift)
     "label": "Map A, 4.1 A",                     2D label above the map
     "dust_size": 10.6,                           A; default style dust_factor x apix
     "dust": true, "dust_reason": "..."},         dust=false only with a stated reason (written to the header)
     "masking": "soft mask mask_soft.mrc applied (unmasked box has neighbouring cell density)"
                                                  what was displayed: masked or unmasked, and why (header line)
  ],
  "in_cell": true,                                in-cell / in-tomogram data: every map must state "masking"
  "layout": {"x_step": 400.0},                    side-by-side shift per map (A) when a map has no "matrix"
  "palette": {"best": 4.0, "worst": 10.0},        local-resolution range; style palette colours, first = best
  "key": true,
  "models": [{"file": "model.cif", "name": "model fitted", "show": true, "ligand": "ATP"}],
  "overview": {"maps": [0], "map_transparency": 0.65},   maps made transparent so the model shows (default: map 0)
  "closeup": {"out": "closeup.cxc", "map": 0, "model": 0, "ligand": "ATP", "level": 0.02,
              "level_rule": "0.8 x median at ATP atoms of model.cif",
              "zone": 2.6, "contact": 4.5, "label_within": 4.0, "clip": 9.0},
  "save_session": "figure.cxs",                   written with includeMaps true
  "save_png": {"file": "figure.png", "width": 3000, "supersample": 3}
}
Model ids: maps (and their local-resolution maps) are opened first, then models; only THEN are local-resolution maps
hidden and nested (#k -> #d.5), because ChimeraX reuses a freed top-level id for the next model opened.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cxstyle  # noqa: E402


def palette(best, worst, colors):
    n = len(colors)
    stops = [best + i * (worst - best) / (n - 1) for i in range(n)]
    return "palette " + ":".join("%.4g,%s" % (s, c) for s, c in zip(stops, colors))


def key_line(best, worst, colors, st, ascii_):
    le, ge, A = ("<=", ">=", "A") if ascii_ else (u"≤", u"≥", u"Å")
    n = len(colors)
    picks = sorted(set([0, n // 4, n // 2, (3 * n) // 4, n - 1]))
    parts = []
    for i in picks:
        if i == 0:
            lab = "%s%g%s" % (le, best, A)
        elif i == n - 1:
            lab = "%s%g%s" % (ge, worst, A)
        elif i == n // 2:
            lab = "%g%s" % (best + (worst - best) * i / (n - 1), A)
        else:
            lab = ""
        parts.append("%s:%s" % (colors[i], lab))
    k = st.get("key", {})
    return "key %s pos %s size %s" % (" ".join(parts), k.get("pos", "0.40,0.06"), k.get("size", "0.2,0.03"))


def comment(lines):
    return ["# " + l if l else "#" for l in lines]


def q(s):
    return '"%s"' % str(s).replace('"', "'")


def build(spec, st, style_name, version, ascii_):
    maps, models = spec["maps"], spec.get("models", [])
    if not spec.get("level_rule"):
        raise SystemExit("spec needs \"level_rule\": how the contour levels were computed (calc_level.py output 'rule')")
    for k in ("file", "apix", "level"):
        for m in maps:
            if m.get(k) in (None, ""):
                raise SystemExit("every map needs \"%s\" (missing in %s)" % (k, m))
    colors = st["palette"]["colors"]
    pal = spec.get("palette", {"best": 4.5, "worst": 10.0})
    pal_s = palette(pal["best"], pal["worst"], colors)
    ov = spec.get("overview") or {}
    ov_maps = set(ov.get("maps", [0])) if models else set()
    ov_t = ov.get("map_transparency", st.get("overview_map_transparency", 0.65))

    # model ids are assigned in open order: each map, then its local-resolution map, then the atomic models
    ids, nid = [], 1
    for m in maps:
        ids.append(nid); nid += 2 if m.get("locres") else 1
    if spec.get("in_cell"):
        for m in maps:
            if not m.get("masking"):
                raise SystemExit("\"in_cell\": true - map %s needs \"masking\" (soft-masked or unmasked, and why): an "
                                 "unmasked in-cell box usually contains neighbouring cell density" % m["file"])
    dust_lines = []
    for m, d in zip(maps, ids):
        if m.get("dust", True):
            m["_dust"] = m.get("dust_size", st.get("dust_factor", 10) * m["apix"])
            dust_lines.append("Dust: #%d blobs < %.4g A hidden (surface dust). This also hides genuine weak or peripheral "
                              "density smaller than that." % (d, m["_dust"]))
        else:
            if not m.get("dust_reason"):
                raise SystemExit("map %s: \"dust\": false needs a \"dust_reason\"" % m["file"])
            dust_lines.append("Dust hiding OFF for #%d: %s" % (d, m["dust_reason"]))

    mask_lines = ["Masking: #%d %s" % (d, m["masking"]) for m, d in zip(maps, ids) if m.get("masking")]
    L = comment(spec.get("header", []) + [
        "Level rule: " + spec["level_rule"]] + mask_lines + dust_lines + [
        "Style: %s (appearance only; check_cxc.py reads this line). Written by the chimerax-figures skill for ChimeraX %s." % (style_name, version),
        "Open from INSIDE this folder:  cd <folder>  then  open " + os.path.basename(spec["out"]),
        "#!N = model N only. Local-resolution maps are children (#N.5) of their density, so moves keep colours attached."])
    L += ["close session"] + cxstyle.style_block(st)

    # 1. open everything; record ids as assigned at open time
    nid, dens, locs, mids = 1, [], [], []
    for m in maps:
        L.append("open %s" % m["file"]); dens.append(nid); nid += 1
        if m.get("locres"):
            L.append("open %s" % m["locres"]); locs.append(nid); nid += 1
        else:
            locs.append(None)
    for mo in models:
        L.append("open %s" % mo["file"]); mids.append(nid); nid += 1

    # 2. hide + nest local-resolution maps BEFORE any placement
    hidden = [i for i in locs if i]
    if hidden:
        L.append("hide #" + ",".join(str(i) for i in hidden) + " models")
    for d, l in zip(dens, locs):
        if l:
            L.append("rename #%d id #%d.5" % (l, d))

    # 3. per map: name, placement, level, dust, colour
    x_step = spec.get("layout", {}).get("x_step")
    for k, (m, d, l) in enumerate(zip(maps, dens, locs)):
        L.append("rename #!%d %s" % (d, q(m.get("name", os.path.basename(m["file"])))))
        if m.get("matrix"):
            if len(m["matrix"]) != 12:
                raise SystemExit("matrix for %s must have 12 numbers" % m["file"])
            L.append("view matrix models #%d," % d + ",".join("%.8f" % v for v in m["matrix"]))
        elif x_step and k > 0:
            L.append("view matrix models #%d,1,0,0,%.3f,0,1,0,0,0,0,1,0" % (d, k * x_step))
        transp = m.get("transparency", ov_t if k in ov_maps else 0.0)
        col = "" if l else " color %s" % m.get("color", st["map_color"])
        tr = " transparency %g" % transp if transp else ""
        L.append("volume #!%d style %s level %.6g%s%s step 1" % (d, m.get("style", "surface"), m["level"], col, tr))
        if m.get("dust", True):
            L.append("surface dust #!%d size %.4g" % (d, m["_dust"]))
        if l:
            L.append("color sample #!%d map #%d.5 %s" % (d, d, pal_s))

    # 4. models (overview styling)
    sm = st.get("models", {})
    for mo, i in zip(models, mids):
        L.append("rename #!%d %s" % (i, q(mo.get("name", os.path.basename(mo["file"])))))
        if not mo.get("show", True):
            L.append("hide #%d models" % i); continue
        L += ["hide #%d atoms" % i, "cartoon #%d" % i,
              "color #%d & nucleic %s" % (i, mo.get("nucleic_color", sm.get("nucleic_color", "burlywood"))),
              "color #%d & protein %s" % (i, mo.get("protein_color", sm.get("protein_color", "lightsteelblue")))]
        if mo.get("ligand"):
            lg = "#%d:%s" % (i, mo["ligand"])
            L += ["show %s atoms" % lg, "style %s %s" % (lg, sm.get("ligand_overview_style", "sphere")),
                  "color %s %s" % (lg, sm.get("ligand_overview_color", "red"))]

    # 5. labels, key, view
    n, lab = len(maps), st.get("labels", {})
    for k, m in enumerate(maps):
        if m.get("label"):
            L.append("2dlabels text %s xpos %.3f ypos %g size %d color %s" % (
                q(m["label"]), 0.02 + k / float(max(n, 1)), lab.get("ypos", 0.92),
                lab.get("size_few", 20) if n <= 2 else lab.get("size_many", 16), lab.get("color", "black")))
    if any(locs) and spec.get("key", True):
        L.append(key_line(pal["best"], pal["worst"], colors, st, ascii_))
    L += ["view", "view name overview"]
    if n > 1 and st.get("independent_rotation", True):
        L.append('mousemode right "rotate independent"')
    if any(locs):
        L.append("# If colours ever look stale (e.g. after using the Surface Color panel):  open recolor.cxc")
    if spec.get("save_png"):
        p = spec["save_png"]
        L.append("# Image:  save %s width %d supersample %d" % (p["file"], p.get("width", 3000), p.get("supersample", 3)))
    if spec.get("save_session"):
        L.append("save %s includeMaps true" % spec["save_session"])
    out = {"main": L}

    if any(locs):
        R = comment(["Re-apply the local-resolution colouring (%s palette, %g-%g A). Run with:  open recolor.cxc"
                     % (st["palette"].get("name", "custom"), pal["best"], pal["worst"])])
        R += ["color sample #!%d map #%d.5 %s" % (d, d, pal_s) for d, l in zip(dens, locs) if l]
        out["recolor"] = R

    c = spec.get("closeup")
    if c:
        if not models:
            raise SystemExit("closeup needs a model in \"models\"")
        sc = st.get("closeup", {})
        d, i = dens[c.get("map", 0)], mids[c.get("model", 0)]
        lg, ct = "#%d:%s" % (i, c["ligand"]), c.get("contact", 4.5)
        near = "(%s :<%g) & ~%s" % (lg, ct, lg)
        C = comment(["Close-up of %s: run AFTER %s (it changes display state)." % (c["ligand"], os.path.basename(spec["out"])),
                     "Mesh zoned around the ligand and its contacts. No surface dust here: in ChimeraX, surface dust",
                     "turns zoning off, and the zone already removes everything away from the site.",
                     "Close-up level %.6g = %s." % (c["level"], c.get("level_rule", "see the main script header"))])
        C += ["volume #!%d style mesh level %.6g color %s transparency 0 step 1" % (d, c["level"], sc.get("mesh_color", "#2f6fd6")),
              "select %s | (%s :<%g & (nucleic | protein))" % (lg, lg, ct),
              "volume zone #!%d nearAtoms sel range %g" % (d, c.get("zone", 2.6)),
              "show %s atoms" % near, "style %s stick" % lg, "style %s stick" % near,
              "color %s byhetero" % lg, "color %s & C %s" % (lg, sc.get("ligand_carbon", "magenta")),
              "color %s byhetero" % near, "color %s & C %s" % (near, sc.get("contact_carbon", "tan")),
              "cartoon #%d suppressBackboneDisplay false" % i,
              "transparency #%d & nucleic 70 target c" % i,
              "label %s text %s height 1.2 color %s offset 1,1,0" % (lg, q(c.get("ligand_label", c["ligand"])), sc.get("ligand_label_color", "black")),
              "label (%s :<%g) & ~%s residues text \"{0.name}{0.number}\" height 0.8 color %s" % (
                  lg, c.get("label_within", 4.0), lg, sc.get("residue_label_color", "dimgray")),
              "view sel", "clip near -%g far %g position %s" % (c.get("clip", 9.0), c.get("clip", 9.0), lg),
              "select clear", "view name closeup",
              "# Back to the overview: re-open %s (display state and view both reset)." % os.path.basename(spec["out"])]
        out["closeup"] = C
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", nargs="?", help="JSON spec (see above)")
    ap.add_argument("--style", help="style name (styles/<name>.json) or path; overrides spec and CHIMERAX_STYLE")
    ap.add_argument("--ascii", action="store_true", help="ASCII-only key labels ('<=4.5 A')")
    ap.add_argument("--chimerax-version", help="target ChimeraX version for the header (default CHIMERAX_VERSION or '1.8+')")
    ap.add_argument("--print-style", action="store_true")
    a = ap.parse_args()
    spec = cxstyle.read_json(a.spec) if a.spec else {}
    st, name, src = cxstyle.load_style(a.style, spec)
    if a.print_style:
        import json
        cxstyle.say("# style %s (from %s)" % (name, src)); cxstyle.say(json.dumps(st, indent=1)); return
    if not a.spec:
        ap.error("spec.json is required")
    version = a.chimerax_version or cxstyle.config_value("CHIMERAX_VERSION", "1.8+")
    out = build(spec, st, name, version, a.ascii or st.get("ascii_labels", False))
    base = os.path.dirname(os.path.abspath(a.spec))
    main_p = spec["out"] if os.path.isabs(spec["out"]) else os.path.join(base, spec["out"])
    d = os.path.dirname(main_p)
    paths = {"main": main_p, "recolor": os.path.join(d, "recolor.cxc"),
             "closeup": os.path.join(d, (spec.get("closeup") or {}).get("out", "closeup.cxc"))}
    for k, lines in out.items():
        cxstyle.write_text(paths[k], lines)
        cxstyle.say(paths[k])
    cxstyle.say("style: %s (from %s)" % (name, src))


if __name__ == "__main__":
    main()
