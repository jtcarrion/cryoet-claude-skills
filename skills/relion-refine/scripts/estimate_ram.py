#!/usr/bin/env python3
"""Decide --preread_images vs node-local scratch and size --mem, for a RELION 5 particle-series refine.

RAM model (measured from per-process RSS on real refines, not sstat, which counts page cache):
    one float copy = N_particles x box^2 x mean_tilts x 4 bytes
    preread RAM   ~= copy x (workers + 2) + working set        (leader holds it, every worker gets a copy)
Rules: preread only if that fits under the node budget with margin; otherwise job-unique node-local scratch under
SCRATCH_ROOT (needs the float16 stacks on disk: their real size). Never both - RELION ignores --scratch_dir when
prereading. Scratch must be node-local disk with room for the stacks: a small /tmp or a network scratch mount is
worse than reading the stacks in place (then use neither).
Examples: 22.7k ptcl, box 64, 41 tilts -> 14.2 GiB/copy -> ~85 GiB with 4 GPUs (fits on most GPU nodes);
          the same set at box 128 -> ~57 GiB/copy -> ~380 GiB with 4 GPUs -> scratch on a 512 GB node.

Usage: "$CRYOET_PYTHON" estimate_ram.py --star <particles>_abspath.star --gpus 4 [--node-ram-gb 512] [--working-gb 40]
--node-ram-gb defaults to $SLURM_NODE_MEM_GB, else this machine's RAM (wrong if you run it on a login node: check the
GPU nodes with `scontrol show node <name>` / `sinfo -o "%N %m"`). --max-mem-gb defaults to $SLURM_MAX_MEM_GB, else
the node RAM. Tilts per particle are read from a sample of the .mrcs headers (they vary between series).
"""
import argparse, os, random, struct, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
import starlite


def env_float(k):
    v = os.environ.get(k, "")
    return float(v) if v else None


def local_ram_gb():
    for l in open("/proc/meminfo"):
        if l.startswith("MemTotal"):
            return int(l.split()[1]) / 1048576.0
    return 256.0


def scratch_root():
    if os.environ.get("SCRATCH_ROOT"):
        return os.environ["SCRATCH_ROOT"]
    try:
        import cryoet_config as cc
        return cc.load().get("SCRATCH_ROOT", "/tmp")
    except (SystemExit, Exception):
        return "/tmp"


def nz_and_bytes(path):
    with open(path, "rb") as f:
        h = f.read(16)
    nx, ny, nz, mode = struct.unpack("<4i", h)
    return nx, nz, os.path.getsize(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--star", required=True); ap.add_argument("--gpus", type=int, required=True)
    ap.add_argument("--node-ram-gb", type=float, default=env_float("SLURM_NODE_MEM_GB"),
                    help="usable RAM per GPU node, GB (default $SLURM_NODE_MEM_GB, else this machine's RAM)")
    ap.add_argument("--working-gb", type=float, default=40.0); ap.add_argument("--sample", type=int, default=200)
    ap.add_argument("--max-mem-gb", type=float, default=env_float("SLURM_MAX_MEM_GB"),
                    help="largest --mem you are willing to request (default $SLURM_MAX_MEM_GB, else node RAM)")
    a = ap.parse_args()
    if a.node_ram_gb is None:
        a.node_ram_gb = local_ram_gb()
        print(f"NOTE node RAM {a.node_ram_gb:.0f} GB taken from THIS machine - pass --node-ram-gb for the GPU nodes")
    if a.max_mem_gb is None:
        a.max_mem_gb = a.node_ram_gb
    P = starlite.particles(starlite.read(a.star)); names = P.values("_rlnImageName")
    stacks = sorted({v.split("@", 1)[-1] for v in names}); n = len(names)
    random.seed(0); samp = random.sample(stacks, min(a.sample, len(stacks)))
    base = os.path.dirname(os.path.abspath(a.star))
    def resolve(s):
        for c in (s, os.path.join(base, s)):
            if os.path.exists(c):
                return c
        sys.exit(f"ERROR: stack {s} not found (relative to cwd or the STAR's dir): use make_optset.py's _abspath STAR "
                 "or run from the directory the paths are relative to")
    info = [nz_and_bytes(resolve(s)) for s in samp]
    box = info[0][0]
    per_stack_tilts = sum(i[1] for i in info) / len(info)
    # particle series: one .mrcs per particle holding its tilts; indexed stacks (N@file) share files
    tilts = per_stack_tilts if len(stacks) >= 0.9 * n else per_stack_tilts * len(stacks) / n
    disk_gb = sum(i[2] for i in info) / len(info) * len(stacks) / 1e9
    copy_gib = n * box * box * tilts * 4 / 2**30
    workers = a.gpus
    preread_gib = copy_gib * (workers + 2) + a.working_gb
    print(f"particles {n:,}  box {box}  mean tilts {tilts:.1f}  stacks {len(stacks):,} on disk ~{disk_gb:.0f} GB")
    print(f"one float copy {copy_gib:.1f} GiB; preread estimate with {workers} workers + leader: {preread_gib:.0f} GiB")
    budget = min(a.node_ram_gb, a.max_mem_gb) * 0.85
    if preread_gib <= budget:
        mem = int(min(a.max_mem_gb, max(64, preread_gib * 1.3)))
        print(f"DECISION: preread   --preread_images  --mem={mem}G   (no --scratch_dir)")
    else:
        mem = int(min(a.max_mem_gb, max(64, copy_gib * 0.5 + a.working_gb * (workers + 1))))
        print(f"DECISION: scratch   MODE=scratch -> job-unique dir under SCRATCH_ROOT={scratch_root()} (needs "
              f"~{disk_gb * 1.1:.0f} GB free on node-local disk; staging ~10 min per 100 GB)  --mem={mem}G")
    print("Always set --mem explicitly (--mem=0 means a site-dependent default, often far below the node's RAM).")


if __name__ == "__main__":
    main()
