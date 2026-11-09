#!/usr/bin/env python3
"""Dieta del contesto di un run sjck-graph (v0.5). Solo standard library, 3.9+.

Agisce sulle categorie che `tokens.py` misura gia' (`system`, `card`,
`interfaces`, `file_read_in_card`, `file_read_outside_card`, `tool_output`,
`agent_messages`, ...). `top` dice quali sono le due piu' pesanti nel run
corrente; gli altri comandi sono gli interventi.

  top         le categorie piu' pesanti di .sjck/tokens.json + interventi utili
  interfaces  interfacce dello scout riusabili per hash dei file sorgente
              (record | check | reuse) -> un nodo scout in meno = un avvio a
              freddo in meno (`system`) e nessuna rilettura (`file_read_in_card`)
  card        la card ridotta alle sezioni che servono a UN ruolo (`card`)
  state       goal + il nodo + le sue deps, invece di tutto state.json (`card`)
  prompt      prompt del nodo con la parte STABILE in testa (prompt cache:
              meno `input`/`cache_creation` al lancio di ogni nodo)

Niente rete, niente scritture fuori da .sjck/. Non fallisce in modo rumoroso:
se un dato manca, lo dice e lascia decidere all'orchestratore.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cards import parse_card, section_paths  # noqa: E402

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".sjck", ".venv", "venv", "dist", "build"}
MAX_FILES = 400          # tetto per una voce di cartella: oltre, l'hash e' parziale e lo dichiara

# Sezioni della card per ruolo (ordine della card). "Leggi" serve solo a chi
# deve aprire i file; "Correzioni richieste" solo a chi sta ritentando.
ROLE_SECTIONS = {
    "implementer": ("Obiettivo", "Puoi modificare", "Leggi", "Criteri di accettazione",
                    "Fuori scope", "Correzioni richieste"),
    "scout": ("Obiettivo", "Puoi modificare", "Leggi", "Criteri di accettazione", "Fuori scope"),
    "validator": ("Obiettivo", "Puoi modificare", "Criteri di accettazione", "Fuori scope"),
    "critic": ("Obiettivo", "Criteri di accettazione"),
    "reviewer": ("Obiettivo", "Criteri di accettazione", "Fuori scope"),
}
CARD_ORDER = ("Obiettivo", "Puoi modificare", "Leggi", "Criteri di accettazione",
              "Fuori scope", "Correzioni richieste")

ACTIONS = {
    "system": "meno avvii a freddo: `precheck.py` evita il validatore LLM quando i criteri sono "
              "deterministici, `context.py interfaces reuse` salta lo scout se i file non sono cambiati",
    "file_read_in_card": "interfacce riusate per hash invece di rileggere i file "
                         "(`context.py interfaces record|reuse`)",
    "card": "card per ruolo: `context.py card --role validator` (niente sezione Leggi)",
    "interfaces": "interfacce piu' corte (max ~80 righe, solo firme e percorso:riga)",
    "tool_output": "leggi a range (offset/limit) o grep prima, invece dell'output intero",
    "agent_messages": "out JSON piu' corti: summary <= 3 righe, nessun contenuto di file",
    "file_read_outside_card": "card povera: aggiungi i file che sono serviti o estrai un'interfaccia",
    "thinking": "il thinking resta in contesto: abbassa l'effort del nodo o dividilo",
    "reminders": "meno reminder: prompt piu' corti e meno tool nel nodo",
    "other": "testo libero nel prompt: passa gli ID e lascia i file alla card",
}


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def _g(root, *parts):
    return os.path.join(root, ".sjck", *parts)


def read_card(root, nid):
    try:
        with open(_g(root, "cards", nid + ".md"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


# ---------------------------------------------------------------- top

def categories(root):
    """Categorie sommate su tutti i nodi di .sjck/tokens.json."""
    data = read_json(_g(root, "tokens.json")) or {}
    tot = {}
    for e in (data.get("by_node") or {}).values():
        for c, v in ((e or {}).get("categories") or {}).items():
            if isinstance(v, (int, float)):
                tot[c] = tot.get(c, 0) + v
    return tot


def top(root, n=2):
    tot = categories(root)
    total = sum(tot.values())
    rows = sorted(tot.items(), key=lambda kv: -kv[1])
    out = {"total": total,
           "categories": [{"category": c, "tokens": int(v),
                            "share": round(100.0 * v / total, 1) if total else 0.0}
                           for c, v in rows]}
    out["top"] = [dict(r, action=ACTIONS.get(r["category"], "")) for r in out["categories"][:n]]
    if not total:
        out["note"] = "nessun dato: .sjck/tokens.json manca o non ha categorie"
    return out


# ---------------------------------------------------- interfacce per hash

def _hash_file(path):
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _expand(root, entry):
    """Una voce (file o cartella) -> lista di percorsi relativi, ordinata."""
    rel = entry.replace("\\", "/").lstrip("./").rstrip("/")
    full = os.path.join(root, rel)
    if os.path.isfile(full):
        return [rel], False
    if not os.path.isdir(full):
        return [], False
    found = []
    for d, dirs, files in os.walk(full):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        for f in sorted(files):
            if f.startswith(".") or f.endswith(".pyc"):
                continue
            found.append(os.path.relpath(os.path.join(d, f), root).replace("\\", "/"))
            if len(found) >= MAX_FILES:
                return sorted(found), True
    return sorted(found), False


def fingerprint(root, entries):
    """{percorso: sha1} per le voci date; None dove il file non esiste."""
    out = {}
    partial = False
    for e in entries or ():
        paths, cut = _expand(root, e)
        partial = partial or cut
        if not paths:
            out[e.replace("\\", "/").lstrip("./")] = None      # manca: cambiera' appena esiste
        for p in paths:
            out[p] = _hash_file(os.path.join(root, p))
    return out, partial


def iface_meta_path(root, name):
    return _g(root, "interfaces", name + ".json")


def iface_md_path(root, name):
    return _g(root, "interfaces", name + ".md")


def record(root, name, entries):
    """Registra l'hash dei file da cui l'interfaccia e' stata estratta."""
    fp, partial = fingerprint(root, entries)
    meta = {"name": name, "files": fp, "sources": sorted(entries or ()),
            "partial": partial, "kit": "sjck-graph"}
    write_json(iface_meta_path(root, name), meta)
    return meta


