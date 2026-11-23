#!/bin/bash
# Create a WarpTools project from the skill templates: $PROJ/{scripts,logs,warp/{tomostar,tmp}} + filled step scripts,
# plus a copy of the shared config library (scripts/_lib) and qc_summary.py so the project runs on its own.
#
#   init_project.sh --proj /abs/path/PROJECT KEY=VALUE [KEY=VALUE ...] [--force]
#
# Acquisition keys have NO default - take them from inspect_mdoc.py / the image headers and confirm with the user:
#   RAW_FRAMES FRAME_EXT MDOC_DIR HAVE_FRAMES ANGPIX VOLTAGE DOSE_PER_FRAME DOSE_PER_TILT TILT_AXIS TOMO_DIM
#   CS       (falls back to the config's MICROSCOPE_CS_MM if not given)
#   NFRAMES  (frames per movie; required when HAVE_FRAMES=1 unless M_GRID is given; EER: the --eer_ngroups value,
#            Warp's default 40 if EER_FLAGS sets none)
# Choice keys have the defaults below (state each one to the user; change with KEY=VALUE). Unknown keys are refused.
# Refuses to touch an existing scripts/warp_params.sh unless --force (which keeps a .bak).
set -eo pipefail
SKILL=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
case "${1:-}" in -h|--help) sed -n '2,13p' "$0"; exit 0 ;; esac
# shellcheck disable=SC1091
source "$SKILL/scripts/_lib/cryoet_config.sh" || exit 2
declare -A V=(
  [AMPLITUDE]=0.07 [OVERRIDE_AXIS]=0 [TILT_OFFSET]=0 [TS_IMPORT_DONT_INVERT]=0 [GAIN_PATH]="" [GAIN_FLAGS]=""
  [EER_FLAGS]="" [DEFOCUS_MIN]=1.0 [DEFOCUS_MAX]=6.0 [CTF_RANGE_HIGH]=7 [CTF_RANGE_LOW]=30 [CTF_WINDOW]=512
  [M_GRID]="" [NFRAMES]="" [MIN_INTENSITY]=0.3 [ALIGN_METHOD]=patches [ALIGN_ANGPIX]=10 [PATCH_SIZE]=800
  [FIDUCIAL_NM]=10 [N_BEADS_TARGET]=50 [ARETOMO_ALIGNZ]=0 [ARETOMO_DELETE_INTERMEDIATE]=1 [MIN_FOV]=0.3
  [RECON_ANGPIX]=10 [INVERT_TOMOGRAMS]=0 [CS]="${MICROSCOPE_CS_MM:-}"
)
REQ=(RAW_FRAMES FRAME_EXT MDOC_DIR HAVE_FRAMES ANGPIX VOLTAGE CS DOSE_PER_FRAME DOSE_PER_TILT TILT_AXIS TOMO_DIM)
for k in "${REQ[@]}"; do V[$k]="${V[$k]:-}"; done
PROJ=""; FORCE=0; want_proj=0
for a in "$@"; do
  if [[ $want_proj == 1 ]]; then PROJ="$a"; want_proj=0; continue; fi
  case "$a" in
    --proj) want_proj=1 ;;
    --proj=*) PROJ="${a#--proj=}" ;;
    --force) FORCE=1 ;;
    [A-Z]*=*) k="${a%%=*}"
              [[ -v "V[$k]" ]] || { echo "ERROR: unknown key $k (see the template warp_params.sh for the list)" >&2; exit 1; }
              V[$k]="${a#*=}" ;;
    *) echo "ERROR: bad argument $a" >&2; exit 1 ;;
  esac
