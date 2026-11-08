"""Parser delle card .sjck/cards/<ID>.md. Solo standard library."""
import re

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
