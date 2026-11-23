#!/bin/bash
# install_env.sh - clone teamtomo-workflows and build its Python environment with uv (one-off, ~1-5 min).
#
#   bash install_env.sh --dest DIR [--repo-dir DIR] [--env-dir DIR] [--ref COMMIT] [--torch-index URL] [--uv PATH]
#
#   --dest DIR         parent folder for everything (default repo DIR/teamtomo-workflows, env DIR/envs/teamtomo,
#                      uv caches DIR/uv_cache + DIR/uv_python). Put it on project/software storage, not a small $HOME.
#   --repo-dir DIR     use/clone the checkout here (an existing checkout is reused, never modified)
#   --env-dir DIR      venv location (must not exist)
#   --ref COMMIT       check out this commit/tag after cloning (default: the default branch). The skill was
#                      validated against commit caf1f46; plan_shards.py records the commit of every run.
#   --torch-index URL  PyTorch wheel index, e.g. https://download.pytorch.org/whl/cu126 - pick the CUDA build your
#                      driver supports (`nvidia-smi` shows "CUDA Version: X.Y" = the newest it supports).
#                      Default: $TORCH_CUDA_INDEX from the cryoet-skills config, else empty = let pip choose (the
#                      PyPI default wheel; fine on most recent drivers).
#   --uv PATH          uv binary (default: $UV_BIN, else `uv` on PATH). Install: `pip install --user uv`.
# Env: TEAMTOMO_REPO_URL (default https://github.com/jtcarrion/teamtomo-workflows).
# Needs internet access (git clone + pip). If your login nodes have none, run it on a node that has.
#
# Why --override: the repo's requirements.txt pins the TeamTomo packages to git commits (teamtomo/teamtomo, and - until
# teamtomo/teamtomo#159 (from_warp_xml) is merged - two packages from a fork). Packages pulled from the fork depend on
# their siblings by the fork URL, so uv sees two URLs for one package ("Requirements contain conflicting URLs for
# package ...") and refuses. Passing every git pin of requirements.txt as an override makes requirements.txt the single
# source of truth. The override list is derived from requirements.txt, so it adapts when upstream drops the fork.
#
# Why a uv-MANAGED python: a distro python often has no Python.h; triton (torch.compile, used by TSA) compiles a C
# helper at runtime -> "fatal error: Python.h" on every TSA series while xml_to_tomograms works. Checked at the end.
set -eo pipefail
usage() { sed -n '2,29p' "$0"; }

DEST=""; REPO=""; ENV=""; REF=""; UVB="${UV_BIN:-}"; TORCH_INDEX_SET=0; TORCH_INDEX=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dest) DEST="$2"; shift 2 ;;
        --repo-dir) REPO="$2"; shift 2 ;;
        --env-dir) ENV="$2"; shift 2 ;;
        --ref) REF="$2"; shift 2 ;;
        --torch-index) TORCH_INDEX="$2"; TORCH_INDEX_SET=1; shift 2 ;;
        --uv) UVB="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

# config values as defaults, if a config exists (optional for this script)
CFG="${CRYOET_SKILLS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/cryoet-skills/config.sh}"
if [[ -f "$CFG" ]]; then
    # shellcheck disable=SC1090
    source "$CFG"
    [[ $TORCH_INDEX_SET == 0 ]] && TORCH_INDEX="${TORCH_CUDA_INDEX:-}"
    [[ -z "$UVB" ]] && UVB="${UV_BIN:-}"
fi

if [[ -z "$DEST" && ( -z "$REPO" || -z "$ENV" ) ]]; then
    echo "ERROR: give --dest DIR (or both --repo-dir and --env-dir)" >&2; usage >&2; exit 2
fi
REPO="${REPO:-$DEST/teamtomo-workflows}"; ENV="${ENV:-$DEST/envs/teamtomo}"
URL="${TEAMTOMO_REPO_URL:-https://github.com/jtcarrion/teamtomo-workflows}"
UVB="${UVB:-$(command -v uv || true)}"
[[ -n "$UVB" && -x "$UVB" ]] || { echo "ERROR: uv not found - install it (pip install --user uv) or pass --uv PATH" >&2; exit 3; }
[[ -e "$ENV" ]] && { echo "ERROR: $ENV exists - pick another --env-dir or remove it yourself" >&2; exit 1; }
if [[ -n "$DEST" ]]; then
    export UV_CACHE_DIR="${UV_CACHE_DIR:-$DEST/uv_cache}" UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$DEST/uv_python}"
fi

if [[ -d "$REPO/.git" ]]; then
    echo "using existing checkout $REPO ($(git -C "$REPO" rev-parse --short HEAD))"
else
    mkdir -p "$(dirname "$REPO")"
    git clone "$URL" "$REPO"
    [[ -n "$REF" ]] && git -C "$REPO" checkout "$REF"
fi
[[ -f "$REPO/requirements.txt" ]] || { echo "ERROR: $REPO/requirements.txt missing - not a teamtomo-workflows checkout?" >&2; exit 1; }

OV=$(mktemp); trap 'rm -f "$OV"' EXIT
grep -E '^[A-Za-z0-9_.-]+ @ git\+' "$REPO/requirements.txt" > "$OV" || true
echo "git pins passed as overrides: $(wc -l < "$OV")"

nice -n 10 "$UVB" venv --python 3.12 --python-preference only-managed "$ENV"
# shellcheck disable=SC1091
source "$ENV/bin/activate"
if [[ -n "$TORCH_INDEX" ]]; then
    nice -n 10 "$UVB" pip install torch torchvision --index-url "$TORCH_INDEX"
else
    nice -n 10 "$UVB" pip install torch torchvision
fi
if [[ -s "$OV" ]]; then
    nice -n 10 "$UVB" pip install -r "$REPO/requirements.txt" --override "$OV"
else
    nice -n 10 "$UVB" pip install -r "$REPO/requirements.txt"
fi
python -c "import torch, torch_tilt_series, torch_reconstruct_tomogram, torch_tiltxcorr, warpxmlfile; print('import OK', torch.__version__, 'CUDA build', torch.version.cuda)"
python -c "import sysconfig, os; h=os.path.join(sysconfig.get_paths()['include'], 'Python.h'); assert os.path.exists(h), h; print('Python.h OK', h)"

cat <<EOF

Done. Add these lines to your cryoet-skills config ($CFG):
TEAMTOMO_REPO="$REPO"
TEAMTOMO_ENV="venv:$ENV"
Check the GPU build on a GPU node:  source $ENV/bin/activate && python -c 'import torch; print(torch.cuda.is_available())'
EOF
