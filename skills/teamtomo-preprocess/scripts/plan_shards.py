#!/usr/bin/env python3
"""Plan a multi-GPU teamtomo-workflows run: discover series exactly as batch.py does, drop finished ones (resume),
balance the rest over N GPUs, estimate disk, and write a provenance manifest. Run inside the teamtomo env.

  python plan_shards.py --config <root>/config.yaml --n-shards 2 --outdir <root>/shards/<jobid>
                        [--series a b ...] [--overwrite] [--dry-run]

Balancing: longest-processing-time greedy on the number of tilts (runtime scales ~linearly with tilts).
Writes shard_<i>.txt (one series per line) + manifest.json (repo commit/dirty, package versions, config hash, shards).
A run with nothing pending prints NOTHING TO DO and writes no shards (exit code 3).
"""
import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _tt import repo_path  # noqa: E402

REPO = None   # set in main() so --help works without the repo


def git(*a):
    try:
        return subprocess.run(["git", "-C", str(REPO), *a], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True); ap.add_argument("--n-shards", type=int, required=True)
    ap.add_argument("--outdir", required=True); ap.add_argument("--series", nargs="+")
    ap.add_argument("--overwrite", action="store_true"); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    global REPO
    REPO = Path(repo_path())
    from teamtomo_workflows import load_config
    from teamtomo_workflows.inputs import discover
    from teamtomo_workflows import outputs as O
    ov = {"input": {"series": a.series}} if a.series else {}
    cfg = load_config(a.config, ov)
    series = discover(cfg)
    if a.series:
        missing = sorted(set(a.series) - {s.name for s in series})
        if missing:
            sys.exit(f"ERROR: requested series not found in the input: {missing}")
    pending = [s for s in series if a.overwrite or not O.is_done(cfg, s.name)]
    done = len(series) - len(pending)
    print(f"{cfg['workflow']}: {len(series)} series discovered, {done} already done, {len(pending)} to run")
    # disk estimate: float32 tomogram per series
    rc = cfg["reconstruction"]; px = float(rc["pixel_spacing"]); est = 0.0
    for s in pending:
        dims = s.tomogram_dimensions_angstrom_xyz
        if dims is None and s.image_dimensions_angstrom_xy is not None and rc["thickness_angstrom"]:
            dims = (*s.image_dimensions_angstrom_xy, float(rc["thickness_angstrom"]))
        if dims:
            est += 4 * (dims[0] / px) * (dims[1] / px) * (dims[2] / px)
    if est:
        print(f"disk estimate for pending tomograms at {px} A/px: {est / 1e9:.1f} GB (float32)")
    if not pending:
        print("NOTHING TO DO (all requested series have run.json status 'done'; use --overwrite to redo)")
        sys.exit(3)
    n = max(1, min(a.n_shards, len(pending)))
    loads = [0] * n; shards = [[] for _ in range(n)]
    for s in sorted(pending, key=lambda s: -len(s.tilt_angles)):
        i = loads.index(min(loads)); shards[i].append(s.name); loads[i] += len(s.tilt_angles)
    for i, sh in enumerate(shards):
        print(f"  shard {i}: {len(sh):3d} series, {loads[i]:5d} tilts  ({', '.join(sh[:4])}{' ...' if len(sh) > 4 else ''})")
    if a.dry_run:
        return
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)
    for i, sh in enumerate(shards):
        (out / f"shard_{i}.txt").write_text("\n".join(sh) + "\n")
    from teamtomo_workflows.outputs import versions
    man = {"config": str(Path(a.config).resolve()), "config_sha256": hashlib.sha256(Path(a.config).read_bytes()).hexdigest(),
           "workflow": cfg["workflow"], "output_root": cfg["output"]["root"],
           "input": cfg["input"].get("warp_project") or cfg["input"].get("stacks"),
           "repo": str(REPO), "repo_commit": git("rev-parse", "HEAD"), "repo_dirty": bool(git("status", "--porcelain")),
           "python": sys.executable, "packages": versions(), "overwrite": a.overwrite,
           "slurm_job": os.environ.get("SLURM_JOB_ID"), "node": os.uname().nodename,
           "n_discovered": len(series), "n_done_before": done, "shards": shards, "disk_estimate_gb": round(est / 1e9, 2)}
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    if man["repo_dirty"]:
        print("WARNING: teamtomo-workflows has uncommitted changes - results are not reproducible from the commit alone")
    print(f"shards + manifest -> {out}")


if __name__ == "__main__":
    main()
