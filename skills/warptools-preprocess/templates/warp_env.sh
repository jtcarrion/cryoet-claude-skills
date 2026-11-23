#!/bin/bash
# Project environment. SOURCE it after warp_params.sh (never execute).
# Loads the cryoet-skills config through the shared library and puts WarpTools (+ IMOD / AreTomo3 when configured:
# IMOD_DIR, ARETOMO3_BIN) on PATH with `cryoet_activate warp`. Batch jobs run a non-login shell that never reads
# ~/.bashrc, so this explicit activation is what makes tiltalign / AreTomo3 visible to ts_etomo_* / ts_aretomo3.
# CRYOET_LIB: exported by cryoet_submit; otherwise the copy init_project.sh put in $PROJ/scripts/_lib.
CRYOET_LIB="${CRYOET_LIB:-$PROJ/scripts/_lib}"
# shellcheck disable=SC1091
source "$CRYOET_LIB/cryoet_config.sh" || { echo "ERROR: cannot load $CRYOET_LIB/cryoet_config.sh" >&2; exit 2; }
export CRYOET_LIB
cryoet_activate warp || { echo "ERROR: WarpTools could not be activated (config key WARP_ENV_SCRIPT)" >&2; exit 2; }
# Warp writes many small temp files; keep them off $HOME (a job-provided TMPDIR is kept)
export TMPDIR="${TMPDIR:-${WARP_DIR:-$PWD}/tmp}"
mkdir -p "$TMPDIR"
