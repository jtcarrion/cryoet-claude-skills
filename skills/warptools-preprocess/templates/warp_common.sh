#!/bin/bash
# Shared option handling for the tilt-series steps (04-07). SOURCE after warp_params.sh and warp_env.sh.
#
#   --variant NAME        run in an isolated processing folder $PROJ/NAME instead of the baseline $TS_PROC.
#                         --output_processing is NOT sticky: every downstream step (05 hand, 06 ctf, 07 reconstruct,
#                         and the export) must carry the SAME --variant, or it silently reads the baseline geometry.
#                         submit_chain.sh does this for you.
#   --input-variant NAME  read from a different folder than you write to (default: same as --variant)
#   --series a,b          restrict to these series (WarpTools --input_data <tomostar>). Use it when only some series
#                         changed: otherwise every step redoes all series and the variant folder LOOKS complete but is
#                         mostly a copy of the baseline.
#   --method M            04 only: patches | fiducials | aretomo3 | import
#   --alignments DIR      04 import only: DIR/<series>/<series>.xf + .tlt (Warp series names)
#   --alignment-angpix A  04 import only: A/px the .xf SHIFTS were computed at - not necessarily the binning of the
#                         stack the user mentions; verify by round-trip. Wrong value = every shift silently mis-scaled.
#   --patch-size A        04 patches only
#   --hand MODE           05 only: check (default) | auto | flip | noflip | switch
#   --inverted            07 only: contrast-inverted tomograms (template matching). Give them their own --variant,
#                         or they overwrite the viewing volumes.
#   --no-seed             04 only: start a variant folder empty instead of from the baseline XMLs
#   --skip-hand-check     06 only: run ts_ctf although step 5 never ran on this folder (you know the hand is set)
#   --dry-run             print the WarpTools command(s) and exit
# Hand-check ordering: 04 align -> 05 ts_defocus_hand --check (and the fix) -> 06 ts_ctf. Step 5 leaves
# hand_status.txt in the processing folder; step 6 refuses to run without it (or AUTO_HAND=N / --skip-hand-check).
# A processing folder is self-contained (per-series XMLs, tiltstack/, reconstruction/, logs/, processed_items.json).
# Single-series reruns REWRITE processed_items.json wholesale (all other entries vanish): run_warp keeps a dated copy.

VARIANT=""; INPUT_VARIANT=""; SERIES=""; INVERTED=0; METHOD="${ALIGN_METHOD:-patches}"
ALIGNMENTS_DIR=""; IMPORT_ANGPIX=""; HAND_MODE=check; DRY_RUN=0; NO_SEED=0; SKIP_HAND_CHECK=0

parse_common_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --variant) VARIANT="$2"; shift 2 ;;
            --input-variant) INPUT_VARIANT="$2"; shift 2 ;;
            --series) SERIES="$2"; shift 2 ;;
            --method) METHOD="$2"; shift 2 ;;
            --alignments) ALIGNMENTS_DIR="$2"; shift 2 ;;
            --alignment-angpix) IMPORT_ANGPIX="$2"; shift 2 ;;
            --patch-size) PATCH_SIZE="$2"; shift 2 ;;
            --hand) HAND_MODE="$2"; shift 2 ;;
            --inverted) INVERTED=1; shift ;;
            --no-seed) NO_SEED=1; shift ;;
            --skip-hand-check) SKIP_HAND_CHECK=1; shift ;;
            --dry-run) DRY_RUN=1; shift ;;
            -h|--help) sed -n '2,27p' "$PROJ/scripts/warp_common.sh"; exit 0 ;;
            *) echo "ERROR: unknown option: $1 (see --help)" >&2; exit 1 ;;
        esac
    done
}

resolve_processing() {
    PROC_FLAGS=()
    if [[ -z "$VARIANT" && -z "$INPUT_VARIANT" ]]; then
        PROC_IN="$TS_PROC"; PROC_OUT="$TS_PROC"; PROC_LABEL="baseline ($TS_PROC)"; return
    fi
    PROC_OUT="$PROJ/${VARIANT:-$INPUT_VARIANT}"; PROC_IN="$PROJ/${INPUT_VARIANT:-$VARIANT}"
    PROC_FLAGS=(--input_processing "$PROC_IN" --output_processing "$PROC_OUT")
    PROC_LABEL="variant ${VARIANT:-$INPUT_VARIANT}"
}

