---
name: cryoet-workflow
description: Director for cryo-ET subtomogram averaging with the cryoet-skills plugin - first-time setup of the per-user/site config (detects Slurm partitions, GPU syntax, installed WarpTools/RELION/M/tomoDRGN/TeamTomo/ChimeraX, a usable Python), a status check of which stages can run on this machine, planning a pipeline from raw tilt series or an existing project to a final map and figures, and running it stage by stage by handing each stage to a subagent that loads the matching skill (warptools-preprocess, teamtomo-preprocess, relion-refine, m-refine, tomodrgn-run, chimerax-figures), keeping a project handoff record so stages know what upstream produced. Use this whenever the user wants to set up or configure the cryo-ET skills, asks what the skills can do here, wants to process a dataset end to end ("take this EMPIAR entry to a map"), asks what to run next, resumes a project, or wants several stages coordinated - even if they only say "set me up", "run the whole pipeline" or "where are we on this project".
---

# cryo-ET workflow director

This skill does not run processing itself. It (1) makes sure the user's config exists and is right, (2) works out
which stages this machine can run, (3) plans the pipeline with the user, and (4) dispatches each stage to a subagent
that loads that stage's skill, checking the hand-off between stages. Scripts: `S=${CLAUDE_SKILL_DIR}/scripts`.

## 0. Always first

> **No shell or restricted permissions?** Read `~/.config/cryoet-skills/config.sh` (or `$CRYOET_SKILLS_CONFIG`)
> directly and apply the same checks to its keys (empty = not installed: stop as described below). Say the live
> check was not run, then keep going: give the exact commands and draft the files inline, with named placeholders for
> values you could not read. Never stop at a prose promise ("I'll calculate ...").

1. If the site has published rules (a message of the day, a policy file, `SITE_NOTES_FILE` in the config), read them
   before submitting anything and respect them (quotas, maintenance windows, login-node limits).
2. `bash $S/check_config.sh`. Exit 2 = no config: go to **Setup**. Any `FAIL` row: fix that key with the user before
   running that stage. `skip` rows are stages whose software is not installed: they are simply left out of plans.

## 1. Setup (first run, or "reconfigure") - Part 1 of `references/intake.md`
**How to ask.** Use AskUserQuestion (up to 4 questions per call, the detected value first, marked "(detected)"). If
that tool is unavailable (headless `-p` runs), end your turn with the questions as a numbered list - id, question,
detected value, options - and wait for the answers. Ask only what detection could not settle.
1. Detect: `python3 $S/setup_config.py --detect` (runs the read-only `detect_env.py` probe: `sinfo`, `command -v`,
   conda env dirs, a python import test; prints the proposed config as a diff, writes nothing).
2. Ask questions A1-A7, B1-B5 of `references/intake.md` that are still open. A4 (GPU request syntax) and A6 (scratch)
   always need the user. A tool the user does not have stays empty - that is a valid answer, not a blocker. Env
   values may be an env script path, `conda:<name-or-path>`, `venv:<path>` or `module:<name>`.
