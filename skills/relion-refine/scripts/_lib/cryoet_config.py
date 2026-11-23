"""cryoet_config.py -- read the cryoet-skills config from Python (3.6+, stdlib only).
CANONICAL COPY: lib/cryoet_config.py; vendored to <skill>/scripts/_lib/ by tools/sync_lib.sh.

    import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))
    import cryoet_config as cc
    cfg = cc.load();  cfg.get("SLURM_GPU_PARTITION");  cc.have("tomodrgn", cfg)
The file is bash, so it is evaluated by bash (not parsed) -- values with $HOME etc. resolve exactly as in the shell.
"""
import os
import re
import subprocess

DEFAULT_PATH = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                            "cryoet-skills", "config.sh")

DEFAULTS = {"SCHEDULER": "slurm", "SLURM_GPU_GRES_FMT": "gpu:{n}", "SCRATCH_ROOT": "/tmp",
            "MCORE_PORT_BASE": "14300", "RELION_MPI_LAUNCHER": "mpirun", "JOLT_ENABLED": "no",
            "CHIMERAX_STYLE": "default", "MICROSCOPE_CS_MM": ""}


def config_path():
    return os.environ.get("CRYOET_SKILLS_CONFIG", DEFAULT_PATH)


def load(path=None):
    """Return {KEY: value} for every key assigned in the config file (plus DEFAULTS), values as bash sees them."""
    path = path or config_path()
    if not os.path.isfile(path):
        raise SystemExit("cryoet-skills: no config at %s -- run the cryoet-workflow skill's setup first" % path)
    keys = set(re.findall(r"^[ \t]*(?:export[ \t]+)?([A-Z][A-Z0-9_]*)=", open(path).read(), re.M))
    out = subprocess.check_output(["bash", "-c", 'set -a; source "$1" >/dev/null 2>&1; env -0', "_", path])
    env = dict(kv.split("=", 1) for kv in out.decode("utf-8", "replace").split("\0") if "=" in kv)
    cfg = dict(DEFAULTS)
    cfg.update({k: env.get(k, "") for k in keys})
    for k in DEFAULTS:            # an empty value in the file means "use the default"
        if not cfg.get(k):
            cfg[k] = DEFAULTS[k]
    return cfg


def require(cfg, *keys):
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        raise SystemExit("cryoet-skills: required config key(s) empty: %s (edit %s)" % (" ".join(missing), config_path()))


def have(stage, cfg):
    """Mirror of cryoet_have in cryoet_config.sh (config-level check only)."""
    import shutil
    w = lambda exe: shutil.which(exe) is not None
    return {
        "warp": bool(cfg.get("WARP_ENV_SCRIPT")) or w("WarpTools"),
        "m": bool(cfg.get("WARP_ENV_SCRIPT")) or w("MCore"),
        "relion": bool(cfg.get("RELION_ENV_SCRIPT")) or w("relion_refine_mpi"),
        "tomodrgn": bool(cfg.get("TOMODRGN_ENV")) or w("tomodrgn"),
        "teamtomo": bool(cfg.get("TEAMTOMO_REPO")) and os.path.isdir(cfg.get("TEAMTOMO_REPO", "")),
        "chimerax": bool(cfg.get("CHIMERAX_BIN")),
        "aretomo3": bool(cfg.get("ARETOMO3_BIN")) or w("AreTomo3"),
        "imod": bool(cfg.get("IMOD_DIR")) or w("tiltalign"),
        "noise2map": bool(cfg.get("NOISE2MAP_BIN")),
        "calc_level": bool(cfg.get("CALC_LEVEL_REPO")) and os.path.isdir(cfg.get("CALC_LEVEL_REPO", "")),
        "jolt": cfg.get("JOLT_ENABLED") == "yes",
    }[stage]


def cs_mm(cfg, cli_value=None):
    """Spherical aberration: CLI > config MICROSCOPE_CS_MM > None (caller must read it from the data/XML)."""
    v = cli_value if cli_value is not None else cfg.get("MICROSCOPE_CS_MM")
    return float(v) if v not in (None, "") else None
