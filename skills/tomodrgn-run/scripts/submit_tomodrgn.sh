#!/bin/bash
# submit_tomodrgn.sh - queue train_vae.sbatch / analyze.sbatch the site's way (config: partition, gres, account...).
#
#   submit_tomodrgn.sh train   [--gpus N] [--time T] [--mem M] [--log FILE] [--dry-run] KEY=VALUE ...
#   submit_tomodrgn.sh analyze [--time T] [--mem M] [--after JOBID] [--log FILE] [--dry-run] KEY=VALUE ...
#
# KEY=VALUE pairs are passed to the job script (see the header of train_vae.sbatch / analyze.sbatch).
# --time defaults: train 12:00:00, analyze 04:00:00 (override per run: epochs x minutes/epoch + load time + margin);
#   always capped at SLURM_MAX_WALLTIME from the config. --gpus default 1 (train), analyze always uses 1.
# --after JOBID: Slurm afterok dependency (analyze starts only if training succeeded). With SCHEDULER=none there are
#   no dependencies: pass RUN_ANALYZE=1 to the train call instead, which runs analyze in the same local job.
# --dry-run prints the sbatch command without submitting (show it to the user first).
# Prints the job id (slurm) or local:<pid> (SCHEDULER=none).
set -o pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
usage() { sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
case "${1:-}" in
  train) kind=train; script="$HERE/train_vae.sbatch"; t_def=12:00:00 ;;
  analyze) kind=analyze; script="$HERE/analyze.sbatch"; t_def=04:00:00 ;;
  -h|--help|"") usage; exit 0 ;;
  *) echo "first argument must be train or analyze" >&2; usage >&2; exit 2 ;;
esac
shift
gpus=1; t=""; mem=""; after=""; log=""; dry=0; kv=()
while [ $# -gt 0 ]; do
  case "$1" in
    --gpus) gpus="$2"; shift 2 ;;
    --time) t="$2"; shift 2 ;;
    --mem) mem="$2"; shift 2 ;;
    --after) after="$2"; shift 2 ;;
    --log) log="$2"; shift 2 ;;
    --dry-run) dry=1; shift ;;
    -h|--help) usage; exit 0 ;;
    [A-Z]*=*) kv+=("$1"); shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ "$kind" = analyze ] && gpus=1
source "$HERE/_lib/cryoet_config.sh" || exit 2
if ! cryoet_have tomodrgn; then
  echo "tomoDRGN is not configured (TOMODRGN_ENV empty and no tomodrgn on PATH)." >&2
  echo "Install it (https://github.com/bpowell122/tomodrgn), then set TOMODRGN_ENV in $CRYOET_SKILLS_CONFIG." >&2
  exit 3
fi
export CRYOET_LIB="$HERE/_lib"

# walltime -> seconds; accepts [D-]HH:MM:SS, HH:MM, MM
secs() {
  local v="$1" d=0 h=0 m=0 s=0
  case "$v" in *-*) d="${v%%-*}"; v="${v#*-}" ;; esac
  IFS=: read -r a b c <<< "$v"
  if [ -n "$c" ]; then h=$a; m=$b; s=$c; elif [ -n "$b" ]; then h=$a; m=$b; else m=$a; fi
  echo $(( 10#${d:-0} * 86400 + 10#${h:-0} * 3600 + 10#${m:-0} * 60 + 10#${s:-0} ))
}
t="${t:-$t_def}"
if [ -n "${SLURM_MAX_WALLTIME:-}" ] && [ "$(secs "$t")" -gt "$(secs "$SLURM_MAX_WALLTIME")" ]; then
  echo "note: --time $t exceeds SLURM_MAX_WALLTIME; capped to $SLURM_MAX_WALLTIME" >&2
  t="$SLURM_MAX_WALLTIME"
fi
if [ -n "${SLURM_MAX_GPUS_PER_JOB:-}" ] && [ "$gpus" -gt "$SLURM_MAX_GPUS_PER_JOB" ]; then
  echo "ERROR: --gpus $gpus > SLURM_MAX_GPUS_PER_JOB=$SLURM_MAX_GPUS_PER_JOB" >&2; exit 2
fi

opts="--export=ALL"
[ -n "$mem" ] && opts="$opts --mem=$mem"
[ -n "$log" ] && opts="$opts --output=$log"
if [ -n "$after" ]; then
  if [ "$SCHEDULER" = slurm ]; then opts="$opts --dependency=afterok:$after"
  else echo "ERROR: --after needs SCHEDULER=slurm; use RUN_ANALYZE=1 on the train call instead" >&2; exit 2; fi
fi
export CRYOET_SBATCH_OPTS="${CRYOET_SBATCH_OPTS:-} $opts"
if [ "$dry" = 1 ]; then
  if [ "$SCHEDULER" = slurm ]; then
    echo "sbatch --parsable $(cryoet_sbatch_args gpu "$gpus" "$t") $CRYOET_SBATCH_OPTS $script ${kv[*]}"
  else
    echo "bash $script ${kv[*]}   (SCHEDULER=none, background)"
  fi
  exit 0
fi
cryoet_submit gpu "$gpus" "$t" "$script" "${kv[@]}"