resolve_series() {
    SERIES_FLAGS=(); SERIES_LABEL="all series"
    [[ -z "$SERIES" ]] && return
    local listf="$PROC_OUT/input_series_${SLURM_JOB_ID:-local$$}.txt"    # on shared storage, never /tmp
    mkdir -p "$PROC_OUT"; : > "$listf"
    local IFS=,
    for s in $SERIES; do
        local f="$TOMOSTAR_DIR/${s}.tomostar"
        [[ -f "$f" ]] || { echo "ERROR: no such series: $f" >&2; exit 1; }
        echo "$f" >> "$listf"
    done
    SERIES_FLAGS=(--input_data "$listf"); SERIES_LABEL="$(wc -l < "$listf") series: $SERIES"
}

# A variant folder starts from the baseline XMLs: an alignment verb rewrites only the GEOMETRY, while the CTF fit and
# defocus handedness live in the same XML. Starting empty makes the comparison not like-for-like.
seed_variant_from_baseline() {
    local dest="$1"
    if [[ "$DRY_RUN" -eq 1 ]]; then echo "  (dry run) would seed $dest from $TS_PROC"; return; fi
    mkdir -p "$dest"
    [[ "$NO_SEED" -eq 1 ]] && { echo "  --no-seed: $dest starts empty"; return; }
    local live; live=$(find "$TS_PROC/tasks/running" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l)
    [[ "$live" -gt 0 ]] && { echo "  baseline has $live live worker(s) - NOT seeding (half-written XMLs)"; return; }
    local have; have=$(find "$dest" -maxdepth 1 -name '*.xml' 2>/dev/null | wc -l)
    [[ "$have" -gt 0 ]] && { echo "  $dest already holds $have XMLs - not re-seeding"; return; }
    local n; n=$(find "$TS_PROC" -maxdepth 1 -name '*.xml' 2>/dev/null | wc -l)
    [[ "$n" -eq 0 ]] && { echo "  no baseline XMLs to seed from (fine for a from-scratch variant)"; return; }
    cp -p "$TS_PROC"/*.xml "$dest"/
    [[ -f "$TS_PROC/processed_items.json" ]] && cp -p "$TS_PROC/processed_items.json" "$dest"/
    echo "  seeded $n baseline XMLs into $dest"
}

# Later steps refuse a variant folder that alignment never wrote (that is how a "new alignment" silently becomes the old one)
require_variant_exists() {
    [[ -z "$VARIANT$INPUT_VARIANT" ]] && return
    [[ -d "$PROC_IN" ]] || { echo "ERROR: variant folder $PROC_IN does not exist - run 04 with the same --variant first" >&2; exit 1; }
}

# GPU count: Slurm's SLURM_GPUS_ON_NODE, else WARP_NGPU (set by submit_chain.sh for local runs), else the devices in
# CUDA_VISIBLE_DEVICES, else nvidia-smi, else 1. Device ids are 0..n-1 (CUDA renumbers visible devices).
resolve_devices() {
    local n="${SLURM_GPUS_ON_NODE:-${WARP_NGPU:-}}"
    if [[ -z "$n" && -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then n=$(echo "$CUDA_VISIBLE_DEVICES" | tr ',' '\n' | grep -c .); fi
    if [[ -z "$n" ]] && command -v nvidia-smi >/dev/null 2>&1; then n=$(nvidia-smi -L 2>/dev/null | grep -c '^GPU'); fi
    [[ "${n:-0}" -ge 1 ]] 2>/dev/null || n=1
    DEVICE_LIST=$(seq -s ' ' 0 $((n - 1)))
    PERDEVICE="${PERDEVICE:-2}"
    echo "  GPUs       : $n ($DEVICE_LIST) x $PERDEVICE workers each"
}

task_dir() { echo "$PROC_OUT/tasks_${1}_${SLURM_JOB_ID:-local$$}"; }   # job-unique: a stale manager holds the default lock

run_warp() {
    echo "  + $*"
    [[ "$DRY_RUN" -eq 1 ]] && { echo "  (dry run - not executed)"; return 0; }
    if [[ -f "$PROC_OUT/processed_items.json" && "${#SERIES_FLAGS[@]}" -gt 0 ]]; then
        cp -p "$PROC_OUT/processed_items.json" "$PROC_OUT/processed_items.json.bak_${SLURM_JOB_ID:-local$$}"
    fi
    "$@"
}

# Step 5 records what it did; step 6 refuses a folder whose hand was never checked (ordering: check BEFORE ts_ctf).
HAND_STATUS_FILE() { echo "${1:-$PROC_OUT}/hand_status.txt"; }
require_hand_checked() {      # checks the folder ts_ctf will READ ($PROC_IN)
    [[ "$DRY_RUN" -eq 1 || "$SKIP_HAND_CHECK" -eq 1 || -n "${AUTO_HAND:-}" ]] && return 0
    local f; f="$(HAND_STATUS_FILE "$PROC_IN")"
    if [[ ! -f "$f" ]]; then
        echo "ERROR: no $f: run step 5 (ts_defocus_hand --check, then the fix if needed) on this folder" >&2
        echo "       before ts_ctf, or pass --skip-hand-check / AUTO_HAND=N if the hand is already settled." >&2
        exit 1
    fi
    local last; last=$(tail -n 1 "$f"); echo "  hand       : $last"
    if [[ "$last" == *"mode=check"* && "$last" == *"verdict=flip"* ]]; then
        local nx ninv
        nx=$(find "$PROC_IN" -maxdepth 1 -name '*.xml' | wc -l)
        ninv=$(grep -l 'AreAnglesInverted="True"' "$PROC_IN"/*.xml 2>/dev/null | wc -l)
        if [[ "$ninv" -lt "$nx" ]]; then
            echo "ERROR: the last hand check said 'flip' but only $ninv/$nx XMLs are flipped. Show the user the check," >&2
            echo "       then run step 5 with --hand auto|flip (or --skip-hand-check if you deliberately keep it)." >&2
            exit 1
        fi
    fi
}

# Hand-off record ($PROJ/cryoet_project.json, keys in the cryoet-workflow skill's handoff reference). Never fatal.
ARM_NAME() { echo "${VARIANT:-${INPUT_VARIANT:-baseline}}"; }
record_state() {
    [[ "$DRY_RUN" -eq 1 || ! -f "$PROJ/cryoet_project.json" ]] && return 0
    "${CRYOET_PYTHON:-python3}" "$CRYOET_LIB/project_state.py" "$@" >/dev/null || echo "  WARN: project_state.py $1 $3 failed (record not updated)"
}
record_arm() {     # add {name, processing_dir, aligner} once per arm name
    [[ "$DRY_RUN" -eq 1 || ! -f "$PROJ/cryoet_project.json" ]] && return 0
    local arm; arm=$(ARM_NAME)
    "${CRYOET_PYTHON:-python3}" "$CRYOET_LIB/project_state.py" get "$PROJ" stages.warptools-preprocess.arms 2>/dev/null \
        | grep -q "\"name\": \"$arm\"" && return 0
    record_state add "$PROJ" stages.warptools-preprocess.arms "{\"name\": \"$arm\", \"processing_dir\": \"$PROC_OUT\", \"aligner\": \"$1\"}"
}

banner() {
    echo "=========================================================="
    echo " $1   [$(date)]  job ${SLURM_JOB_ID:-local$$} on $(hostname)"
    echo "=========================================================="
    echo "  processing : $PROC_LABEL"
    echo "  input      : $PROC_IN"
    echo "  output     : $PROC_OUT"
    echo "  series     : ${SERIES_LABEL:-all series}"
    [[ "$DRY_RUN" -eq 1 ]] && echo "  mode       : DRY RUN"
    echo ""
}
