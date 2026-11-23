#!/bin/bash
#SBATCH --job-name=w_fs
#SBATCH --cpus-per-task=32
#SBATCH --mem=200G
#SBATCH --time=24:00:00
# Step 2 - frame series: motion + CTF (HAVE_FRAMES=1) or CTF only on single images per tilt (HAVE_FRAMES=0).
# The expensive step. --out_average_halves enables ts_reconstruct --halfmap_frames and denoiser training later.
# --c_grid 2x2x1 (>= 2x2x1 is needed by ts_defocus_hand). Resumable after preemption.
# Submit (GPUs/partition from the config):  cryoet_submit gpu 2 "" $PROJ/scripts/02_fs_motion_and_ctf.sbatch
# Locally (SCHEDULER=none):                 WARP_NGPU=2 bash $PROJ/scripts/02_fs_motion_and_ctf.sbatch
set -o pipefail
source __PROJ__/scripts/warp_params.sh   # absolute: sbatch runs a spooled copy of this script
source "$PROJ/scripts/warp_env.sh"
source "$PROJ/scripts/warp_common.sh"
cd "$PROJ" || exit 1
VARIANT=""; PROC_OUT="$FS_PROC"; DRY_RUN=0
PERDEVICE=${PERDEVICE:-3}; resolve_devices
TD="$FS_PROC/tasks_fs_${SLURM_JOB_ID:-local$$}"
echo "=== step 2 on $(hostname)  $(date)"
if [[ "$HAVE_FRAMES" == "1" ]]; then
  WarpTools fs_motion_and_ctf --settings "$FS_SETTINGS" --m_grid "$M_GRID" --c_grid "$C_GRID" \
    --c_range_max "$CTF_RANGE_HIGH" --c_defocus_min "$DEFOCUS_MIN" --c_defocus_max "$DEFOCUS_MAX" \
    --c_voltage "$VOLTAGE" --c_cs "$CS" --c_amplitude "$AMPLITUDE" --c_use_sum \
    --out_averages --out_average_halves --device_list $DEVICE_LIST --perdevice "$PERDEVICE" --task_dir "$TD" "$@"
  rc=$?
else
  WarpTools fs_ctf --settings "$FS_SETTINGS" --grid "$C_GRID" --range_max "$CTF_RANGE_HIGH" \
    --defocus_min "$DEFOCUS_MIN" --defocus_max "$DEFOCUS_MAX" --voltage "$VOLTAGE" --cs "$CS" \
    --amplitude "$AMPLITUDE" --device_list $DEVICE_LIST --perdevice "$PERDEVICE" --task_dir "$TD" "$@"
  rc=$?   # captured BEFORE any other command, so an fs_ctf failure fails the job (and stops afterok chains)
  echo "NOTE: no frames -> ts_import needs the tilt images visible in $FS_PROC/average/ (symlink them; see SKILL.md)"
fi
echo "rc=$rc"
echo "--- check: $(find "$FS_PROC" -maxdepth 1 -name '*.xml' | wc -l) frame-series XMLs; $(find "$FS_PROC/average" -maxdepth 1 -name '*.mrc' 2>/dev/null | wc -l) averages"
exit $rc
