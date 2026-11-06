import json
import re
import pathlib
import sys

ROOT = pathlib.Path(r"C:/Users/PC/Documents/GitHub/ocr-app")
inp = json.loads((ROOT / ".ua/tmp/batch-input-2.json").read_text(encoding="utf-8"))

allowed = set(inp["batchImportData"])
for v in inp["batchImportData"].values():
    allowed |= set(v)
allowed |= {f["path"] for f in inp["files"]}
syms = set()
for path, ns in inp["neighborMap"].items():
    allowed.add(path)
    for n in ns:
        allowed.add(n["path"])
        for s in n.get("symbols", []):
            syms.add((n["path"], s))
known = {
    ("app/validator.py", "validate"),
    ("app/db.py", "list_jobs"),
    ("app/db.py", "set_status"),
    ("app/main.py", "create_app"),
    ("app/auth.py", "create_key"),
    ("app/db.py", "connect"),
}

nodes = []
edges = []
for k in (1, 2, 3):
    d = json.loads((ROOT / f".ua/intermediate/batch-2-part-{k}.json").read_text(encoding="utf-8"))
    nodes += [(k, n) for n in d["nodes"]]
    edges += [(k, e) for e in d["edges"]]
ids = {n["id"] for _, n in nodes}

bad = []
for _, e in edges:
    for side in ("source", "target"):
        v = e[side]
        if v in ids:
            continue
        pfx, rest = v.split(":", 1)
        path = rest.rsplit(":", 1)[0] if pfx in ("function", "class") else rest
        if path not in allowed and v not in ("document:README.md", "file:scripts/tailscale_serve.ps1"):
            bad.append("PATH?" + v)
            continue
        if pfx in ("function", "class"):
            key = (path, rest.rsplit(":", 1)[1])
            if key not in syms and key not in known:
                bad.append("SYM?" + v)

esc = re.compile(r"u[0-9a-fA-F]{4}")
lines = [
    "nodes %d / edges %d" % (len(nodes), len(edges)),
    "tag violations: %d" % len([n for _, n in nodes if not 3 <= len(n["tags"]) <= 5]),
    "bad complexity: %d" % len([n for _, n in nodes if n["complexity"] not in ("simple", "moderate", "complex")]),
    "missing summary/name/type: %d" % len([n for _, n in nodes if not (n.get("summary") and n.get("name") and n.get("type"))]),
    "bad direction: %d" % len([e for _, e in edges if e["direction"] != "forward"]),
    "self edges: %d" % len([e for _, e in edges if e["source"] == e["target"]]),
    "unresolved refs: %s" % sorted(set(bad)),
    "imports edges: %d / expected %d" % (
        len([e for _, e in edges if e["type"] == "imports"]),
        sum(len(v) for v in inp["batchImportData"].values()),
    ),
    "ascii-escaped text: %d" % len([n for _, n in nodes if esc.search(json.dumps(n.get("summary", "")))]),
    "file nodes: %d (batch has %d files)" % (
        len([n for _, n in nodes if n["type"] == "file"]), len(inp["files"])),
]
sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))
