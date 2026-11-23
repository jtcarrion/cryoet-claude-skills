#!/usr/bin/env python3
"""Split each evals/<case>/graders/criteria.md (one PASS/FAIL list) into one llm grader per numbered item
(graders/c<N>.md) so scores show partial credit and reports say which behaviour failed.
Text before the numbered list (e.g. the no-shell-mode paragraph) is kept as shared context in every item grader.
Idempotent: re-run after editing criteria.md; criteria.md is kept as the human-readable source and renamed
to criteria.md.src so the harness does not grade it twice."""
import glob, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
n_cases = n_items = 0
for src in sorted(glob.glob(os.path.join(ROOT, "evals", "*", "graders", "criteria.md")) +
                  glob.glob(os.path.join(ROOT, "evals", "*", "graders", "criteria.md.src"))):
    gdir = os.path.dirname(src)
    if src.endswith(".md") and os.path.exists(src + ".src"):
        continue
    body = re.sub(r"^---\n.*?\n---\n", "", open(src).read(), flags=re.S).strip()
    m = re.search(r"^\s*1\.\s", body, re.M)
    if not m:
        print("skip (no numbered list):", src); continue
    pre = body[:m.start()].strip()
    pre = re.sub(r"PASS only if all[^\n]*?(else|otherwise) FAIL:?", "", pre).strip()
    items = re.split(r"^\s*\d+\.\s+", body[m.start():], flags=re.M)[1:]
    for old in glob.glob(os.path.join(gdir, "c[0-9]*.md")):
        os.remove(old)
    for i, it in enumerate(items, 1):
        it = " ".join(it.split())
        with open(os.path.join(gdir, "c%d.md" % i), "w") as f:
            f.write("---\ntype: llm\nweight: 1\n---\n\n")
            if pre:
                f.write("Context for grading: %s\n\n" % pre)
            f.write("Judge ONE behaviour. PASS if the answer does this (substance matters, not exact wording), "
                    "else FAIL:\n%s\n" % it)
    if src.endswith(".md"):
        os.rename(src, src + ".src")
    n_cases += 1; n_items += len(items)
print("split %d cases into %d item graders" % (n_cases, n_items))
