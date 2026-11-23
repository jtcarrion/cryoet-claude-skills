#!/bin/bash
#SBATCH --job-name=w_hand
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=01:00:00
# Step 5 - defocus handedness. ORDER: after alignment (04), BEFORE ts_ctf (06) - the CTF fit uses the hand.
# Default --hand check: REPORT only, change nothing.
#   "Average correlation: +0.93 ... should be set to 'no flip'"  -> positive = no flip; negative = flip needed.
# Then, only if the user agrees: --hand auto (determine + set for all series) | flip | noflip | switch.
# Uses the frame-series defocus gradient (needs fs --c_grid >= 2x2x1).
# Writes $PROC_OUT/hand_status.txt (one line per run); step 06 refuses a folder without it, and refuses a folder
# whose last check said 'flip' while its XMLs are not flipped.
# LIMIT: this validates the per-tilt defocus GRADIENT under the ts_import angle convention, not the absolute hand of
# the final map. Check the map hand downstream against an atomic model or reference map.
set -o pipefail
source __PROJ__/scripts/warp_params.sh   # absolute: sbatch runs a spooled copy of this script
source "$PROJ/scripts/warp_env.sh"
source "$PROJ/scripts/warp_common.sh"
cd "$PROJ" || exit 1
parse_common_args "$@"; resolve_processing; resolve_series; require_variant_exists
banner "Step 5 - defocus handedness (--hand $HAND_MODE)"
case "$HAND_MODE" in
  check) F=--check ;; auto) F=--set_auto ;; flip) F=--set_flip ;; noflip) F=--set_noflip ;; switch) F=--set_switch ;;
  *) echo "ERROR: --hand check|auto|flip|noflip|switch" >&2; exit 1 ;;
esac
LOG="$PROC_OUT/hand_${HAND_MODE}_${SLURM_JOB_ID:-local$$}.log"
[[ "$DRY_RUN" -eq 1 ]] && LOG=/dev/null
mkdir -p "$PROC_OUT"
run_warp WarpTools ts_defocus_hand --settings "$TS_SETTINGS" "$F" "${PROC_FLAGS[@]}" "${SERIES_FLAGS[@]}" 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}; echo "rc=$rc"
if [[ "$DRY_RUN" -eq 0 && $rc -eq 0 ]]; then
  corr=$(grep -o 'Average correlation: *[-+0-9.eE]*' "$LOG" | tail -n 1 | awk '{print $NF}')
  verdict=$(grep -io "should be set to '[a-z ]*'" "$LOG" | tail -n 1 | sed "s/.*'\(.*\)'/\1/")
  echo "$(date +%F_%T) mode=$HAND_MODE corr=${corr:-?} verdict=${verdict:-?} series=${SERIES:-all} import_dont_invert=${TS_IMPORT_DONT_INVERT:-0}" \
    >> "$(HAND_STATUS_FILE)"
  [[ "$HAND_MODE" != check ]] && record_state add "$PROJ" decisions \
    "{\"what\": \"defocus hand ($(ARM_NAME))\", \"choice\": \"$HAND_MODE\", \"evidence\": \"ts_defocus_hand corr=${corr:-?} verdict=${verdict:-?}; ts_import dont_invert=${TS_IMPORT_DONT_INVERT:-0}\", \"date\": \"$(date +%F)\"}"
  echo "--- recorded in $(HAND_STATUS_FILE): $(tail -n 1 "$(HAND_STATUS_FILE)")"
  echo "--- AreAnglesInverted across XMLs (True = flipped):"
  grep -ho 'AreAnglesInverted="[A-Za-z]*"' "$PROC_OUT"/*.xml 2>/dev/null | sort | uniq -c
fi
exit $rc
