#!/bin/bash
# Submit the tilt-series chain (steps 4-7) as dependent jobs, passing the SAME --variant/--series/--method/... to every
# step (the commonest silent failure is a later step reading the baseline instead of the variant).
#
#   scripts/submit_chain.sh [--from 4] [--to 5] [--gpus 2] [--time HH:MM:SS] [--mem 200G]
#                           [--hand check|auto|flip|noflip|switch] [--dry-run] [step options...]
# Partition / account / QoS / GPU request format come from the cryoet-skills config (cryoet_submit); nothing site-
# specific lives here. With SCHEDULER=none the steps run one after another in the foreground on this machine.
# --time: lower the per-job limit (templates default to 12 h) - e.g. before a maintenance window, when jobs pend with
#   'ReqNodeNotAvail, Reserved for maintenance'. Pending jobs can be fixed in place: scontrol update JobId=<id> TimeLimit=..
#
# ORDER (enforced): 04 align -> 05 ts_defocus_hand --check -> [user decides] -> 05 fix -> 06 ts_ctf -> 07 reconstruct.
# Default: 04 align -> 05 hand CHECK, then STOP so the hand decision is made from the check's output. Continue with
#   scripts/submit_chain.sh --from 5 --to 7 --hand auto   [same step options]   # set the hand, then CTF, reconstruct
#   scripts/submit_chain.sh --from 6 --to 7               [same step options]   # check said 'no flip' and XMLs agree
# Smoke test (one series end to end, into its own folder):
#   scripts/submit_chain.sh --to 7 --hand auto --series <ONE_SERIES> --variant smoketest
# Step options (warp_common.sh): --variant N --input-variant N --series a,b --method M --alignments DIR
#   --alignment-angpix A --patch-size A (take a value); --inverted --no-seed --skip-hand-check (flags).
set -eo pipefail
source __PROJ__/scripts/warp_params.sh
CRYOET_LIB="${CRYOET_LIB:-$PROJ/scripts/_lib}"
# shellcheck disable=SC1091
source "$CRYOET_LIB/cryoet_config.sh" || exit 2
export CRYOET_LIB
usage() { sed -n '2,21p' "$0"; }
need() { [[ $# -ge 2 && -n "$2" && "$2" != --* ]] || { echo "ERROR: $1 needs a value (see --help)" >&2; exit 1; }; }
FROM=4; TO=5; GPUS=2; HAND=check; PASS=(); DRY=0; TIME=""; MEM=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from|--to|--gpus|--hand|--time|--mem) need "$@" ;;&
    --from) FROM="$2"; shift 2 ;;
    --to)   TO="$2"; shift 2 ;;
    --gpus) GPUS="$2"; shift 2 ;;
    --hand) HAND="$2"; shift 2 ;;
    --time) TIME="$2"; shift 2 ;;
    --mem)  MEM="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    --variant|--input-variant|--series|--method|--alignments|--alignment-angpix|--patch-size)
      need "$@"; PASS+=("$1" "$2"); shift 2 ;;
    --inverted|--no-seed|--skip-hand-check) PASS+=("$1"); shift ;;
    *) echo "ERROR: unknown option '$1' (see --help)" >&2; exit 1 ;;
  esac
done
[[ "$FROM" =~ ^[4-7]$ && "$TO" =~ ^[4-7]$ && "$FROM" -le "$TO" ]] || { echo "ERROR: --from/--to must be 4..7, from <= to (run 01-03 directly)" >&2; exit 1; }
[[ "$GPUS" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: --gpus must be a positive integer" >&2; exit 1; }
if [[ -n "${SLURM_MAX_GPUS_PER_JOB:-}" && "$GPUS" -gt "$SLURM_MAX_GPUS_PER_JOB" ]]; then
  echo "ERROR: --gpus $GPUS > SLURM_MAX_GPUS_PER_JOB=$SLURM_MAX_GPUS_PER_JOB (config); a bigger request may pend forever" >&2; exit 1
fi
cryoet_have warp || { echo "ERROR: WarpTools is not configured (config key WARP_ENV_SCRIPT, or WarpTools on PATH)" >&2; exit 3; }
# hand ordering: --from 6/7 without a hand record is refused by 06 itself; warn here so nothing is queued in vain
if [[ "$FROM" -ge 6 && " ${PASS[*]} " != *" --skip-hand-check "* && -z "${AUTO_HAND:-}" ]]; then
  V=""; for ((i = 0; i < ${#PASS[@]}; i++)); do [[ "${PASS[$i]}" == --variant ]] && V="${PASS[$((i + 1))]}"; done
  D="${V:+$PROJ/$V}"; D="${D:-$TS_PROC}"
  [[ -f "$D/hand_status.txt" ]] || { echo "ERROR: $D/hand_status.txt missing: run --from 5 (hand check) first" >&2; exit 1; }
fi
mkdir -p "$PROJ/logs"
SCRIPTS=([4]=04_ts_align.sbatch [5]=05_ts_defocus_hand.sbatch [6]=06_ts_ctf.sbatch [7]=07_ts_reconstruct.sbatch)
DEP=""; IDS=()
for s in $(seq "$FROM" "$TO"); do
  sc="${SCRIPTS[$s]}"; name="${sc%.sbatch}"
  ARGS=("${PASS[@]}"); [[ "$s" == "5" ]] && ARGS+=(--hand "$HAND")
  NG=$GPUS; [[ "$s" == "5" ]] && NG=1
  if [[ "$SCHEDULER" == slurm ]]; then
    OPTS="-o $PROJ/logs/${name}_%j.out -e $PROJ/logs/${name}_%j.err${MEM:+ --mem=$MEM}${DEP:+ --dependency=afterok:$DEP}"
    if [[ "$DRY" == "1" ]]; then
      echo "CRYOET_SBATCH_OPTS=\"$OPTS\" cryoet_submit gpu $NG \"$TIME\" $PROJ/scripts/$sc ${ARGS[*]}"
      echo "    -> sbatch$(cryoet_sbatch_args gpu "$NG" "$TIME") $OPTS $PROJ/scripts/$sc ${ARGS[*]}"
      DEP="DRYRUN_$s"; continue
    fi
    JID=$(CRYOET_SBATCH_OPTS="$OPTS" cryoet_submit gpu "$NG" "$TIME" "$PROJ/scripts/$sc" "${ARGS[@]}")
    [[ "$JID" =~ ^[0-9]+ ]] || { echo "ERROR: submission of step $s failed: $JID" >&2; exit 1; }
    JID="${JID%%;*}"; IDS+=("$s:$JID"); DEP=$JID
    echo "submitted step $s ($sc) as job $JID ${ARGS[*]}"
  else
    LOG="$PROJ/logs/${name}_local$$.out"
    if [[ "$DRY" == "1" ]]; then echo "WARP_NGPU=$NG bash $PROJ/scripts/$sc ${ARGS[*]} > $LOG 2>&1"; continue; fi
    echo "running step $s ($sc) locally -> $LOG"
    rc=0; WARP_NGPU=$NG bash "$PROJ/scripts/$sc" "${ARGS[@]}" > "$LOG" 2>&1 || rc=$?
    tail -n 15 "$LOG"
    [[ $rc -eq 0 ]] || { echo "ERROR: step $s failed (rc=$rc); later steps not run. Log: $LOG" >&2; exit $rc; }
  fi
done
[[ "$DRY" == "1" || "$SCHEDULER" != slurm ]] || echo "chain: ${IDS[*]}   logs: $PROJ/logs/   status: squeue -h -j $(IFS=,; echo "${IDS[*]#*:}")"