def check(root, name, base=None):
    """fresh | stale | missing per un'interfaccia (base = cartella alternativa)."""
    d = base or _g(root, "interfaces")
    md = os.path.join(d, name + ".md")
    meta = read_json(os.path.join(d, name + ".json"))
    if not os.path.isfile(md) or not isinstance(meta, dict) or not isinstance(meta.get("files"), dict):
        return {"name": name, "status": "missing", "changed": []}
    now, _ = fingerprint(root, meta.get("sources") or list(meta["files"]))
    changed = sorted(p for p, h in meta["files"].items() if now.get(p) != h)
    changed += sorted(p for p in now if p not in meta["files"])
    if changed:
        return {"name": name, "status": "stale", "changed": changed[:20]}
    return {"name": name, "status": "fresh", "changed": [], "path": md,
            "partial": bool(meta.get("partial"))}


def _archives(root):
    base = _g(root, "archive")
    try:
        return [os.path.join(base, d, "interfaces") for d in sorted(os.listdir(base), reverse=True)]
    except OSError:
        return []


def reuse(root, name):
    """Interfaccia riusabile? Se e' in un archivio e i file non sono cambiati, la riporta su."""
    r = check(root, name)
    if r["status"] == "fresh":
        return dict(r, reused="in place")
    for d in _archives(root):
        a = check(root, name, base=d)
        if a["status"] == "fresh":
            try:
                os.makedirs(_g(root, "interfaces"), exist_ok=True)
                shutil.copyfile(os.path.join(d, name + ".md"), iface_md_path(root, name))
                shutil.copyfile(os.path.join(d, name + ".json"), iface_meta_path(root, name))
            except OSError:
                continue
            return dict(a, path=iface_md_path(root, name), reused="from archive", archive=d)
    return r


