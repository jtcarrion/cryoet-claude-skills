#!/usr/bin/env bash
# cleanroom.sh -- run Claude Code as a brand-new user of this plugin: no personal skills, memory, CLAUDE.md files,
# user settings/hooks, MCP servers or claude.ai-synced skills; only this repo's plugin (--plugin-dir).
# The site's managed policy (e.g. /etc/claude-code/) still applies, as it would for any user of the machine.
#
#   tools/cleanroom.sh init <dir>                      # create <dir>/{config,work}; <dir> must be outside any project
#   tools/cleanroom.sh interactive <dir>               # you play the user (real AskUserQuestion dialogs)
#   tools/cleanroom.sh turn <dir> "<user message>"     # headless: one user turn; prints Claude's reply
#   tools/cleanroom.sh turn <dir> -                    #   (message from stdin)
#   tools/cleanroom.sh check <dir>                     # show what the session loads (plugins, skills, MCP)
#   tools/cleanroom.sh cost <dir>                      # per-turn and cumulative Claude usage (API-equivalent $)
#
# Auth (the clean config dir starts logged out). Either:
#   a) once, in a real terminal: `tools/cleanroom.sh interactive <dir>`, type /login, then /exit. The login is stored in
#      <dir>/config and every later `turn` reuses it (delete <dir>/config/.credentials.json afterwards), or
#   b) export CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`; revoke after testing), or put it in
#      <dir>/token (chmod 600). The real ~/.claude/.credentials.json is never copied.
# Env knobs: CLEANROOM_BUDGET_USD (per turn, default 5), CLEANROOM_TOOLS (allowed tools, default below),
#   CLEANROOM_HOME (HOME for the session, default <dir>/home: makes ~/.config/cryoet-skills fresh too),
#   CLEANROOM_NEW_SESSION=1 (fresh conversation for this turn; later turns resume it),
#   CLEANROOM_ADD_DIRS (space-separated dirs a real user would approve access to: project, data, software).
# Each headless turn appends to <dir>/transcript.md and saves the raw JSON in <dir>/turns/.
set -euo pipefail
PLUGIN="$(cd "$(dirname "$0")/.." && pwd)"
cmd="${1:-}"; D="${2:-}"
[ -n "$cmd" ] && [ -n "$D" ] || { sed -n '2,20p' "$0"; exit 1; }
D="$(mkdir -p "$D" && cd "$D" && pwd)"
SETTINGS='{"autoMemoryEnabled":false,"syncClaudeAiSkills":false,"syncClaudeAiPlugins":false,"disableClaudeAiConnectors":true}'
TOOLS="${CLEANROOM_TOOLS:-Read,Glob,Grep,Edit,Write,Bash,Skill,Agent,TodoWrite,AskUserQuestion}"

common_env() {
  export CLAUDE_CONFIG_DIR="$D/config" CLAUDE_CODE_DISABLE_CLAUDE_MDS=1 CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
  export CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=0   # -p would otherwise kill stage subagents 10 min after the turn
  export HOME="${CLEANROOM_HOME:-$D/home}"
  if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -f "$D/token" ]; then export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$D/token")"; fi
  if [ "${1:-}" != interactive ] && [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ ! -s "$D/config/.credentials.json" ]; then
    echo "not logged in: run 'tools/cleanroom.sh interactive $D' in a terminal and /login once (or set a token)" >&2; exit 2
  fi
}
flags() {
  local d; for d in ${CLEANROOM_ADD_DIRS:-} "${CLEANROOM_HOME:-$D/home}"; do printf '%s\0' --add-dir "$d"; done
  printf '%s\0' --plugin-dir "$PLUGIN" --setting-sources project,local --strict-mcp-config \
    --mcp-config '{"mcpServers":{}}' --settings "$SETTINGS"
}

