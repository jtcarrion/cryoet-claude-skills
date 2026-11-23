#!/usr/bin/env python3
"""Static check of a ChimeraX .cxc: general-practice rules FAIL, deviations from the active style only WARN.

  python3 check_cxc.py figure.cxc [--closeup] [--style NAME|PATH]
    --closeup   a follow-on script run after the main one (no style block / close session / dust expected)
Prints PASS/WARN/FAIL per rule; exit 1 if any FAIL. Text only: it cannot tell whether the figure looks right.
Stdlib only, Python 3.6+, safe under LC_ALL=C.

FAIL (general practice): close session missing; trailing comments (ChimeraX treats '#' after a command as an atom
spec - only whole-line comments or '; # ...' are comments); tile; non-numeric levels; volume display without step 1;
a displayed surface/mesh without surface dust (unless the header says 'Dust hiding OFF for #N: reason');
surface dust after a zone on the same model (it switches the zone off); local-resolution maps nested after a
view matrix or before the last open; plain #N (not #!N) on a model that has nested children in volume / color sample /
rename; color sample not on #!N with its own nested child and an explicit palette; resampling commands;
several displayed maps but no 'Level rule:' header line; placeholders.
WARN (style or advice): background / lighting / silhouettes differ from the style; close session not first;
absolute paths; no colour key with color sample; .cxs saved without includeMaps true.
"""
import argparse
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cxstyle  # noqa: E402

HEX = re.compile(r"[0-9A-Fa-f]{3,12}\b")


def strip_quotes(s):
    return re.sub(r'"[^"]*"|\'[^\']*\'', '""', s)


def bad_hash(cmd):
    """True if a '#' in the command cannot be an atom spec or a colour, i.e. it is a trailing comment."""
    for k, seg in enumerate(strip_quotes(cmd).split(";")):
        seg_s = seg.strip()
        if k > 0 and seg_s.startswith("#"):
            continue                        # "cmd ; # comment" is a documented in-line comment
        for m in re.finditer(r"#", seg):
            rest = seg[m.end():]
            if rest[:1] in ("!", "*") or rest[:1].isdigit() or HEX.match(rest):
                continue
            return True
    return False


