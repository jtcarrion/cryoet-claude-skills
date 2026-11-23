# Conventions every skill follows

Target user: anyone, any Slurm HPC (or a workstation with `SCHEDULER=none`). No assumption about this lab's cluster.

## 1. Config, never hardcode
- Site/user values come from the config (`config/config.example.sh` documents every key). Scripts load it with
  `source "$CRYOET_LIB/cryoet_config.sh" || exit 2` (sbatch bodies; `CRYOET_LIB` is exported by `cryoet_submit`) or
  `source "${CLAUDE_SKILL_DIR}/scripts/_lib/cryoet_config.sh"` (commands in SKILL.md).
- Python helpers: `sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_lib"))` then
  `import cryoet_config as cc` / `import starlite`. Run them with `"$CRYOET_PYTHON"`. Shebang `#!/usr/bin/env python3`.
  Stdlib-only helpers must run on Python 3.6; numpy/mrcfile helpers may assume 3.8+.
- Need a key that is not in config.example.sh? Use `${KEY:-sensible_default}` in the script and LIST it in your report
  (the lead adds it to the schema). Do not edit lib/, tools/, config/ or another skill's directory.
- Software env: `cryoet_activate warp|relion|tomodrgn|teamtomo` -- never `source /abs/path/env.sh`.
- Optional software: check `cryoet_have <stage>` first; if missing, say so and skip that step (or the whole skill) cleanly.
- Microscope constants (Cs, kV, amp. contrast) come from the data (Warp XML / STAR / mdoc) or a CLI flag, else
  `MICROSCOPE_CS_MM`; never a literal 2.7.

## 2. Slurm
- `#SBATCH` lines may only carry site-neutral options: `--job-name --output --error --cpus-per-task --mem --ntasks
  --nodes --time`(default only). Partition, account, QoS, gres, nodelist/exclude come from `cryoet_submit KIND NGPU TIME
  script args` (or `cryoet_sbatch_args`). Never a typed gres; never a node name.
- Every job script must also run under `SCHEDULER=none` (`bash script.sbatch args`): don't rely on SLURM_* vars
  without a fallback (`${SLURM_CPUS_PER_TASK:-$(nproc)}`, `${SLURM_JOB_ID:-$$}`).
- Scratch: `cryoet_use_scratch tag` (sets `$SCR`, job-unique, removed on exit; call it directly, not in `$(...)`). MCore/REST ports: `--port $(cryoet_port)`.
  MPI: `cryoet_mpirun NP cmd...`.
- Exit codes must be honest: capture `rc` before any `set -e` can swallow it; a failed tool must fail the job.

## 3. SKILL.md layout (< 500 lines; frontmatter `name` == dir; description <= 1536 chars, generic wording)
1. One-paragraph purpose.  2. **Setup check** (load config, `cryoet_require`, `cryoet_have`, what to do if missing).
3. **Inputs / Outputs (handoff)** -- a table: artifact, path pattern, produced/consumed, by which skill. The
   cryoet-workflow director reads this.  4. Procedure.  5. General rules (the hard-won lessons, stated generally).
6. Pointers to references/.
Refer to other skills by bare name (`relion-refine`), never by path or `plugin:` prefix.

## 4. Knowledge
- Keep every hard-won lesson, but state it as a general rule with the *symptom* and *check* ("if X, you will see Y;
  check with Z"). Dataset specifics go to `references/worked-example-empiar10499.md`: short, public facts only
  (EMPIAR-10499 / EMD-11650 / EMPIAR-11843 are public), light on result numbers.
- Remove: internal (unpublished) lab datasets and their numbers, /orcd paths, node names, lab-only script names that are not
  shipped (replace with what the step does, or ship it).
- JOLT (unreleased-preprint picker): keep as optional, gated on `cryoet_have jolt`, marked `<!-- TODO(jolt-preprint) -->`.
- `lint: allow` at end of a line suppresses tools/lint.py for that line -- use only for documented examples.

## 5. Evals (claude plugin eval format) in `evals/<skill>-<case>/`
`prompt.md` (frontmatter: `max_turns`, `allowed_tools`, `timeout_seconds`, `tags: [<skill>]`; body = a realistic
generic user request), `graders/skill-fired.md` (`type: tool_used`, `tool: Skill`,
`input_match: '"skill"\s*:\s*"(?:[\w-]+:)?<skill>"'`) and `graders/criteria.md` (`type: llm`, PASS/FAIL rubric on the
expected behaviour, e.g. "asks for / reads pixel size from mdoc", "uses cryoet_submit, no hardcoded partition",
"skips cleanly when tomodrgn is not configured"). 3-5 cases per skill, including one "tool not installed" case.
Evals must not need cluster data or submit jobs.

## 6. Done means
`python3 tools/lint.py` shows 0 errors for your skill's files; every script `--help` works (or `bash -n`); the
audit's bug list for your skill (audit/<skill>.md) is fixed or explicitly deferred with a reason.