done
[[ "$PROJ" == /* ]] || { echo "ERROR: --proj must be an absolute path" >&2; exit 1; }
# Warp writes averages (+ odd/even halves) for every movie, tilt stacks and tomograms: budget hundreds of GB per
# dataset. Home directories are usually small and quota-limited; put projects on bulk/project storage.
case "$PROJ" in "$HOME"/*)
  if [[ "${ALLOW_HOME:-0}" != 1 ]]; then
    msg="project under \$HOME - put it on bulk storage${DEFAULT_PROJECT_ROOT:+ (config DEFAULT_PROJECT_ROOT=$DEFAULT_PROJECT_ROOT)}; ALLOW_HOME=1 to override"
    if [[ "$SCHEDULER" == slurm ]]; then echo "ERROR: $msg" >&2; exit 1; else echo "WARN: $msg" >&2; fi
  fi ;;
esac
miss=(); for k in "${REQ[@]}"; do [[ -n "${V[$k]}" ]] || miss+=("$k"); done
[[ ${#miss[@]} -eq 0 ]] || { echo "ERROR: missing acquisition values: ${miss[*]} (run inspect_mdoc.py; CS may also come from config MICROSCOPE_CS_MM)" >&2; exit 1; }
[[ "${V[DOSE_PER_FRAME]}" == -* ]] && { echo "ERROR: give DOSE_PER_FRAME positive; the script negates it for --exposure" >&2; exit 1; }
[[ "${V[HAVE_FRAMES]}" == 0 || "${V[HAVE_FRAMES]}" == 1 ]] || { echo "ERROR: HAVE_FRAMES must be 0 or 1" >&2; exit 1; }
for k in RAW_FRAMES MDOC_DIR; do [[ "${V[$k]}" == /* && -d "${V[$k]}" ]] || { echo "ERROR: $k must be an existing absolute dir" >&2; exit 1; }; done
[[ -z "${V[GAIN_PATH]}" || ( "${V[GAIN_PATH]}" == /* && -f "${V[GAIN_PATH]}" ) ]] || { echo "ERROR: GAIN_PATH must be an existing absolute file" >&2; exit 1; }
[[ "${V[TOMO_DIM]}" =~ ^[0-9]+x[0-9]+x[0-9]+$ ]] || { echo "ERROR: TOMO_DIM must be XxYxZ (unbinned px)" >&2; exit 1; }
# Motion grid: temporal nodes = frames per movie. No silent default - a wrong count changes the motion model.
if [[ -z "${V[NFRAMES]}" && "${V[FRAME_EXT]}" == *eer* ]]; then
  g=$(echo "${V[EER_FLAGS]}" | sed -n 's/.*--eer_ngroups[ =]*\([0-9][0-9]*\).*/\1/p')
  V[NFRAMES]="${g:-40}"; echo "NOTE: EER -> NFRAMES=${V[NFRAMES]} (eer groups)"
fi
if [[ -z "${V[M_GRID]}" ]]; then
  if [[ "${V[HAVE_FRAMES]}" == 1 ]]; then
    [[ "${V[NFRAMES]}" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: HAVE_FRAMES=1 needs NFRAMES (frames per movie; inspect_mdoc.py reports NumSubFrames) or an explicit M_GRID" >&2; exit 1; }
    V[M_GRID]="1x1x${V[NFRAMES]}"
  else
    V[M_GRID]="1x1x1"   # unused without frames (fs_ctf only)
  fi
fi
[[ -n "${V[NFRAMES]}" ]] || V[NFRAMES]="${V[M_GRID]##*x}"
case "${V[ALIGN_METHOD]}" in
  patches|fiducials) cryoet_have imod || echo "WARN: ALIGN_METHOD=${V[ALIGN_METHOD]} needs IMOD - config IMOD_DIR is empty and tiltalign is not on PATH" >&2 ;;
  aretomo3) cryoet_have aretomo3 || echo "WARN: ALIGN_METHOD=aretomo3 needs AreTomo3 - config ARETOMO3_BIN is empty" >&2 ;;
  import) ;;
  *) echo "ERROR: ALIGN_METHOD must be patches|fiducials|aretomo3|import" >&2; exit 1 ;;
esac
cryoet_have warp || echo "WARN: WarpTools not configured (config WARP_ENV_SCRIPT) - the step scripts will refuse to run" >&2
V[PROJ]="$PROJ"
if [[ -f "$PROJ/scripts/warp_params.sh" && "$FORCE" != 1 ]]; then
  echo "ERROR: $PROJ/scripts/warp_params.sh exists - edit it, or pass --force (keeps a .bak)" >&2; exit 1; fi