def top_ids(spec):
    """Top-level model ids named in a spec like '#!1,3' or '#2.5' or '#1-3'."""
    out = set()
    for m in re.finditer(r"#!?([\d,\-]+)", spec):
        for part in m.group(1).split(","):
            if "-" in part and part.replace("-", "").isdigit():
                a, b = part.split("-", 1)
                if a and b:
                    out |= set(range(int(a), int(b) + 1))
            elif part.isdigit():
                out.add(int(part))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cxc")
    ap.add_argument("--closeup", action="store_true")
    ap.add_argument("--style")
    a = ap.parse_args()
    with io.open(a.cxc, encoding="utf-8", errors="replace") as f:
        raw = f.read().splitlines()
    hdr = [re.match(r"^#\s*Style:\s*(\S+)", l) for l in raw]
    hdr = [m.group(1) for m in hdr if m]
    st, sname, _ = cxstyle.load_style(a.style or (hdr[0] if hdr else None))
    comments = [l.strip() for l in raw if l.strip().startswith("#")]
    cmds = [(n + 1, l.strip()) for n, l in enumerate(raw) if l.strip() and not l.strip().startswith("#")]
    res = []

    def add(lvl, rule, msg=""):
        res.append((lvl, rule, msg))

    def lines(ns):
        return "lines %s" % ns

    # ---- style (WARN only) ---------------------------------------------------------------------------------------
    if not a.closeup:
        cs = [n for n, c in cmds if c == "close session"]
        add("PASS" if cs else "FAIL", "close session", "line %d" % cs[0] if cs else "missing")
        if cs:
            add("PASS" if cmds[0][1] == "close session" else "WARN", "close session is the first command")
        bg = [c.split()[2] for _, c in cmds if re.match(r"(?i)^set\s+bgColor\s+\S+", c)]
        want = str(st["background"]).lower()
        add("PASS" if bg and bg[-1].lower() == want else "WARN", "style %s: background %s" % (sname, want),
            ("found %s" % bg[-1]) if bg else "no set bgColor")
        li = [c.split()[1] for _, c in cmds if re.match(r"^lighting\s+\S+", c)]
        add("PASS" if li and li[-1] == st["lighting"] else "WARN", "style %s: lighting %s" % (sname, st["lighting"]),
            ("found %s" % li[-1]) if li else "no lighting line")
        sil = [c for _, c in cmds if c.startswith("graphics silhouettes")]
        on = st.get("silhouettes", {}).get("enabled", True)
        got = bool(sil) and re.match(r"^graphics silhouettes\s+(true|on|1)\b", sil[-1]) is not None
        add("PASS" if (sil and got == on) else "WARN", "style %s: silhouettes %s" % (sname, "on" if on else "off"),
            sil[-1] if sil else "no graphics silhouettes line")

    # ---- general practice (FAIL) ---------------------------------------------------------------------------------
    bad = [n for n, c in cmds if bad_hash(c)]
    add("FAIL" if bad else "PASS", "no trailing comments", lines(bad) if bad else "")
    tl = [n for n, c in cmds if re.match(r"^tile\b", c)]
    add("FAIL" if tl else "PASS", "no tile (moves top-level models only; breaks color sample)", lines(tl) if tl else "")
    rs = [n for n, c in cmds if re.search(r"\bresample\b|\bonGrid\b|^vop\s+resample", c)]
    add("FAIL" if rs else "PASS", "no resampling (place with an exact matrix instead)", lines(rs) if rs else "")

    # nesting bookkeeping
    renames = [(n, c) for n, c in cmds if re.match(r"^rename\s+#!?\d+\s+id\s+#\d+\.\d+", c)]
    parents = {int(re.search(r"id\s+#(\d+)\.", c).group(1)): n for n, c in renames}

    def plain_on_parent(n, spec):
        """spec uses plain #N (not #!N) for a model that already has a nested child at line n."""
        for m in re.finditer(r"#(!?)(\d+)(?![\d.])", spec):
            if m.group(1) != "!" and int(m.group(2)) in parents and parents[int(m.group(2))] < n:
                return True
        return False

    vols = []   # (line, ids, cmd) for volume display lines
    for n, c in cmds:
        m = re.match(r"^volume\s+(#\S+)(.*)$", c)
        if m:
            vols.append((n, m.group(1), m.group(2)))
    badlv = [n for n, s, rest in vols if re.search(r"\blevel\b", rest) and
             not re.search(r"\blevel\s+-?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?(\s|,|$)", rest)]
    add("FAIL" if badlv else "PASS", "numeric contour levels", lines(badlv) if badlv else "%d volume lines" % len(vols))
    disp = [(n, s, rest) for n, s, rest in vols if re.search(r"\b(level|style\s+(surface|mesh))\b", rest)]
    nostep = [n for n, s, rest in disp if not re.search(r"\bstep\s+1\b", rest)]
    add("FAIL" if nostep else "PASS", "step 1 on every displayed volume", lines(nostep) if nostep else "")

    zoned = {}
    for n, c in cmds:
        m = re.match(r"^(volume|surface)\s+zone\s+(#\S+)", c)
        if m:
            for i in top_ids(m.group(2)):
                zoned.setdefault(i, n)
    dust = {}
    for n, c in cmds:
        m = re.match(r"^surface\s+dust\s+(#\S+)", c)
        if m:
            for i in top_ids(m.group(1)):
                dust.setdefault(i, []).append(n)
    off = set()
    for l in comments:
        m = re.search(r"Dust hiding OFF for #!?(\d+)\s*:\s*\S", l)
        if m:
            off.add(int(m.group(1)))
    shown = set()
    for n, s, rest in disp:
        if not re.search(r"style\s+image", rest):
            shown |= top_ids(s)
    if not a.closeup and shown:
        miss = sorted(i for i in shown if i not in dust and i not in off and i not in zoned)
        add("FAIL" if miss else "PASS", "surface dust on every displayed density",
            "missing for #%s (or add '# Dust hiding OFF for #N: reason')" % miss if miss else "")
    late_dust = sorted(i for i in dust if i in zoned and any(n > zoned[i] for n in dust[i]))
    add("FAIL" if late_dust else "PASS", "no surface dust after a zone (it switches the zone off)",
        "#%s" % late_dust if late_dust else "")

    first_vm = min([n for n, c in cmds if c.startswith("view matrix")], default=None)
    late = [n for n, _ in renames if first_vm and n > first_vm]
    add("FAIL" if late else "PASS", "local-resolution maps nested before any view matrix", lines(late) if late else "")
    last_open = max([n for n, c in cmds if c.startswith("open ")], default=0)
    early = [n for n, _ in renames if n < last_open]
    add("FAIL" if early else "PASS", "all files opened before nesting",
        "rename at %s precedes an open" % lines(early) if early else "")

    plain = [n for n, c in cmds if (c.startswith("volume ") or c.startswith("color sample") or
             (c.startswith("rename") and " id " not in c)) and plain_on_parent(n, c.split(" map ")[0])]
    add("FAIL" if plain else "PASS", "#!N (not #N) on models with nested children", lines(plain) if plain else "")

    samples = [(n, c) for n, c in cmds if c.startswith("color sample")]
    for n, c in samples:
        m = re.match(r"^color sample (#!?)(\d+) map #(\d+)\.(\d+)", c)
        if not m:
            add("FAIL", "color sample uses #!N target and a nested #N.k map", "line %d" % n); continue
        if m.group(1) != "#!":
            add("FAIL", "color sample target is #!N", "line %d" % n)
        if m.group(2) != m.group(3):
            add("FAIL", "color sample map is the target's own child", "line %d" % n)
        if "palette" not in c:
            add("FAIL", "color sample has an explicit palette", "line %d" % n)
    if samples:
        nested = {re.search(r"id\s+#(\d+\.\d+)", c).group(1) for _, c in renames}
        used = {re.search(r"map #(\d+\.\d+)", c).group(1) for _, c in samples if re.search(r"map #(\d+\.\d+)", c)}
        if not a.closeup:
            add("PASS" if used <= nested else "FAIL", "every sampled map was nested",
                str(sorted(used - nested)) if used - nested else "")
        add("PASS" if any(c.startswith("key ") for _, c in cmds) or a.closeup else "WARN", "colour key present")

    rule = any(re.search(r"(?i)level rule\s*:", l) for l in comments)
    if not a.closeup and shown:
        lvl = "FAIL" if len(shown) > 1 and not rule else ("WARN" if not rule else "PASS")
        add(lvl, "header states the contour-level rule ('Level rule:'; one rule for every compared map)")

    absopen = [n for n, c in cmds if re.match(r"^open\s+(/|[A-Za-z]:\\|~)", c)]
    add("WARN" if absopen else "PASS", "relative paths in open", "absolute at %s" % lines(absopen) if absopen else "")
    cxs = [n for n, c in cmds if re.match(r"^save\s+\S+\.cxs\b", c) and "includeMaps true" not in c]
    add("WARN" if cxs else "PASS", "sessions saved with includeMaps true", lines(cxs) if cxs else "")
    ph = [n for n, c in cmds if re.search(r"\b(LEVEL_[A-Z]\w*|TODO|XXX|FIXME)\b|<[a-z_]+>", c)]
    add("FAIL" if ph else "PASS", "no placeholders left", lines(ph) if ph else "")

    width = max(len(r) for _, r, _ in res)
    for lvl, rule_, msg in res:
        cxstyle.say("%-5s %-*s  %s" % (lvl, width, rule_, msg))
    sys.exit(1 if any(l == "FAIL" for l, _, _ in res) else 0)


if __name__ == "__main__":
    main()
