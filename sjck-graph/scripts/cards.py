"""Parser delle card .sjck/cards/<ID>.md. Solo standard library.

CLI (l'orchestratore lavora da Bash):
  cards.py sections <ID> [--cwd D] [--wanted "A,B"]  scrive la card ridotta in
                                  .sjck/out/<ID>.card.md e ne stampa il percorso
  cards.py state <ID> [--cwd D]   fetta di .sjck/state.json (nodo + deps), JSON
  cards.py prompt --system F --fuori-scope F --budget F --card F [--correzioni F]
"""
import argparse
import json
import os
import re
import sys

SECTIONS = ("Obiettivo", "Puoi modificare", "Leggi",
            "Criteri di accettazione", "Fuori scope", "Correzioni richieste")

_ITEM = re.compile(r"^\s*(?:[-*]\s+(?:\[[ xX]\]\s+)?|\d+[.)]\s+)(.*\S)\s*$")


def _title(raw):
    t = re.sub(r"\([^)]*\)", "", raw)
    return re.sub(r"\s+", " ", t).strip()


def parse_card(text):
    out = {}
    cur = None
    buf = []
    fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            if cur is not None:
                out[cur] = "\n".join(buf).strip("\n")
            cur = _title(line[3:])
            buf = []
        elif cur is not None:
            buf.append(line)
    if cur is not None:
        out[cur] = "\n".join(buf).strip("\n")
    return out


def section_items(text, section):
    body = parse_card(text).get(section)
    if not body:
        return []
    items = []
    for line in body.splitlines():
        m = _ITEM.match(line)
        if m:
            items.append(m.group(1).strip())
        elif items and line.startswith((" ", "\t")) and line.strip():
            items[-1] += " " + line.strip()  # riga di continuazione
    return items


def section_paths(text, section):
    paths = []
    for item in section_items(text, section):
        m = re.search(r"`([^`]+)`", item)
        tok = m.group(1) if m else (item.split() or [""])[0]
        paths.append(tok.rstrip(".,;:)"))
    return paths


def count_criteria(text):
    return len(section_items(text, "Criteri di accettazione"))


def select_sections(text, wanted):
    """Titolo + solo le sezioni `wanted` (nell'ordine della card)."""
    parsed = parse_card(text)
    first = text.splitlines()[0] if text.startswith("# ") else ""
    parts = [first] if first else []
    for title, body in parsed.items():
        if title in wanted:
            parts.append("## " + title + "\n" + body)
    return "\n\n".join(parts) + "\n"


def select_state(state, node_id):
    """Dallo stato solo il nodo e le sue deps (id/status/files per le deps)."""
    nodes = {n.get("id"): n for n in state.get("nodes", []) if isinstance(n, dict)}
    node = nodes.get(node_id)
    if node is None:
        return {"nodes": []}
    out = [node]
    for d in node.get("deps") or []:
        dn = nodes.get(d)
        if dn is not None:
            out.append({k: dn[k] for k in ("id", "status", "files") if k in dn})
    return {"nodes": out}


# Ordine del prompt: prefisso invariante (cacheable) poi coda variabile.
# Vedi docs/context-diet.md.
INVARIANT_ORDER = ("system", "fuori_scope", "budget")
VARIABLE_ORDER = ("card", "correzioni")


def build_prompt(system, fuori_scope, budget, card, correzioni=""):
    """Assembla il prompt: system, fuori scope, budget, poi card e correzioni.
    Le prime tre parti non dipendono dal nodo ne' dal tentativo."""
    parts = [system, fuori_scope, budget, card, correzioni]
    return "\n\n".join(p.strip("\n") for p in parts if p and p.strip()) + "\n"


DIET_SECTIONS = ("Puoi modificare", "Leggi", "Criteri di accettazione", "Fuori scope")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Card ridotte, stato selettivo, prompt ordinato")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("sections")
    a.add_argument("id")
    a.add_argument("--cwd", default=".")
    a.add_argument("--wanted", default=",".join(DIET_SECTIONS))
    b = sub.add_parser("state")
    b.add_argument("id")
    b.add_argument("--cwd", default=".")
    c = sub.add_parser("prompt")
    for k in ("system", "fuori-scope", "budget", "card"):
        c.add_argument("--" + k, required=True)
    c.add_argument("--correzioni")
    n = ap.parse_args(argv)
    try:
        if n.cmd == "sections":
            text = _read(os.path.join(n.cwd, ".sjck", "cards", n.id + ".md"))
            wanted = [w.strip() for w in n.wanted.split(",") if w.strip()]
            out = os.path.join(n.cwd, ".sjck", "out")
            os.makedirs(out, exist_ok=True)
            dest = os.path.join(out, n.id + ".card.md")
            with open(dest, "w", encoding="utf-8") as f:
                f.write(select_sections(text, wanted))
            print(dest)
        elif n.cmd == "state":
            state = json.loads(_read(os.path.join(n.cwd, ".sjck", "state.json")))
            print(json.dumps(select_state(state, n.id), ensure_ascii=False))
        else:
            corr = _read(n.correzioni) if n.correzioni else ""
            sys.stdout.write(build_prompt(_read(n.system), _read(n.fuori_scope),
                                          _read(n.budget), _read(n.card), corr))
    except (OSError, ValueError) as e:
        print("cards.py: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
