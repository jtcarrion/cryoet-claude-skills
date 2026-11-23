# Packaging design (from Claude Code docs, checked 2026-11-21)

Docs: code.claude.com/docs/en/plugins/{manifest-reference,create-marketplace,install}.md, skills.md, sub-agents.md, plugin-evals.md

- Repo root = plugin root = marketplace root: `.claude-plugin/{plugin.json,marketplace.json}`, `skills/`, `agents/`, `evals/`.
  Install: `/plugin marketplace add <owner>/<repo>` then `/plugin install <plugin>@<marketplace>`. Validate: `claude plugin validate .`
- Plugin name must not start with `claude-`/`anthropic-`. Bump `version` every release.
- Script paths: use `${CLAUDE_SKILL_DIR}` (works in plugin and copied `~/.claude/skills` mode).
  `${CLAUDE_PLUGIN_ROOT}` is markdown-only and plugin-only -> do not use in Bash. Each skill self-contained; vendor shared helpers.
- Config: one file `~/.config/cryoet-skills/config.sh` (override with `$CRYOET_SKILLS_CONFIG`), written by `cryoet-workflow setup`,
  read by every skill. Works in copy mode (plugin `userConfig` does not).
- Skill names are namespaced in plugin mode (`/<plugin>:m-refine`) vs bare in copy mode; skill text must name skills without prefix.
- Director: plugin ships `agents/<stage>.md` with `skills: [<one skill>]`; in copy mode director falls back to general-purpose
  subagents told to load the skill. Skill->skill invocation and plugin-skill preloading: UNVERIFIED, test via evals.
- SKILL.md < 500 lines; description+when_to_use truncated at 1,536 chars.
- Evals: `evals/<case>/prompt.md` + `graders/*.md` (types: tool_used, regex, tool_order, file_exists, baseline, llm);
  `claude plugin eval . --case X --runs 1`. Routing/file-writing only; real cluster runs are a separate tier (tests/e2e).
- Validation tiers: (a) static: lint for hardcoded paths, py_compile/bash -n, flags vs docs; (b) plugin evals with a fresh-user
  config; (c) e2e on EMPIAR-10499 3-series subset (00254, 00255, 00261) in a sandbox, inputs symlinked.