def iface_names_of(root, nid):
    """Nomi delle interfacce che un nodo scrive, dalla sezione "Puoi modificare"."""
    text = read_card(root, nid) or ""
    names = []
    for p in section_paths(text, "Puoi modificare"):
        p = p.replace("\\", "/")
        if ".sjck/interfaces/" in p:
            names.append(os.path.splitext(os.path.basename(p))[0])
    return names


def skippable(root):
    """Nodi scout che si possono saltare: le loro interfacce sono fresche."""
    state = read_json(_g(root, "state.json")) or {}
    reusable, regenerate = [], []
    for n in state.get("nodes", []) or []:
        if not isinstance(n, dict) or n.get("agent") != "scout":
            continue
        if n.get("status") not in ("pending", None, ""):
            continue
        names = iface_names_of(root, n.get("id"))
        if not names:
            regenerate.append({"id": n.get("id"), "reason": "nessuna interfaccia nella card"})
            continue
        res = [reuse(root, nm) for nm in names]
        if all(x["status"] == "fresh" for x in res):
            reusable.append({"id": n.get("id"), "interfaces": names,
                             "how": [x.get("reused") for x in res]})
        else:
            regenerate.append({"id": n.get("id"), "interfaces": names,
                               "reason": "; ".join("%s: %s" % (x["name"], x["status"]) for x in res)})
    return {"reusable": reusable, "regenerate": regenerate}


# ------------------------------------------------------ card e stato ridotti

def card_slice(text, role, attempt=0):
    """La card ridotta alle sezioni che servono a quel ruolo."""
    want = list(ROLE_SECTIONS.get(role) or CARD_ORDER)
    if role == "validator" and attempt > 0 and "Correzioni richieste" not in want:
        want.append("Correzioni richieste")   # al retry deve verificare le correzioni
    sections = parse_card(text or "")
    parts = []
    for s in CARD_ORDER:
        if s in want and (sections.get(s) or "").strip():
            parts.append("## %s\n%s" % (s, sections[s].strip()))
    return "\n\n".join(parts) + ("\n" if parts else "")


def state_slice(root, nid):
    """goal + il nodo + le sue deps (stato e file): non tutto state.json."""
    state = read_json(_g(root, "state.json")) or {}
    nodes = {n.get("id"): n for n in state.get("nodes", []) or [] if isinstance(n, dict)}
    me = nodes.get(nid) or {}
    keep = ("id", "title", "agent", "status", "files", "attempts", "model", "effort", "budget")
    out = {"goal": state.get("goal"), "mode": state.get("mode"),
           "node": {k: me[k] for k in keep if k in me},
           "deps": [{k: nodes[d][k] for k in ("id", "status", "files") if k in nodes[d]}
                    for d in (me.get("deps") or []) if d in nodes]}
    return out


