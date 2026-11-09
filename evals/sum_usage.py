#!/usr/bin/env python3
"""Somma i token reali di una cartella di lavoro dai transcript di Claude Code.

Misura indipendente dal kit: stesso metodo per il run sjck e per l'auto mode,
cosi' il confronto non dipende dal codice che si sta valutando.

Legge ricorsivamente ~/.claude/projects/<slug-della-cartella>/**/*.jsonl
(sessione principale e subagenti), tiene una sola riga per messaggio
(`message.id`: lo streaming scrive lo stesso messaggio piu' volte, si tiene la
riga con piu' output) e somma input, output, cache read, cache write.

Limiti noti: nei transcript dei subagenti la riga finale dello streaming a
volte manca, quindi l'output puo' essere sottostimato (qualche %). Il costo e'
calcolato con un solo prezzo per tutti i modelli e con cache write 5 minuti
(x1,25); la cache a 1 ora costa di piu'. Per questo i token vengono sempre
mostrati per tipo e per modello.

Uso:
  sum_usage.py DIR [--since 2026-11-08T22:00:00Z] [--price-in 3 --price-out 15]
               [--label NOME] [--json]
  --since   conta solo i messaggi con timestamp >= (UTC, formato ISO)
  --price-* dollari per milione di token (input, output)
"""
import argparse
import json
import os
import re
import sys

FIELDS = ("input_tokens", "output_tokens",
          "cache_read_input_tokens", "cache_creation_input_tokens")


def project_dir(workdir):
    slug = re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(workdir))
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(
        os.path.expanduser("~"), ".claude")
    return os.path.join(base, "projects", slug)


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def scan(pdir, since=None):
    best = {}
    files = subs = 0
    for root, _dirs, names in os.walk(pdir):
        for name in sorted(names):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(root, name)
            is_sub = "subagents" in path.split(os.sep) or name.startswith("agent-")
            files += 1
            subs += 1 if is_sub else 0
            try:
                fh = open(path, encoding="utf-8", errors="replace")
            except OSError:
                continue
            with fh:
                for line in fh:
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(obj, dict) or obj.get("type") != "assistant":
                        continue
                    msg = obj.get("message")
                    if not isinstance(msg, dict):
                        continue
                    usage = msg.get("usage")
                    if not isinstance(usage, dict):
                        continue
                    model = msg.get("model") or "unknown"
                    if model == "<synthetic>":
                        continue
                    ts = obj.get("timestamp") or ""
                    if since and ts and ts < since:
                        continue
                    key = msg.get("id") or obj.get("uuid")
                    if not key:
                        continue
                    rec = {f: _int(usage.get(f)) for f in FIELDS}
                    rec["model"], rec["ts"], rec["sub"] = model, ts, is_sub
                    old = best.get(key)
                    if old is None or rec["output_tokens"] >= old["output_tokens"]:
                        best[key] = rec
    return best, files, subs


def summarize(best, files, subs, price_in=None, price_out=None):
    tot = {f: 0 for f in FIELDS}
    per_model = {}
    stamps = []
    for rec in best.values():
        m = per_model.setdefault(rec["model"], {f: 0 for f in FIELDS})
        m["messages"] = m.get("messages", 0) + 1
        for f in FIELDS:
            tot[f] += rec[f]
            m[f] += rec[f]
        if rec["ts"]:
            stamps.append(rec["ts"])
    out = {
        "messages": len(best),
        "transcripts": files,
        "subagent_transcripts": subs,
        "first": min(stamps) if stamps else None,
        "last": max(stamps) if stamps else None,
        "tokens": {
            "input": tot["input_tokens"],
            "output": tot["output_tokens"],
            "cache_read": tot["cache_read_input_tokens"],
            "cache_write": tot["cache_creation_input_tokens"],
        },
        "per_model": per_model,
    }
    t = out["tokens"]
    t["total"] = sum(t.values())
    if price_in is not None and price_out is not None:
        out["cost_usd"] = round(
            (t["input"] * price_in + t["output"] * price_out
             + t["cache_read"] * price_in * 0.10
             + t["cache_write"] * price_in * 1.25) / 1e6, 4)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dir", help="cartella di lavoro (worktree) del run")
    ap.add_argument("--since", help="solo messaggi con timestamp >= (UTC ISO)")
    ap.add_argument("--price-in", type=float, help="$/MTok input")
    ap.add_argument("--price-out", type=float, help="$/MTok output")
    ap.add_argument("--label", default="")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    pdir = project_dir(a.dir)
    if not os.path.isdir(pdir):
        print("nessun transcript in %s" % pdir, file=sys.stderr)
        return 1
    best, files, subs = scan(pdir, a.since)
    res = summarize(best, files, subs, a.price_in, a.price_out)
    res["label"], res["project_dir"] = a.label, pdir
    if a.json:
        print(json.dumps(res, indent=1))
        return 0
    t = res["tokens"]
    print("== %s ==" % (a.label or a.dir))
    print("transcript: %d (di cui subagenti: %d), messaggi: %d"
          % (res["transcripts"], res["subagent_transcripts"], res["messages"]))
    print("periodo: %s -> %s" % (res["first"], res["last"]))
    for k in ("input", "output", "cache_read", "cache_write", "total"):
        print("%-12s %14s" % (k, format(t[k], ",")))
    if "cost_usd" in res:
        print("costo stimato: $%.4f" % res["cost_usd"])
    for model, m in sorted(res["per_model"].items()):
        print("  %-28s msg=%d in=%s out=%s cr=%s cw=%s" % (
            model, m["messages"], format(m["input_tokens"], ","),
            format(m["output_tokens"], ","),
            format(m["cache_read_input_tokens"], ","),
            format(m["cache_creation_input_tokens"], ",")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
