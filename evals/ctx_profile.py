import glob, json, os, re, sys
from collections import defaultdict
wd = os.path.realpath(sys.argv[1])
base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
pd = os.path.join(base, "projects", re.sub(r"[^A-Za-z0-9]", "-", wd))
def tlen(c):
    if isinstance(c, str):
        return len(c)
    if isinstance(c, list):
        return sum(len(b.get("text", "")) for b in c if isinstance(b, dict))
    return 0
def kind(name, inp):
    if name == "Bash":
        cmd = " ".join(str(inp.get("command", "")).split())
        m = re.search(r"([\w.-]+\.py)", cmd)
        return "Bash:" + (m.group(1) if m else cmd[:28])
    if name in ("Read", "Write", "Edit", "MultiEdit"):
        return "%s:%s" % (name, os.path.basename(str(inp.get("file_path", ""))))
    return name
for path in sorted(glob.glob(os.path.join(pd, "*.jsonl"))):
    msgs, uses, calls, res, wrote, big = {}, {}, defaultdict(int), defaultdict(int), defaultdict(int), []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if not isinstance(o, dict):
            continue
        m = o.get("message")
        if not isinstance(m, dict):
            continue
        c = m.get("content")
        if o.get("type") == "assistant":
            u = m.get("usage") or {}
            k = m.get("id") or o.get("uuid")
            ctx = (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0) + (u.get("cache_creation_input_tokens") or 0)
            if k and ctx and (k not in msgs or (u.get("output_tokens") or 0) >= msgs[k][1]):
                msgs[k] = (ctx, u.get("output_tokens") or 0, o.get("timestamp") or "")
            for b in (c if isinstance(c, list) else []):
                if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("id") not in uses:
                    inp = b.get("input") or {}
                    kd = kind(b.get("name", "?"), inp)
                    uses[b["id"]] = kd
                    calls[kd] += 1
                    if b.get("name") in ("Write", "Edit", "MultiEdit"):
                        wrote[kd] += len(str(inp.get("content", ""))) + len(str(inp.get("new_string", "")))
        elif o.get("type") == "user":
            for b in (c if isinstance(c, list) else []):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    kd = uses.get(b.get("tool_use_id"), "?")
                    n = tlen(b.get("content"))
                    res[kd] += n
                    big.append((n, kd))
    ctxs = [v[0] for v in sorted(msgs.values(), key=lambda v: v[2])]
    if len(ctxs) < 5:
        continue
    q = lambda f: ctxs[min(len(ctxs) - 1, int(f * len(ctxs)))]
    print("== %s: %d turni" % (os.path.basename(path)[:12], len(ctxs)))
    print("contesto/turno (k token): primo=%d 25%%=%d 50%%=%d 75%%=%d ultimo=%d medio=%d" % (
        ctxs[0] / 1e3, q(.25) / 1e3, q(.5) / 1e3, q(.75) / 1e3, ctxs[-1] / 1e3, sum(ctxs) / len(ctxs) / 1e3))
    print("\nchiamate  risultati_k_car  scritto_k_car  tipo   (~token = caratteri/2.4)")
    for kd, n in sorted(res.items(), key=lambda x: -x[1])[:14]:
        print("%8d %16.0f %14.0f  %s" % (calls[kd], n / 1e3, wrote.get(kd, 0) / 1e3, kd))
    print("\nturni per tipo di chiamata (prime 10):")
    print("  " + ", ".join("%s=%d" % (k, v) for k, v in sorted(calls.items(), key=lambda x: -x[1])[:10]))
    print("\nrisultati singoli piu grandi (k car):", ", ".join("%.0f %s" % (n / 1e3, kd) for n, kd in sorted(big, reverse=True)[:8]))