case "$cmd" in
  init)
    case "$D/" in "$PLUGIN"/*) echo "refusing: $D is inside the plugin repo" >&2; exit 1;; esac
    p="$D"; while [ "$p" != / ]; do
      [ -f "$p/CLAUDE.md" ] && { echo "refusing: $p/CLAUDE.md would load (pick a dir outside any project)" >&2; exit 1; }
      p="$(dirname "$p")"; done
    mkdir -p "$D/config" "$D/work" "$D/home" "$D/turns"; : > "$D/transcript.md"
    command -v uuidgen >/dev/null && uuidgen > "$D/session_id" || python3 -c 'import uuid;print(uuid.uuid4())' > "$D/session_id"
    echo "clean room ready: $D (session $(cat "$D/session_id"))" ;;
  interactive)
    common_env interactive; cd "$D/work"; mapfile -d '' F < <(flags)
    exec claude "${F[@]}" ;;
  check)
    common_env; cd "$D/work"; mapfile -d '' F < <(flags)
    claude -p "Reply with the word ok." "${F[@]}" --max-budget-usd 0.5 --output-format stream-json --verbose \
      | python3 -c 'import sys,json
for l in sys.stdin:
    try: e=json.loads(l)
    except ValueError: continue
    if e.get("type")=="system" and e.get("subtype")=="init":
        print(json.dumps({k:e.get(k) for k in ("cwd","plugins","plugin_errors","mcp_servers","skills","agents","memory_paths") if k in e},indent=1)); break' ;;
  turn)
    common_env; cd "$D/work"; mapfile -d '' F < <(flags)
    msg="${3:-}"; [ "$msg" = - ] && msg="$(cat)"; [ -n "$msg" ] || { echo "empty message" >&2; exit 1; }
    sid="$(cat "$D/session_id")"; n=$(ls "$D/turns" | wc -l); n=$((n+1))
    if [ "${CLEANROOM_NEW_SESSION:-0}" = 1 ]; then   # start a fresh conversation (state must come from the project record)
      sid="$(python3 -c 'import uuid;print(uuid.uuid4())')"; echo "$sid" > "$D/session_id"; S=(--session-id "$sid")
      printf '\n---\n# NEW SESSION %s\n' "$sid" >> "$D/transcript.md"
    elif [ "$n" -eq 1 ]; then S=(--session-id "$sid"); else S=(--resume "$sid"); fi
    out="$D/turns/$(printf %03d $n).json"
    claude -p "$msg" "${S[@]}" "${F[@]}" --permission-mode dontAsk --permission-prompts none \
      --allowedTools "$TOOLS" --max-budget-usd "${CLEANROOM_BUDGET_USD:-5}" --output-format json > "$out" || true
    python3 - "$out" "$D/transcript.md" "$n" "$msg" <<'PY'
import json, sys
out, tr, n, msg = sys.argv[1:]
try: r = json.load(open(out))
except Exception as e: r = {"result": "(no JSON: %s)" % e}
text = r.get("result") or r.get("error") or "(empty)"
with open(tr, "a") as f:
    f.write("\n## Turn %s - user\n\n%s\n\n## Turn %s - Claude (cost $%.2f, %s turns)\n\n%s\n" % (
        n, msg, n, r.get("total_cost_usd") or 0, r.get("num_turns", "?"), text))
print(text)
PY
    ;;
  cost)
    python3 - "$D" <<'PY'
import glob, json, os, sys
D = sys.argv[1]; tot = 0.0; rows = []
for f in sorted(glob.glob(os.path.join(D, "turns", "*.json"))):
    try: r = json.load(open(f))
    except Exception: continue
    c = r.get("total_cost_usd") or 0.0; tot += c
    m = r.get("modelUsage") or {}
    rows.append((os.path.basename(f)[:3], c, tot, r.get("num_turns", "?"), r.get("duration_ms", 0) / 60000.0))
print("turn   cost($)  cumulative($)  agent-steps  minutes")
for t, c, cum, n, mins in rows: print("%4s %9.2f %14.2f %12s %8.1f" % (t, c, cum, n, mins))
print("total %.2f over %d turns (API-equivalent; on a subscription this counts against plan limits, not a bill)" % (tot, len(rows)))
PY
    ;;
  *) sed -n '2,21p' "$0"; exit 1 ;;
esac
