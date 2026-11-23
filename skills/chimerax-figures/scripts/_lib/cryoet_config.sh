# cryoet_config.sh -- shared config loader for the cryoet-skills plugin.  SOURCE it; do not execute.
# CANONICAL COPY: lib/cryoet_config.sh. Each skill vendors it as scripts/_lib/cryoet_config.sh (tools/sync_lib.sh).
# Works under bash 4+; safe without `set -u` (but tolerates it). No GNU-only flags.
#
# Usage in a skill script / sbatch body:
#   source "$CRYOET_LIB/cryoet_config.sh" || exit 2      # CRYOET_LIB = <skill>/scripts/_lib, exported by the submitter
#   cryoet_require CRYOET_PYTHON WARP_ENV_SCRIPT
#   cryoet_activate warp
# Usage from Claude (interactive shell):
#   source <skill>/scripts/_lib/cryoet_config.sh && cryoet_submit gpu 2 04:00:00 my.sbatch arg1

CRYOET_SKILLS_CONFIG="${CRYOET_SKILLS_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/cryoet-skills/config.sh}"
if [ -f "$CRYOET_SKILLS_CONFIG" ]; then
  # shellcheck disable=SC1090
  source "$CRYOET_SKILLS_CONFIG"
else
  echo "cryoet-skills: no config at $CRYOET_SKILLS_CONFIG -- run the cryoet-workflow skill's setup first" >&2
  return 2 2>/dev/null || exit 2
fi
_cryoet_gres_default='gpu:{n}'   # via a variable: a literal } inside ${VAR:=...} would end the expansion early
: "${SCHEDULER:=slurm}" "${SLURM_GPU_GRES_FMT:=$_cryoet_gres_default}" "${SCRATCH_ROOT:=/tmp}" "${MCORE_PORT_BASE:=14300}"
: "${RELION_MPI_LAUNCHER:=mpirun}" "${JOLT_ENABLED:=no}" "${CHIMERAX_STYLE:=default}"
export CRYOET_SKILLS_CONFIG

cryoet_die() { echo "cryoet-skills: $*" >&2; return 1; }

# cryoet_require KEY [KEY...] : fail (rc 3) naming every empty key.
cryoet_require() {
  local k missing=""
  for k in "$@"; do [ -n "${!k:-}" ] || missing="$missing $k"; done
  [ -z "$missing" ] && return 0
  echo "cryoet-skills: required config key(s) empty:$missing  (edit $CRYOET_SKILLS_CONFIG or re-run setup)" >&2
  return 3
}

# cryoet_have STAGE : 0 if the optional stage's software is configured. Stages:
#   warp relion m tomodrgn teamtomo chimerax aretomo3 imod noise2map calc_level jolt
cryoet_have() {
  case "$1" in
    warp|m)    [ -n "${WARP_ENV_SCRIPT:-}" ] || command -v WarpTools >/dev/null 2>&1 ;;
    relion)    [ -n "${RELION_ENV_SCRIPT:-}" ] || command -v relion_refine_mpi >/dev/null 2>&1 ;;
    tomodrgn)  [ -n "${TOMODRGN_ENV:-}" ] || command -v tomodrgn >/dev/null 2>&1 ;;
    teamtomo)  [ -n "${TEAMTOMO_REPO:-}" ] && [ -d "${TEAMTOMO_REPO}" ] ;;
    chimerax)  [ -n "${CHIMERAX_BIN:-}" ] ;;   # usually on the user's laptop: configured != present here
    aretomo3)  [ -n "${ARETOMO3_BIN:-}" ] || command -v AreTomo3 >/dev/null 2>&1 ;;
    imod)      [ -n "${IMOD_DIR:-}" ] || command -v tiltalign >/dev/null 2>&1 ;;
    noise2map) [ -n "${NOISE2MAP_BIN:-}" ] ;;
    calc_level) [ -n "${CALC_LEVEL_REPO:-}" ] && [ -d "${CALC_LEVEL_REPO}" ] ;;
    jolt)      [ "${JOLT_ENABLED}" = yes ] ;;
    *) cryoet_die "cryoet_have: unknown stage '$1'" ;;
  esac
}

# _cryoet_source_env FILE_OR_CMD : FILE is sourced; a value starting with "conda:" or "module:" is activated.
_cryoet_source_env() {
  local v="$1"
  case "$v" in
    "") return 0 ;;
    conda:*) local e="${v#conda:}"
       if command -v conda >/dev/null 2>&1; then
         eval "$(conda shell.bash hook 2>/dev/null)" && conda activate "$e"
       elif [ -d "$e/bin" ]; then
         # batch shells often lack conda on PATH: use the env's own conda.sh, else put its bin/ first
         local base; base="$(cd "$e/../.." 2>/dev/null && pwd)"
         if [ -f "$base/etc/profile.d/conda.sh" ]; then source "$base/etc/profile.d/conda.sh" && conda activate "$e"
         else export PATH="$e/bin:$PATH" CONDA_PREFIX="$e"; fi
       else
         cryoet_die "conda not on PATH and '$e' is not an env directory (use conda:/full/path/to/env)"; return 1
       fi ;;
    venv:*)  source "${v#venv:}/bin/activate" ;;
    module:*) module load ${v#module:} ;;
    *) [ -f "$v" ] || { cryoet_die "env script not found: $v"; return 1; }
       local had_u=0; case $- in *u*) had_u=1; set +u ;; esac   # conda/env scripts break under set -u
       source "$v"; local rc=$?
       [ $had_u = 1 ] && set -u
       return $rc ;;
  esac
}

