#!/usr/bin/env python3
"""detect_env.py -- probe this machine/site and print a PROPOSED cryoet-skills config (stdlib, Python 3.6+).

    python3 detect_env.py                 # human-readable findings + proposed config on stdout
    python3 detect_env.py --json          # machine-readable findings
    python3 detect_env.py --write PATH    # write the proposed config (refuses to overwrite without --force)

Read-only and cheap: runs `sinfo` once, `command -v` lookups, `conda env list`, and imports in candidate pythons.
It never scans filesystems. Every value is a GUESS for the user to confirm -- the cryoet-workflow skill walks
through them with the user before writing.
"""
import argparse, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "config.template.sh")


def run(cmd, timeout=20):
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=timeout).decode("utf-8", "replace")
    except Exception:
        return ""


def slurm():
    if not shutil.which("sbatch"):
        return {"scheduler": "none"}
    rows = [l.split("|") for l in run(["sinfo", "-h", "-o", "%P|%G|%l|%c|%m"]).splitlines() if l.count("|") == 4]
    parts = {}
    for p, g, lim, cpus, mem in rows:
        name = p.rstrip("*")
        d = parts.setdefault(name, {"default": p.endswith("*"), "gpus": set(), "timelimit": lim,
                                    "cpus": cpus, "mem_mb": mem})
        for m in re.finditer(r"gpu:([A-Za-z0-9_]+):(\d+)|gpu:(\d+)", g):
            d["gpus"].add(m.group(1) or "generic")
    for d in parts.values():
        d["gpus"] = sorted(d["gpus"])
    gpu_parts = [n for n, d in parts.items() if d["gpus"]]
    cpu_parts = [n for n, d in parts.items() if not d["gpus"]]
    return {"scheduler": "slurm", "partitions": parts, "gpu_partitions": gpu_parts, "cpu_partitions": cpu_parts,
            "user_accounts": sorted(set(run(["sacctmgr", "-nP", "show", "assoc", "user=" + os.environ.get("USER", ""),
                                             "format=account"]).split()))}


def tools():
    names = ["WarpTools", "MTools", "MCore", "relion_refine_mpi", "relion_postprocess", "tomodrgn", "AreTomo3",
             "tiltalign", "imod", "chimerax", "ChimeraX", "noise2map", "mpirun", "srun", "conda", "module", "nvidia-smi"]
    return {n: shutil.which(n) for n in names if shutil.which(n)}


def conda_envs():
    out = run(["conda", "env", "list", "--json"]) if shutil.which("conda") else ""
    try:
        envs = json.loads(out).get("envs", [])
    except Exception:
        envs = []
    # conda is often not on PATH in non-login shells: also list the usual env dirs (one level, no recursion)
    home = os.path.expanduser("~")
    for root in [os.path.join(home, d, "envs") for d in (".conda", "miniconda3", "miniforge3", "anaconda3", "mambaforge")] \
            + ([os.path.join(os.environ["CONDA_PREFIX"], "envs")] if "CONDA_PREFIX" in os.environ else []):
        if os.path.isdir(root):
            envs += [os.path.join(root, e) for e in sorted(os.listdir(root)) if os.path.isdir(os.path.join(root, e, "bin"))]
    seen = set()
    return [e for e in envs if not (e in seen or seen.add(e))]


def good_python(envs):
    cands = [sys.executable] + [os.path.join(e, "bin", "python") for e in envs]
    probe = "import numpy, scipy, mrcfile, matplotlib; import sys; print(sys.version.split()[0])"
    for c in cands:
        if os.path.exists(c):
            v = run([c, "-c", probe]).strip()
            if v:
                return c, v
    return None, None


def env_named(envs, *keys):
    for e in envs:
        b = os.path.basename(e).lower()
        if any(k in b for k in keys):
            return e
    return ""


def propose(f):
    s, env = f["slurm"], f["conda_envs"]
    gp = s.get("gpu_partitions", [])
    gpart = next((p for p in gp if s["partitions"][p]["default"]), gp[0] if gp else "")
    cpart = next((p for p in s.get("cpu_partitions", []) if s["partitions"][p]["default"]),
                 (s.get("cpu_partitions") or [""])[0])
    tomodrgn_env = env_named(env, "tomodrgn")
    teamtomo_env = env_named(env, "teamtomo")
    return {
        "SCHEDULER": s["scheduler"],
        "SLURM_GPU_PARTITION": gpart, "SLURM_CPU_PARTITION": cpart,
        "SLURM_ACCOUNT": s.get("user_accounts", [""])[0] if len(s.get("user_accounts", [])) == 1 else "",
        "SLURM_GPU_GRES_FMT": "gpu:{n}",
        "SLURM_MAX_WALLTIME": s["partitions"][gpart]["timelimit"] if gpart else "",
        "CRYOET_PYTHON": f["python"] or "",
        "WARP_ENV_SCRIPT": "" if "WarpTools" not in f["tools"] else "",
        "RELION_MPI_LAUNCHER": "mpirun" if "mpirun" in f["tools"] else ("srun" if "srun" in f["tools"] else "mpirun"),
        "TOMODRGN_ENV": ("conda:" + tomodrgn_env) if tomodrgn_env else "",
        "TEAMTOMO_ENV": ("conda:" + teamtomo_env) if teamtomo_env else "",
        "CHIMERAX_BIN": f["tools"].get("chimerax") or f["tools"].get("ChimeraX") or "",
    }


def render(values):
    out = []
    for line in open(TEMPLATE):
        m = re.match(r'^([A-Z][A-Z0-9_]*)="(.*?)"(.*)$', line.rstrip("\n"))
        if m and values.get(m.group(1)):
            line = '%s="%s"%s\n' % (m.group(1), values[m.group(1)], m.group(3))
        out.append(line)
    return "".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", metavar="PATH")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    f = {"slurm": slurm(), "tools": tools(), "conda_envs": conda_envs()}
    f["python"], f["python_version"] = good_python(f["conda_envs"])
    if a.json:
        print(json.dumps(f, indent=1, default=list)); return 0
    p = propose(f)
    if a.write:
        if os.path.exists(a.write) and not a.force:
            sys.exit("refusing to overwrite %s (use --force after showing the user a diff)" % a.write)
        os.makedirs(os.path.dirname(os.path.abspath(a.write)), exist_ok=True)
        open(a.write, "w").write(render(p)); print("wrote", a.write); return 0
    s = f["slurm"]
    print("== scheduler:", s["scheduler"])
    for n, d in sorted(s.get("partitions", {}).items()):
        print("   %-22s gpus=%-22s limit=%-11s cpus=%s mem_mb=%s%s" % (n, ",".join(d["gpus"]) or "-", d["timelimit"],
              d["cpus"], d["mem_mb"], "  (default)" if d["default"] else ""))
    if s.get("user_accounts"): print("   accounts:", " ".join(s["user_accounts"]))
    print("== tools on PATH:", ", ".join(sorted(f["tools"])) or "none")
    print("== conda envs:", len(f["conda_envs"]), "(" + ", ".join(os.path.basename(e) for e in f["conda_envs"][:15]) + ")")
    print("== python with numpy/scipy/mrcfile/matplotlib:", f["python"] or "NONE FOUND", f["python_version"] or "")
    print("\n== proposed values (confirm each with the user):")
    for k, v in p.items():
        print('   %s="%s"' % (k, v))
    return 0


if __name__ == "__main__":
    sys.exit(main())
