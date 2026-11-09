import glob, json, os, re, sys
from datetime import datetime
wd = os.path.realpath(sys.argv[1])
base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
pd = os.path.join(base, "projects", re.sub(r"[^A-Za-z0-9]", "-", wd))
PRICE = {"opus": (5, 25), "sonnet": (3, 15), "haiku": (1, 5)}  # $/MTok in,out: ipotesi del run A
def price(model):
    for k, v in PRICE.items():
        if k in model:
            return v
    return (3, 15)
def ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None
amap = {}
try:
    for n in json.load(open(os.path.join(wd, ".sjck", "state.json"))).get("nodes", []):
        if n.get("agent_id"):
            amap[n["agent_id"]] = "%s/%s" % (n.get("id"), n.get("agent"))
except Exception:
    pass
rows = []
for path in glob.glob(os.path.join(pd, "**", "*.jsonl"), recursive=True):
    best = {}
    first = ""
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if not first and isinstance(o, dict) and o.get("type") == "user":
            c = (o.get("message") or {}).get("content")
            if isinstance(c, list):
                c = " ".join(b.get("text", "") for b in c if isinstance(b, dict))
            first = " ".join(str(c).split())[:60]
        m = o.get("message") if isinstance(o, dict) and o.get("type") == "assistant" else None
        u = m.get("usage") if isinstance(m, dict) else None
        if not isinstance(u, dict) or m.get("model") in (None, "<synthetic>"):
            continue
        k = m.get("id") or o.get("uuid")
        r = dict(model=m["model"], t=ts(o.get("timestamp") or ""), i=u.get("input_tokens") or 0,
                 o=u.get("output_tokens") or 0, cr=u.get("cache_read_input_tokens") or 0,
                 cw=u.get("cache_creation_input_tokens") or 0)
        if k and (k not in best or r["o"] >= best[k]["o"]):
            best[k] = r
    if not best:
        continue
    ms = sorted(best.values(), key=lambda r: r["t"] or 0)
    cost = sum((r["i"] * price(r["model"])[0] + r["o"] * price(r["model"])[1]
                + r["cr"] * price(r["model"])[0] * 0.1 + r["cw"] * price(r["model"])[0] * 1.25) / 1e6 for r in ms)
    gaps = cwg = 0
    for a, b in zip(ms, ms[1:]):
        if a["t"] and b["t"] and b["t"] - a["t"] > 300:
            gaps += 1
            cwg += b["cw"]
    is_sub = "subagents" in path.split(os.sep) or os.path.basename(path).startswith("agent-")
    label = "main" if not is_sub else next((v for k, v in amap.items() if k in path), "? " + first)
    models = sorted({r["model"].replace("claude-", "") for r in ms})
    rows.append((cost, label, len(ms), sum(r["o"] for r in ms), sum(r["cr"] for r in ms),
                 sum(r["cw"] for r in ms), gaps, cwg, ",".join(models)))
tot = sum(r[0] for r in rows) or 1
print("%7s %5s %-48s %5s %7s %8s %7s %6s %8s  %s" % ("costo$", "quota", "transcript", "msg", "out_k", "cread_M", "cwr_k", "gap>5m", "cw_gap_k", "modello"))
for r in sorted(rows, reverse=True):
    print("%7.2f %4.0f%% %-48s %5d %7.0f %8.2f %7.0f %6d %8.0f  %s" % (r[0], 100 * r[0] / tot, r[1][:48], r[2], r[3] / 1e3, r[4] / 1e6, r[5] / 1e3, r[6], r[7] / 1e3, r[8]))
print("TOTALE $%.2f su %d transcript" % (tot, len(rows)))
