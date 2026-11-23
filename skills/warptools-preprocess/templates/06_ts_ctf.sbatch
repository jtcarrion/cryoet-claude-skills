#!/bin/bash
#SBATCH --job-name=w_ctf
#SBATCH --cpus-per-task=32
#SBATCH --mem=200G
#SBATCH --time=12:00:00
# Step 6 - tilt-series CTF. MANDATORY after any new or imported alignment: the defocus fit is made against the geometry,
# so a variant carrying the baseline CTF is not a valid comparison. Same --variant/--series as step 4.
# ORDER: the hand must be checked (step 5, ts_defocus_hand --check, and fixed if needed) BEFORE this step. It refuses a
# folder with no hand_status.txt, or whose last check said 'flip' while its XMLs are unflipped. Alternatives:
# AUTO_HAND=N in the environment adds --auto_hand N (fits N series both ways, sets the hand, then fits CTF) - with ONE
# series it returns rc=0 but is weak: provisional. --skip-hand-check if the hand is settled some other way.
set -o pipefail
source __PROJ__/scripts/warp_params.sh   # absolute: sbatch runs a spooled copy of this script
source "$PROJ/scripts/warp_env.sh"
source "$PROJ/scripts/warp_common.sh"
cd "$PROJ" || exit 1
parse_common_args "$@"; resolve_processing; resolve_series; require_variant_exists
banner "Step 6 - tilt-series CTF"
require_hand_checked
resolve_devices
AH=(); [[ -n "${AUTO_HAND:-}" ]] && AH=(--auto_hand "$AUTO_HAND")
run_warp WarpTools ts_ctf --settings "$TS_SETTINGS" --window "$CTF_WINDOW" --range_low "$CTF_RANGE_LOW" \
  --range_high "$CTF_RANGE_HIGH" --defocus_min "$DEFOCUS_MIN" --defocus_max "$DEFOCUS_MAX" --voltage "$VOLTAGE" \
  --cs "$CS" --amplitude "$AMPLITUDE" "${AH[@]}" --device_list $DEVICE_LIST --perdevice "$PERDEVICE" \
  --task_dir "$(task_dir ctf)" "${PROC_FLAGS[@]}" "${SERIES_FLAGS[@]}"
rc=$?; echo "rc=$rc"
[[ "$DRY_RUN" -eq 0 ]] && echo "--- summary: ${CRYOET_PYTHON:-python3} $PROJ/scripts/qc_summary.py $PROC_OUT --cs $CS"
exit $rc