mkdir -p "$PROJ/scripts/_lib" "$PROJ/logs" "$PROJ/warp/tomostar" "$PROJ/warp/tmp"
PY="${CRYOET_PYTHON:-python3}"
DECL="$(declare -p V)"
for f in "$SKILL"/templates/*; do
  b=$(basename "$f"); dest="$PROJ/scripts/$b"
  [[ -f "$dest" && "$FORCE" == 1 ]] && cp -p "$dest" "$dest.bak"
  "$PY" - "$f" "$dest" "$DECL" <<'PY'
import sys, re
src, dst, decl = sys.argv[1], sys.argv[2], sys.argv[3]
vals = dict(re.findall(r'\[([A-Z_0-9]+)\]="((?:[^"\\]|\\.)*)"', decl))
s = open(src).read()
s = re.sub(r"__([A-Z_0-9]+)__", lambda m: vals.get(m.group(1), m.group(0)), s)
left = sorted(set(re.findall(r"__([A-Z_0-9]+)__", s)))
if left:
    sys.exit("unfilled placeholders in %s: %s" % (src, left))
open(dst, "w").write(s)
PY
  chmod +x "$dest"
done
cp -p "$SKILL"/scripts/_lib/* "$PROJ/scripts/_lib/"
cp -p "$SKILL/scripts/qc_summary.py" "$PROJ/scripts/"   # inspect_mdoc.py comes with _lib
# hand-off record for downstream skills (never fatal)
PS="$PROJ/scripts/_lib/project_state.py"
if [[ ! -f "$PROJ/cryoet_project.json" ]]; then
  "$PY" "$PS" init "$PROJ" --dataset "$(basename "$PROJ")" --angpix "${V[ANGPIX]}" --kv "${V[VOLTAGE]}" --cs "${V[CS]}" \
    --amp "${V[AMPLITUDE]}" --dose_per_tilt "${V[DOSE_PER_TILT]}" >/dev/null || echo "WARN: could not create cryoet_project.json" >&2
fi
if [[ -f "$PROJ/cryoet_project.json" ]]; then
  "$PY" "$PS" set "$PROJ" acquisition.tilt_axis "${V[TILT_AXIS]}" >/dev/null
  "$PY" "$PS" set "$PROJ" stages.warptools-preprocess.warp_project "$PROJ/warp" >/dev/null
  "$PY" "$PS" set "$PROJ" stages.warptools-preprocess.default_arm baseline >/dev/null
  "$PY" "$PS" set "$PROJ" stages.warptools-preprocess.status planned >/dev/null
  "$PY" "$PS" set "$PROJ" stages.warptools-preprocess.ts_import_dont_invert "${V[TS_IMPORT_DONT_INVERT]}" >/dev/null
fi
echo "project ready: $PROJ   (M_GRID ${V[M_GRID]}, CS ${V[CS]}, ts_import --dont_invert=${V[TS_IMPORT_DONT_INVERT]})"
echo "  edit/inspect   $PROJ/scripts/warp_params.sh"
echo "  step 1         bash $PROJ/scripts/01_create_settings.sh"
if [[ "$SCHEDULER" == slurm ]]; then
  echo "  step 2         source $PROJ/scripts/_lib/cryoet_config.sh && CRYOET_SBATCH_OPTS=\"-o $PROJ/logs/02_%j.out -e $PROJ/logs/02_%j.err\" cryoet_submit gpu 2 \"\" $PROJ/scripts/02_fs_motion_and_ctf.sbatch"
else
  echo "  step 2         WARP_NGPU=<n> bash $PROJ/scripts/02_fs_motion_and_ctf.sbatch > $PROJ/logs/02_local.out 2>&1"
fi
echo "  step 3         bash $PROJ/scripts/03_ts_import.sh"
echo "  smoke test     $PROJ/scripts/submit_chain.sh --to 7 --hand auto --series <ONE> --variant smoketest"
