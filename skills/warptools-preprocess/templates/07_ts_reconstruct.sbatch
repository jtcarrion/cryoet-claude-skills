#!/bin/bash
#SBATCH --job-name=w_recon
#SBATCH --cpus-per-task=32
#SBATCH --mem=300G
#SBATCH --time=12:00:00
# Step 7 - reconstruct tomograms at RECON_ANGPIX with deconvolved copies and half-tomograms.
# Contrast: default --dont_invert (dark density on white, for looking/segmentation). --inverted (bright on dark) is
# what ts_template_match needs; polarity is baked into the .mrc and an inverted run OVERWRITES the viewing volumes in
# the same reconstruction/ folder -> give it its own --variant. NB this --dont_invert is CONTRAST; ts_import's is
# tilt-angle sign. No --keep_full_voxels if you will template match.
# Halves: --halfmap_frames (needs fs --out_average_halves) or --halfmap_tilts (no frames). Frame-split half-maps share
# one alignment, so their FSC is BLIND to alignment error (a deliberate shift perturbation barely moves it); to compare
# alignments use odd/even tilts (--halfmap_tilts) and, ultimately, downstream STA resolution.
set -o pipefail
source __PROJ__/scripts/warp_params.sh   # absolute: sbatch runs a spooled copy of this script
source "$PROJ/scripts/warp_env.sh"
source "$PROJ/scripts/warp_common.sh"
cd "$PROJ" || exit 1
parse_common_args "$@"; resolve_processing; resolve_series; require_variant_exists
banner "Step 7 - reconstruct"
PERDEVICE=${PERDEVICE:-1}; resolve_devices
POL=(--dont_invert); [[ "$INVERTED" == "1" || "$INVERT_TOMOGRAMS" == "1" ]] && POL=()
HALF=(--halfmap_frames); [[ "$HAVE_FRAMES" != "1" || -n "${HALFMAP_TILTS:-}" ]] && HALF=(--halfmap_tilts)
run_warp WarpTools ts_reconstruct --settings "$TS_SETTINGS" --angpix "$RECON_ANGPIX" --deconv "${HALF[@]}" "${POL[@]}" \
  --device_list $DEVICE_LIST --perdevice "$PERDEVICE" --task_dir "$(task_dir recon)" \
  "${PROC_FLAGS[@]}" "${SERIES_FLAGS[@]}"
rc=$?; echo "rc=$rc"
[[ $rc -eq 0 ]] && record_state set "$PROJ" "stages.warptools-preprocess.tomograms.$(ARM_NAME)" \
  "{\"dir\": \"$PROC_OUT/reconstruction\", \"angpix\": $RECON_ANGPIX, \"polarity\": \"${POL[*]:-inverted}\"}"
[[ "$DRY_RUN" -eq 0 ]] && echo "--- $(find "$PROC_OUT/reconstruction" -maxdepth 1 -name '*.mrc' 2>/dev/null | wc -l) tomograms in $PROC_OUT/reconstruction (polarity: ${POL[*]:-inverted})"
exit $rc
