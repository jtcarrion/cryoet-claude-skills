#!/usr/bin/env python3
"""Shared helpers for write_cxc.py / check_cxc.py (stdlib only, Python 3.6+, safe under LC_ALL=C).

Style resolution (first hit wins):  --style NAME|PATH  >  spec "style"  >  $CHIMERAX_STYLE  >  config CHIMERAX_STYLE
>  "default".  NAME means styles/NAME.json in this skill; anything ending in .json (or containing a slash) is a path.
Every style is merged over styles/default.json, so a style file only needs the keys it changes.
"""
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STYLE_DIR = os.path.join(os.path.dirname(HERE), "styles")
sys.path.insert(0, os.path.join(HERE, "_lib"))


def config_value(key, default=""):
    """Value from the environment, else the cryoet-skills config, else default. Never fails if there is no config."""
    if os.environ.get(key):
        return os.environ[key]
    try:
        import cryoet_config as cc
        return cc.load().get(key) or default
    except (SystemExit, Exception):
        return default


def read_json(path):
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def _merge(base, over):
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


def style_path(name):
    if name.endswith(".json") or os.sep in name or "/" in name:
        return os.path.abspath(os.path.expanduser(name))
    return os.path.join(STYLE_DIR, name + ".json")


def load_style(cli=None, spec=None):
    """Return (style_dict, name, source) after merging over default.json and any spec "style_overrides"."""
    spec = spec or {}
    if cli:
        name, src = cli, "--style"
    elif spec.get("style"):
        name, src = spec["style"], "spec"
    else:
        name = config_value("CHIMERAX_STYLE", "default")
        src = "CHIMERAX_STYLE" if name != "default" else "default"
    p = style_path(name)
    if not os.path.isfile(p):
        avail = sorted(f[:-5] for f in os.listdir(STYLE_DIR) if f.endswith(".json"))
        raise SystemExit("chimerax-figures: style '%s' not found (%s). Available: %s" % (name, p, ", ".join(avail)))
    st = read_json(os.path.join(STYLE_DIR, "default.json"))
    if os.path.abspath(p) != os.path.join(STYLE_DIR, "default.json"):
        st = _merge(st, read_json(p))
    if spec.get("style_overrides"):
        st = _merge(st, spec["style_overrides"])
    st.pop("_doc", None)
    return st, name, src


def style_block(st):
    """The ChimeraX lines that set the style, in order (after `close session`)."""
    L = ["set bgColor %s" % st["background"], "lighting %s" % st["lighting"]]
    s = st.get("silhouettes", {})
    if s.get("enabled", True):
        line = "graphics silhouettes true width %g" % s.get("width", 1.5)
        if s.get("color") and s["color"] != "black":
            line += " color %s" % s["color"]
        L.append(line)
    else:
        L.append("graphics silhouettes false")
    return L


def write_text(path, lines):
    """Always UTF-8, whatever the locale (Python 3.6 under LC_ALL=C would otherwise raise UnicodeEncodeError)."""
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")


def say(msg=""):
    """print() that cannot crash on a non-UTF-8 terminal/locale."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    sys.stdout.write(msg.encode(enc, "backslashreplace").decode(enc) + "\n")