3. Write: `python3 $S/setup_config.py --detect --set KEY=VALUE ... --write` (or `--answers answers.json`). It starts
   from the existing config, shows a diff, backs the old file up and refuses unknown keys. Default location
   `~/.config/cryoet-skills/config.sh`; `CRYOET_SKILLS_CONFIG=/path` (exported in the user's shell profile) moves it.
4. `bash $S/check_config.sh` and show the table. A FAIL row goes back to its question. Installing missing software is
   out of scope unless the user asks; `references/setup.md` has install pointers.

## 1b. Project intake (once per dataset) - Part 2 of `references/intake.md`
1. Ask C1-C3 (project dir, raw data locations, name). List the data dirs to confirm counts (mdocs, movies, gain).
2. Pre-fill acquisition: `"$CRYOET_PYTHON" $S/_lib/inspect_mdoc.py --mdocs <dir> --frames <dir> --json`. Show the
   values and EVERY warning, then ask D1-D8 as confirmations. A "TRANSPOSED" warning means the MDOC tilt axis is
   probably 90 deg off: say so, and plan to verify on one series before the batch. Voltage/Cs/amplitude contrast are
   often absent from MDOCs: ask. If the user does not know the gain orientation, plan a one-series test.
3. Ask E1-E5 and F1-F2 (target, particles - picking is not covered -, reference, how far, test subset, budget,
   approval style). Offer only stages that `check_config.sh` marks ok.
4. Record: `python3 $S/_lib/project_state.py init <PROJECT> --dataset <name> --angpix .. --kv .. --cs .. --amp ..
   --dose_per_tilt ..`, then `set <PROJECT> intake '<json of all answers>'` and `set <PROJECT> plan '<json>'`.
5. Summarise the plan back in one table (stage, inputs, compute, the decision gates G1-G6 it will stop at) and get
   an explicit yes before the first submission.

## 2. Status / "what can I do here"
Show the `check_config.sh` table, and if a project is given, `python3 $S/_lib/project_state.py get <PROJECT>` and
`check` (missing paths). Summarise: done stages, the latest particle set and map (with particle counts and
resolution as recorded), and the next sensible stage.

## 3. Plan
Agree the plan with the user before any compute. The stage graph and what each needs is in `references/pipeline.md`:

    raw movies+mdocs ─▶ warptools-preprocess ─┬─▶ (particle picking: external) ─▶ relion-refine ─▶ m-refine ─▶ chimerax-figures
                       teamtomo-preprocess ───┘                                    │      ▲
                                                                     tomodrgn-run ─┘      └─ relion-refine (subset)
- Leave out stages whose software is `skip`. tomoDRGN, TeamTomo, M and ChimeraX are all optional; the minimum
  useful chain is warptools-preprocess -> relion-refine.
- **Picking is not covered by these skills.** Ask the user for a coordinate STAR (from template matching, crYOLO,
  topaz, a published set, ...) and its pixel size. <!-- TODO(jolt-preprint): add jolt-picker stage when JOLT is released. -->
- Write the plan into the project record: `python3 $S/_lib/project_state.py init <PROJECT> --dataset <name> [--angpix ...]` then
  `set <PROJECT> plan '<json list of stages>'`.
- State the compute for each stage (GPUs x hours, disk) and get a yes before submitting.

## 4. Run a stage (dispatch)
One stage per subagent, so each skill's long instructions and tool output stay out of this conversation.
- Plugin install: use the agent `cryoet-skills:<stage>` if it is available (it preloads that skill).
- Otherwise spawn a general-purpose subagent whose prompt starts: "Load the `<stage>` skill with the Skill tool and
  follow it." Then give: the project path, `cryoet_project.json` location, the exact inputs from the record, the
  user's choices, the compute the user approved, and what to return.
- Ask every stage subagent to return: what it submitted (job ids), what it produced (paths), checks it ran with their
  numbers (raw counts, not just percentages), anything it could not decide, and to record its outputs with
  `project_state.py set/add` (schema in `references/handoff.md`).
- Long Slurm jobs: the subagent submits, verifies the job started, records the job id and returns. NEVER keep a
  subagent (or yourself) polling a queue: in the end-to-end test one turn that waited ~2 h for a go/no-go iteration
  cost as much as ten normal turns. Mid-run checks (go/no-go at iteration N) belong in a cheap Slurm dependency job or
  shell watcher that writes a verdict file; read it on the next turn. Tell the user what to come back and ask.
- Every stage subagent must END with a checklist: "Submitted: <job ids>. Prepared but NOT submitted: <scripts>.
  Recorded: <keys>." Before reporting a stage, compare that list with `squeue`/`sacct` and the project record and
  finish anything left undone (subagents do sometimes stop one step early).
- After each stage: `project_state.py check`, confirm the outputs the next stage consumes exist, and report to the
  user before starting the next stage. Independent work (e.g. tomodrgn-run and a figure of the current map) may run
  in parallel subagents; dependent stages never.

## 4b. Sessions and cost
- One conversation per stage is the default. The project record carries all state, so a new session that starts with
  "resume the project in <dir>" picks up exactly where the last left off. Long sessions get expensive: each turn
  re-reads the whole conversation (end-to-end test: $0.2/turn at the start, $20/turn after 15 turns in one session,
  $2-6/turn in fresh per-stage sessions).
- Keep `open_questions[]` in the project record (`project_state.py add <PROJECT> open_questions '{"q":..,"since":..}'`)
  for anything you asked and did not get an answer to - including proposed config fixes - and re-ask them at the
  start of the next turn. Remove an entry once answered. (A proposed RELION-env fix that nobody answered caused the
  same MPI failure twice.)
- Headless (`claude -p`) runs end background subagents when the turn ends; prefer foreground stage subagents there,
  or submit-and-return.

## 5. Rules that hold across stages
- Site rules: "nothing heavy on the login node" means anything beyond a few CPU-seconds or ~1 GB of I/O - map
  comparisons, FSCs, local resolution, STAR edits of large sets - goes through `cryoet_submit cpu`.
- Never write into input data or another person's project; symlink inputs, write to the project's own dirs.
- M rewrites the population it runs on: always clone first (m-refine does this).
- Handedness has two separate questions: the defocus hand (`ts_defocus_hand --check`, before CTF) and whether the
  final map is mirrored against a trusted reference/atomic model. Settle the second before comparing or depositing,
  and record the decision in the project record (`decisions`).
- Report resolution with the mask, the FSC criterion and the particle count; report recall/precision with raw counts.
- If a stage fails, stop the chain, show the error, and propose a fix; do not skip ahead on stale inputs.

## References
- `references/pipeline.md` - stage graph, inputs/outputs, typical compute, decision points.
- `references/handoff.md` - the `cryoet_project.json` schema and which stage writes which keys.
- `references/intake.md` - the full question set (site, software, dataset, goals, budget, later decision gates).
- `references/setup.md` - config keys explained, install pointers, site-specific gotchas to ask about.
