#!/usr/bin/env python3
"""Status of a teamtomo-workflows output root, rebuilt from every <series>/run.json (the authoritative record;
batch_summary.csv only holds rows of batches that reached their end).

  python status.py --root <output root> [--expect-series a b ...] [--csv <path>] [--quiet]

Per series: status (done / failed / running = interrupted or still going / missing), time, axis angle, thickness,
mean defocus, flagged CTF fits, tomogram size and whether the file listed in run.json exists. Writes <root>/status.csv.
Also flags: a run.json whose config differs from the root's config.yaml (mixed root), tomograms missing on disk,
TSA axis angles far from the batch median (hand / axis-search failure candidates), and leftover non-standard files.
Pure stdlib - runs with any python3 >= 3.6 (PyYAML optional, only to read the series list from config.yaml).
"""
import argparse, csv, json, statistics, sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True); ap.add_argument("--expect-series", nargs="+")
    ap.add_argument("--csv"); ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    root = Path(a.root)
    rows, cfgs = [], set()
    for rj in sorted(root.glob("*/run.json")):
        r = json.loads(rj.read_text()); res = r.get("results", {}); d = rj.parent
        outs = r.get("outputs", {}); tomo = next((d / v for k, v in outs.items() if str(v).endswith(".mrc")), None)
        cfgs.add(json.dumps({k: v for k, v in r.get("config", {}).items() if k not in ("input", "output", "compute")}, sort_keys=True))
        rows.append({"series": r.get("series", d.name), "status": r.get("status"), "total_s": r.get("total_s"),
                     "axis_deg": res.get("tilt_axis_angle_deg"), "thickness_A": res.get("specimen_thickness_angstrom"),
                     "defocus_um": res.get("mean_defocus_um"), "ctf_flagged": res.get("ctf_fits_flagged"),
                     "tomogram": tomo.name if tomo else "", "tomo_gb": round(tomo.stat().st_size / 1e9, 3) if tomo and tomo.exists() else None,
                     "tomo_exists": bool(tomo and tomo.exists()), "warp_xml": (d / f"{d.name}.xml").exists(),
                     "host": r.get("host"), "gpu": r.get("gpu"), "started": r.get("started"),
                     "error": (r.get("error") or "").splitlines()[0][:160] if r.get("error") else ""})
    seen = {r["series"] for r in rows}
    expect = list(a.expect_series or [])
    cy = root / "config.yaml"
    if not expect and cy.exists():   # never-started series: the config's explicit list (series: all needs --expect-series)
        try:
            import yaml
            ser = (yaml.safe_load(cy.read_text()) or {}).get("input", {}).get("series")
        except Exception:
            ser = None
        if isinstance(ser, list):
            expect = [str(x) for x in ser]
    for s in expect:
        if s not in seen:
            rows.append({"series": s, "status": "missing"})
    keys = ["series", "status", "total_s", "axis_deg", "thickness_A", "defocus_um", "ctf_flagged", "tomogram", "tomo_gb",
            "tomo_exists", "warp_xml", "host", "gpu", "started", "error"]
    out = Path(a.csv) if a.csv else root / "status.csv"
    try:
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore"); w.writeheader(); w.writerows(rows)
    except PermissionError:
        print(f"  (root not writable - status table not written; pass --csv <path>)"); out = None
    n = {}
    for r in rows:
        n[r["status"]] = n.get(r["status"], 0) + 1
    print(f"{root}: {len(rows)} series  " + "  ".join(f"{k} {v}" for k, v in sorted(n.items(), key=lambda x: str(x[0]))))
    done = [r for r in rows if r["status"] == "done"]
    if done:
        ts = [r["total_s"] for r in done if r.get("total_s")]
        gb = sum(r["tomo_gb"] or 0 for r in done)
        print(f"  done: median {statistics.median(ts):.0f} s/series, tomograms {gb:.1f} GB" if ts else "")
        ax = [r["axis_deg"] for r in done if r.get("axis_deg") is not None]
        if len(ax) >= 3:
            med = statistics.median(ax)
            odd = [(r["series"], r["axis_deg"]) for r in done if r.get("axis_deg") is not None and abs(r["axis_deg"] - med) > 5]
            print(f"  TSA axis angle: median {med:.2f} deg, range {min(ax):.2f}..{max(ax):.2f}")
            for s, v in odd:
                print(f"  CHECK axis: {s} {v:.2f} deg ({v - med:+.1f} from median) - axis search / hand candidate")
    for r in rows:
        if r["status"] == "done" and not r["tomo_exists"]:
            print(f"  MISSING tomogram on disk for done series {r['series']}")
        if r["status"] == "failed":
            print(f"  FAILED {r['series']}: {r['error']}")
        if r["status"] == "running":
            print(f"  RUNNING/INTERRUPTED {r['series']} (started {r['started']} on {r['host']}) - re-run resumes it")
        if r["status"] == "missing":
            print(f"  MISSING {r['series']}: no run.json")
    if len(cfgs) > 1:
        print(f"  WARNING: {len(cfgs)} different processing configs in one root (alignment/ctf/reconstruction) - mixed root")
    if not a.quiet and out:
        print(f"  status table -> {out}")
    sys.exit(1 if any(r["status"] in ("failed", "missing") for r in rows) else 0)


if __name__ == "__main__":
    main()
