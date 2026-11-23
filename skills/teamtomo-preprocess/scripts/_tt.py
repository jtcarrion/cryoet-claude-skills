"""Locate the teamtomo-workflows checkout for this skill's helpers (stdlib only, python 3.6+).

Order: $TEAMTOMO_REPO (exported by run_shards.sbatch) > TEAMTOMO_REPO in the cryoet-skills config. If neither gives
an existing directory, exit with install instructions (env/install_env.sh) instead of a traceback.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))

INSTALL_HINT = ("teamtomo-workflows is not configured. Install it with\n"
                "  bash <skill dir>/env/install_env.sh --dest <software dir>\n"
                "then set TEAMTOMO_REPO and TEAMTOMO_ENV in your cryoet-skills config (the installer prints both lines).")


def repo_path(add_to_syspath=True):
    repo = os.environ.get("TEAMTOMO_REPO", "")
    if not repo:
        try:
            import cryoet_config as cc
            repo = cc.load().get("TEAMTOMO_REPO", "")
        except SystemExit:
            repo = ""
    if not repo or not os.path.isdir(repo):
        sys.exit("cryoet-skills: TEAMTOMO_REPO %r is not a directory.\n%s" % (repo, INSTALL_HINT))
    if add_to_syspath and repo not in sys.path:
        sys.path.insert(0, repo)
    return repo
