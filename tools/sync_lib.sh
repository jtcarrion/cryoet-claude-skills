#!/usr/bin/env bash
# Vendor lib/* into every skill's scripts/_lib/ (skills must be self-contained: copy-install has no shared dir).
# Run after editing anything in lib/. tools/lint.py fails if a vendored copy drifts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for s in "$ROOT"/skills/*/; do
  mkdir -p "$s/scripts/_lib"
  for f in "$ROOT"/lib/*; do [ -f "$f" ] && cp "$f" "$s/scripts/_lib/"; done
done
echo "synced lib/ into $(ls -d "$ROOT"/skills/*/ | wc -l) skills"
