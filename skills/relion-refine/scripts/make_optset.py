#!/usr/bin/env python3
"""After ts_export_particles: write our OWN optimisation set and an absolute-path particle STAR, then check the export.

WarpTools 2.0.0 writes an empty _rlnTomoParticlesFile, and _rlnImageName paths relative to metadata/ while RELION resolves
them against the job's cwd. So we never use Warp's optimisation set: we write <stem>_abspath.star (every .mrcs path made
absolute and checked to exist) and <stem>_abspath_optimisation_set.star pointing at it and at <stem>_tomograms.star.

Checks (non-zero exit on FAIL):
  particle count == --expected-n (if given); tilt series count == --expected-ts (if given)
  optics: _rlnImagePixelSize == --angpix, _rlnImageSize == --box, _rlnCtfDataAreCtfPremultiplied == --premult
  no negative coordinates; every referenced .mrcs exists
  WARN: particle-level copies of optics columns (_rlnImageSize, _rlnTomoSubtomogramBinning, ...) that disagree with the
        optics table - RELION ignores them but tomoDRGN reads the particle copy first (stale box -> wrong CTF)
  _rlnRandomSubset present, and both halves non-empty
  WARN: Cs differs between optics groups, or from --cs / config MICROSCOPE_CS_MM: refined Cs leaked from an M/MCore
        run into the export geometry
Usage: "$CRYOET_PYTHON" make_optset.py --star <export>.star --premult 1 --angpix 2.25 --box 208 [--expected-n N] [--expected-ts T] [--outdir D]
"""
import argparse, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
import starlite

STALE = ["_rlnImageSize", "_rlnTomoSubtomogramBinning", "_rlnImageDimensionality", "_rlnVoltage",
         "_rlnSphericalAberration", "_rlnAmplitudeContrast", "_rlnTomoTiltSeriesPixelSize", "_rlnImagePixelSize"]


def nominal_cs(cli):
    """--cs, else config MICROSCOPE_CS_MM, else None (then only the between-group spread is checked)."""
    if cli is not None:
        return cli
    try:
        import cryoet_config as cc
        return cc.cs_mm(cc.load())
    except (SystemExit, Exception):
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--star", required=True); ap.add_argument("--premult", type=int, required=True)
    ap.add_argument("--angpix", type=float, required=True); ap.add_argument("--box", type=int, required=True)
    ap.add_argument("--expected-n", type=int); ap.add_argument("--expected-ts", type=int)
    ap.add_argument("--outdir", help="write the _abspath files here instead of next to the export")
    ap.add_argument("--cs", type=float, help="nominal Cs (mm) to compare against; default config MICROSCOPE_CS_MM")
    a = ap.parse_args()
    star = os.path.realpath(a.star); meta = os.path.dirname(star); stem = star[:-5]
    tomos = stem + "_tomograms.star"
    fails, warns = [], []
    B = starlite.read(star); P = starlite.particles(B); O = B.get("data_optics")
    n = len(P.rows); ts = len(set(P.values("_rlnTomoName")))
    print(f"particles {n:,} in {ts} tilt series")
    if a.expected_n is not None and n != a.expected_n:
        fails.append(f"particle count {n} != expected {a.expected_n}")
    if a.expected_ts is not None and ts != a.expected_ts:
        fails.append(f"tilt-series count {ts} != expected {a.expected_ts}")
    if not os.path.exists(tomos):
        fails.append(f"missing {tomos}")
    # optics
    if O is not None and O.loop and O.rows:
        for name, want in (("_rlnImagePixelSize", a.angpix), ("_rlnImageSize", a.box), ("_rlnCtfDataAreCtfPremultiplied", a.premult)):
            if name in O.cols:
                bad = {v for v in O.values(name) if abs(float(v) - float(want)) > 1e-3}
                if bad:
                    fails.append(f"optics {name} = {sorted(bad)} != {want}")
            else:
                fails.append(f"optics table lacks {name}")
        if "_rlnSphericalAberration" in O.cols:
            cs = O.floats("_rlnSphericalAberration"); nominal = nominal_cs(a.cs)
            fix = ("re-export from a copy of the XMLs with Cs reset (scripts/_lib/reset_ctf_cs.py)")
            if max(cs) - min(cs) > 0.01:
                warns.append(f"Cs varies across {len(cs)} optics groups ({min(cs):.2f}..{max(cs):.2f} mm): refined Cs leaked "
                             f"from an M/MCore run into the export geometry - {fix}")
            elif nominal is not None and abs(cs[0] - nominal) > 0.01:
                warns.append(f"Cs {cs[0]:.2f} mm != nominal {nominal:.2f} mm - refined Cs from M/MCore? {fix}")
        for name in STALE:
            if name in P.cols and name in O.cols:
                og = dict(zip(O.values("_rlnOpticsGroup"), O.values(name)))
                diff = sum(1 for g, v in zip(P.values("_rlnOpticsGroup"), P.values(name)) if abs(float(v) - float(og[g])) > 1e-3)
                if diff:
                    warns.append(f"{diff} particles carry a stale per-particle {name} that disagrees with optics "
                                 "(harmless for RELION; strip before tomoDRGN)")
    else:
        fails.append("no data_optics loop")
    # coordinates
    for c in ("_rlnCoordinateX", "_rlnCoordinateY", "_rlnCoordinateZ"):
        if c in P.cols and min(P.floats(c)) < 0:
            fails.append(f"negative {c} (coordinates are in export pixels; check --coords_angpix / hand)")
    # halves
    if "_rlnRandomSubset" in P.cols:
        h = P.values("_rlnRandomSubset"); c1, c2 = h.count("1"), h.count("2")
        print(f"random halves {c1:,} / {c2:,}")
        if not (c1 and c2):
            fails.append("one random half is empty")
    else:
        warns.append("no _rlnRandomSubset: RELION will assign halves (fine for a first refine; set it to follow a "
                     "previous refinement)")
    # absolute image paths
    i = P.col("_rlnImageName"); missing = 0; seen = {}
    for r in P.rows:
        v = r[i]; idx, path = (v.split("@", 1) if "@" in v else ("", v))
        ap_ = path if os.path.isabs(path) else os.path.normpath(os.path.join(meta, path))
        if ap_ not in seen:
            seen[ap_] = os.path.exists(ap_)
        missing += not seen[ap_]
        r[i] = f"{idx}@{ap_}" if idx else ap_
    print(f"{len(seen):,} stack files referenced")
    if missing:
        fails.append(f"{missing} particles point at missing .mrcs files")
    ostem = os.path.join(os.path.abspath(a.outdir), os.path.basename(stem)) if a.outdir else stem
    out_star = ostem + "_abspath.star"; out_opt = ostem + "_abspath_optimisation_set.star"
    if not fails:
        starlite.write(out_star, B)
        with open(out_opt, "w") as f:
            f.write("\n# version 50001\n\ndata_\n\n"
                    f"_rlnTomoParticlesFile   {out_star}\n_rlnTomoTomogramsFile   {os.path.abspath(tomos)}\n\n")
        print(f"wrote {out_star}\nwrote {out_opt}   <- pass this as --ios")
    for w in warns:
        print("WARN ", w)
    for f_ in fails:
        print("FAIL ", f_)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
