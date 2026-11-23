"""Minimal, dependency-free RELION STAR reader/writer (pandas/starfile are broken in some cluster envs).

read(path) -> dict  name -> Block;  Block.cols (list of column names, '_rln' prefix kept), Block.rows (list of lists of
str) for loop blocks, or Block.pairs (dict) for key/value blocks. write(path, blocks) writes them back in order.
Values stay strings: convert where you use them (col_float(block, name)).
"""
from collections import OrderedDict


class Block:
    def __init__(self, name):
        self.name, self.cols, self.rows, self.pairs, self.loop = name, [], [], OrderedDict(), False

    def col(self, name):
        return self.cols.index(name)

    def values(self, name):
        i = self.col(name)
        return [r[i] for r in self.rows]

    def floats(self, name):
        return [float(v) for v in self.values(name)]

    def set_values(self, name, vals):
        if name not in self.cols:
            self.cols.append(name)
            for r in self.rows:
                r.append("")
        i = self.col(name)
        for r, v in zip(self.rows, vals):
            r[i] = str(v)


def read(path):
    blocks, cur, in_loop_header = OrderedDict(), None, False
    for raw in open(path):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("data_"):
            cur = Block(line); blocks[line] = cur; in_loop_header = False; continue
        if cur is None:
            continue
        if line == "loop_":
            cur.loop = True; in_loop_header = True; continue
        if line.startswith("_"):
            parts = line.split()
            if cur.loop and in_loop_header:
                cur.cols.append(parts[0])
            else:
                cur.pairs[parts[0]] = parts[1] if len(parts) > 1 else ""
            continue
        in_loop_header = False
        if cur.loop:
            cur.rows.append(line.split())
    return blocks


def write(path, blocks):
    with open(path, "w") as f:
        f.write("\n# version 50001\n\n")
        for name, b in blocks.items():
            f.write(f"{name}\n\n")
            if b.loop:
                f.write("loop_\n")
                for i, c in enumerate(b.cols, 1):
                    f.write(f"{c} #{i}\n")
                for r in b.rows:
                    f.write("\t".join(r) + "\n")
            else:
                w = max((len(k) for k in b.pairs), default=0)
                for k, v in b.pairs.items():
                    f.write(f"{k:<{w}}   {v}\n")
            f.write("\n\n")


def particles(blocks):
    for k in ("data_particles", "data_"):
        if k in blocks and blocks[k].loop:
            return blocks[k]
    raise KeyError("no particles loop block")
