"""Minimal text-level access to a .kicad_pcb (KiCad 10 / 10.99 s-expression).

top_blocks(text) -> list of (start, end, head) for every direct child of (kicad_pcb ...):
text[start:end] is the whole "(head ...)" block (balanced parens, strings respected).
parse(block) -> nested lists of atoms (strings unquoted) for small blocks (segments, vias, pads).
"""
import math
import re


def _match(text, i):
    """index just past the ')' closing the '(' at i"""
    depth, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced s-expression")


def top_blocks(text):
    root = text.index("(kicad_pcb")
    i, end = root + 1, _match(text, root) - 1
    out = []
    while i < end:
        j = text.find("(", i, end)
        if j < 0:
            break
        k = _match(text, j)
        m = re.match(r"\(([^\s()]+)", text[j:j + 64])
        out.append((j, k, m.group(1)))
        i = k
    return out


_TOK = re.compile(r'\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+')


def parse(block):
    stack = [[]]
    for t in _TOK.findall(block):
        if t == "(":
            stack.append([])
        elif t == ")":
            x = stack.pop()
            stack[-1].append(x)
        else:
            stack[-1].append(t[1:-1].replace('\\"', '"') if t.startswith('"') else t)
    return stack[0][0]


def field(node, name):
    for x in node[1:]:
        if isinstance(x, list) and x and x[0] == name:
            return x
    return None


def fields(node, name):
    return [x for x in node[1:] if isinstance(x, list) and x and x[0] == name]


def net_of(node):
    f = field(node, "net")
    if not f or len(f) < 2:
        return ""
    return f[-1] if len(f) == 2 else f[2]  # (net "NAME") in 10.x, (net N "NAME") in older files


def rot(x, y, deg):
    """KiCad footprint-local -> board offset (y down, angle counter-clockwise on screen)"""
    a = math.radians(deg)
    return x * math.cos(a) + y * math.sin(a), -x * math.sin(a) + y * math.cos(a)