def node_prompt(root, nid, role, script="", attempt=0):
    """Prompt del nodo: prima la parte STABILE (cacheabile), poi quella variabile."""
    stable = [
        "ruolo: %s" % role,
        "script: %s" % (script or "(vedi reference/scripts.md)"),
        "contratto: leggi solo la card qui sotto e i file che indica; scrivi il tuo out JSON in",
        ".sjck/out/ e rispondi SOLO con quel JSON; i problemi fuori scope si registrano, non si",
        "sistemano.",
    ]
    node = read_json(_g(root, "state.json")) or {}
    budget = {}
    for n in node.get("nodes", []) or []:
        if isinstance(n, dict) and n.get("id") == nid:
            budget = n.get("budget") or {}
            break
    volatile = ["--- nodo ---", "id: %s" % nid]
    if budget.get("tool_calls"):
        volatile.append("budget: max %s tool call" % budget["tool_calls"])
    if attempt:
        volatile.append("tentativo: %d (vedi Correzioni richieste)" % attempt)
    text = read_card(root, nid)
    if text is None:
        volatile.append("card: MANCANTE (.sjck/cards/%s.md)" % nid)
    else:
        volatile.append("")
        volatile.append(card_slice(text, role, attempt).rstrip())
    return "\n".join(stable + volatile) + "\n"


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="Dieta del contesto di un run sjck-graph")
    ap.add_argument("--cwd", default=".")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("top", help="categorie piu' pesanti e interventi")
    p.add_argument("-n", type=int, default=2)

    p = sub.add_parser("interfaces", help="riuso delle interfacce per hash")
    p.add_argument("action", choices=("record", "check", "reuse", "skip"))
    p.add_argument("--name")
    p.add_argument("--file", action="append", default=[])
    p.add_argument("--from-card")

    p = sub.add_parser("card", help="card ridotta a un ruolo")
    p.add_argument("--id", required=True)
    p.add_argument("--role", default="implementer")
    p.add_argument("--attempt", type=int, default=0)
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("state", help="goal + nodo + deps")
    p.add_argument("--id", required=True)

    p = sub.add_parser("prompt", help="prompt del nodo, parte stabile in testa")
    p.add_argument("--id", required=True)
    p.add_argument("--role", default="implementer")
    p.add_argument("--script", default="")
    p.add_argument("--attempt", type=int, default=0)

    args = ap.parse_args(argv)
    root = os.path.abspath(args.cwd)
    if args.cmd == "top":
        print(json.dumps(top(root, args.n), indent=1, ensure_ascii=False))
        return 0
    if args.cmd == "interfaces":
        if args.action == "skip":
            print(json.dumps(skippable(root), indent=1, ensure_ascii=False))
            return 0
        if args.action == "record":
            if not args.name:
                print("serve --name", file=sys.stderr)
                return 3
            entries = list(args.file)
            if args.from_card:
                entries += section_paths(read_card(root, args.from_card) or "", "Leggi")
            if not entries:
                print("nessun file: usa --file o --from-card", file=sys.stderr)
                return 3
            print(json.dumps(record(root, args.name, entries), indent=1, ensure_ascii=False))
            return 0
        names = [args.name] if args.name else sorted(
            os.path.splitext(f)[0] for f in os.listdir(_g(root, "interfaces"))
            if f.endswith(".md")) if os.path.isdir(_g(root, "interfaces")) else []
        fn = reuse if args.action == "reuse" else check
        res = [fn(root, nm) for nm in names]
        print(json.dumps(res if len(res) != 1 else res[0], indent=1, ensure_ascii=False))
        return 0 if res and all(r["status"] == "fresh" for r in res) else 1
    if args.cmd == "card":
        text = read_card(root, args.id)
        if text is None:
            print("card mancante: .sjck/cards/%s.md" % args.id, file=sys.stderr)
            return 3
        sliced = card_slice(text, args.role, args.attempt)
        if args.json:
            print(json.dumps({"id": args.id, "role": args.role, "chars": len(sliced),
                              "chars_full": len(text), "text": sliced}, indent=1, ensure_ascii=False))
        else:
            print("# %s (%s)\n%s" % (args.id, args.role, sliced), end="")
        return 0
    if args.cmd == "state":
        print(json.dumps(state_slice(root, args.id), indent=1, ensure_ascii=False))
        return 0
    if args.cmd == "prompt":
        sys.stdout.write(node_prompt(root, args.id, args.role, args.script, args.attempt))
        return 0
    ap.print_help()
    return 3


if __name__ == "__main__":
    sys.exit(main())