# cryoet_activate STAGE : put that stage's software on PATH (warp also brings IMOD/AreTomo3 if configured).
cryoet_activate() {
  case "$1" in
    warp|m)
      _cryoet_source_env "${WARP_ENV_SCRIPT:-}" || return 1
      if [ -n "${IMOD_DIR:-}" ]; then export IMOD_DIR; [ -f "$IMOD_DIR/IMOD-linux.sh" ] && source "$IMOD_DIR/IMOD-linux.sh"; fi
      [ -n "${ARETOMO3_BIN:-}" ] && export PATH="$(dirname "$ARETOMO3_BIN"):$PATH"
      [ -n "${EXTRA_LD_LIBRARY_PATH:-}" ] && export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$EXTRA_LD_LIBRARY_PATH"
      command -v WarpTools >/dev/null 2>&1 || { cryoet_die "WarpTools not on PATH after activation"; return 1; } ;;
    relion)   _cryoet_source_env "${RELION_ENV_SCRIPT:-}" || return 1
              command -v relion_refine_mpi >/dev/null 2>&1 || { cryoet_die "relion_refine_mpi not on PATH"; return 1; } ;;
    tomodrgn) _cryoet_source_env "${TOMODRGN_ENV:-}" || return 1
              command -v tomodrgn >/dev/null 2>&1 || { cryoet_die "tomodrgn not on PATH"; return 1; } ;;
    teamtomo) _cryoet_source_env "${TEAMTOMO_ENV:-}" ;;
    *) cryoet_die "cryoet_activate: unknown stage '$1'" ;;
  esac
}

# cryoet_gres N : the --gres value for N GPUs in this site's format ("" if N=0).
cryoet_gres() {
  local n="$1" f="$SLURM_GPU_GRES_FMT"
  [ "${n:-0}" -gt 0 ] 2>/dev/null || { echo ""; return 0; }
  f="${f//\{n\}/$n}"; f="${f//\{type\}/${SLURM_GPU_TYPE:-}}"; f="${f//::/:}"
  echo "$f"
}

# cryoet_sbatch_args KIND NGPU [TIME] : prints sbatch options. KIND = gpu | cpu.
cryoet_sbatch_args() {
  local kind="$1" ngpu="${2:-0}" t="${3:-}" a=""
  local part="$SLURM_GPU_PARTITION"; [ "$kind" = cpu ] && part="${SLURM_CPU_PARTITION:-$SLURM_GPU_PARTITION}"
  [ -n "$part" ] && a="$a --partition=$part"
  [ -n "${SLURM_ACCOUNT:-}" ] && a="$a --account=$SLURM_ACCOUNT"
  [ -n "${SLURM_QOS:-}" ] && a="$a --qos=$SLURM_QOS"
  [ "$kind" = gpu ] && [ "$ngpu" -gt 0 ] && a="$a --gres=$(cryoet_gres "$ngpu")"
  [ -n "$t" ] && a="$a --time=$t"
  [ -n "${SLURM_EXTRA_ARGS:-}" ] && a="$a $SLURM_EXTRA_ARGS"
  echo "$a"
}

# cryoet_submit KIND NGPU TIME SCRIPT [ARGS...] [-- extra sbatch opts via CRYOET_SBATCH_OPTS env]
#   slurm : sbatch <site args> $CRYOET_SBATCH_OPTS SCRIPT ARGS   -> prints job id
#   none  : runs SCRIPT with bash in the background, log in ./<script>.<pid>.log -> prints "local:<pid>"
# --export=ALL so CRYOET_LIB survives sites that set SBATCH_EXPORT=NONE. Exports CRYOET_LIB so the job body can re-source this file (sbatch copies the script to a spool dir).
cryoet_submit() {
  local kind="$1" ngpu="$2" t="$3" script="$4"; shift 4
  export CRYOET_LIB="${CRYOET_LIB:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
  if [ "$SCHEDULER" = slurm ]; then
    # shellcheck disable=SC2046
    sbatch --parsable --export=ALL $(cryoet_sbatch_args "$kind" "$ngpu" "$t") ${CRYOET_SBATCH_OPTS:-} "$script" "$@"
  else
    local log; log="$(basename "$script").$$.log"
    nohup bash "$script" "$@" > "$log" 2>&1 &
    echo "local:$! (log $log)"
  fi
}

# cryoet_use_scratch [TAG] : make a job-unique scratch dir under SCRATCH_ROOT, set $SCR to it and remove it when
#   the calling shell exits. Call it directly (NOT inside $(...): a trap set in a subshell fires immediately).
#   Chains onto an existing EXIT trap instead of replacing it.
cryoet_use_scratch() {
  SCR="$(cryoet_scratch "${1:-job}")" || return 1
  local prev; prev="$(trap -p EXIT | sed -e "s/^trap -- '//" -e "s/' EXIT\$//")"
  # shellcheck disable=SC2064
  trap "rm -rf '$SCR'; ${prev:-:}" EXIT
  export SCR
}

# cryoet_scratch [TAG] : create a job-unique scratch dir and print its path. NO cleanup is registered (it cannot be
#   from inside $(...)); prefer cryoet_use_scratch, or add your own `trap 'rm -rf "$DIR"' EXIT`.
cryoet_scratch() {
  mktemp -d "${SCRATCH_ROOT%/}/cryoet_${1:-job}_${SLURM_JOB_ID:-$$}_XXXXXX"
}

# cryoet_port : a per-job TCP port (MCore/REST) so two jobs on one node do not collide.
cryoet_port() { echo $(( MCORE_PORT_BASE + ( ${SLURM_JOB_ID:-$$} % 997 ) )); }

# cryoet_mpirun NP CMD... : launch MPI the site's way.
cryoet_mpirun() {
  local np="$1"; shift
  if [ "$RELION_MPI_LAUNCHER" = srun ]; then srun -n "$np" "$@"; else mpirun -n "$np" "$@"; fi
}
