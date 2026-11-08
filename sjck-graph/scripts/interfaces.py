"""Riuso delle interfacce dello scout via hash dei file sorgente.

Registro: .sjck/interfaces/.hashes.json  {nome: {percorso: sha256}}.
Solo standard library. CLI: interfaces.py register|check|invalidate <nome> [file...]
"""
import hashlib
import json
import os
import sys

REGISTRY = os.path.join(".sjck", "interfaces", ".hashes.json")
FRESH, STALE = "fresh", "stale"


def file_hash(path):
    """sha256 del contenuto, None se il file non esiste."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _load(root):
    try:
        with open(os.path.join(root, REGISTRY), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(root, data):
    p = os.path.join(root, REGISTRY)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=True)


def register(root, name, sources):
    """Registra gli hash dei sorgenti (percorsi relativi a root) di <name>."""
    data = _load(root)
    data[name] = {s: file_hash(os.path.join(root, s)) for s in sources}
    _save(root, data)
    return data[name]


def check(root, name):
    """'fresh' se .sjck/interfaces/<name>.md esiste e nessun sorgente e' cambiato,
    altrimenti 'stale' (mai registrata, sorgente modificato/sparito, md assente)."""
    rec = _load(root).get(name)
    md = os.path.join(root, ".sjck", "interfaces", name + ".md")
    if not rec or not os.path.isfile(md):
        return STALE
    for src, h in rec.items():
        if h is None or file_hash(os.path.join(root, src)) != h:
            return STALE
    return FRESH


def invalidate(root, name):
    """Dimentica <name>: il prossimo check e' 'stale'. True se esisteva."""
    data = _load(root)
    had = data.pop(name, None) is not None
    _save(root, data)
    return had


def main(argv):
    if len(argv) < 3 or argv[1] not in ("register", "check", "invalidate"):
        print("uso: interfaces.py register|check|invalidate <nome> [file...]",
              file=sys.stderr)
        return 2
    cmd, name = argv[1], argv[2]
    if cmd == "register":
        register(".", name, argv[3:])
    elif cmd == "invalidate":
        invalidate(".", name)
    else:
        res = check(".", name)
        print(res)
        return 0 if res == FRESH else 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
