#!/usr/bin/env python3
"""Prezzi dei modelli e configurazione del kit sjck-graph (v0.5).

Solo standard library, Python 3.9+, nessuna chiamata di rete.

Due tabelle, stesso meccanismo di override: il file distribuito col kit e'
solo il default, e ogni livello successivo sovrascrive il precedente SENZA
toccare il codice.

Ordine (l'ultimo vince):
  1. `scripts/prices.json` / i default qui sotto  (distribuiti)
  2. `~/.sjck/prices.json` / `~/.sjck/config.json`  (utente)
  3. `<root>/.sjck/prices.json` / `<root>/.sjck/config.json`  (progetto)
  4. `$SJCK_PRICES` / `$SJCK_CONFIG`  (percorso esplicito)
  5. per il validatore: `$SJCK_VALIDATOR_MODEL`, `$SJCK_VALIDATOR_EFFORT`

Prezzi: USD per milione di token, per modello, con `input` e `output`.
Cache read e cache write si ricavano da `cache_multipliers` (moltiplicatori
rispetto all'input: 0,1 e 1,25) salvo prezzo esplicito `cache_read` /
`cache_write` sul modello, che vince. Un modello sconosciuto NON viene
inventato: `rates()` ritorna None e il chiamante mostra solo i token.
Un override puo' togliere un modello mettendolo a `null`.

API:
    load_prices(root=None) -> tabella effettiva (con `sources`)
    rates(model, table)    -> {input, output, cache_read, cache_creation} USD/token, o None
    cost_of(counts, model, table) -> (usd, priced: bool)
    load_config(root=None) -> {"validator": {model, effort, timeout_s, always_llm}, ...}

CLI:
    config.py prices [--cwd DIR] [--model NOME]
    config.py validator [--cwd DIR]
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHIPPED_PRICES = os.path.join(HERE, "prices.json")

KEYS = ("input", "output", "cache_read", "cache_creation")

DEFAULT_CACHE_MULTIPLIERS = {"cache_read": 0.1, "cache_creation": 1.25}

# Default del validatore: identici al frontmatter di sjck-validator.md, cosi'
# chi non configura niente non cambia comportamento.
DEFAULT_CONFIG = {
    "validator": {
        "model": "sonnet",      # haiku|sonnet|opus|fable|inherit
        "effort": "high",       # low|medium|high|xhigh|max
        "timeout_s": 300,       # per comando deterministico
        "always_llm": False,    # True = il validatore LLM parte sempre
    },
}

# Prefissi dei nomi modello sui vari provider: si tolgono prima del confronto.
_PREFIXES = ("us.", "eu.", "apac.", "global.", "anthropic.", "anthropic/")

# Coda ammessa nel confronto per prefisso: niente, una data, oppure "latest".
_SNAPSHOT = re.compile(r"^(|-\d{8}|-latest)$")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _home(name):
    return os.path.join(os.path.expanduser("~"), ".sjck", name)


def _overlay_paths(root, name, env):
    paths = [_home(name)]
    if root:
        paths.append(os.path.join(root, ".sjck", name))
    p = os.environ.get(env)
    if p:
        paths.append(p)
    return paths


def load_prices(root=None):
    """Tabella prezzi effettiva: default distribuito + override utente/progetto/env."""
    table = _read_json(SHIPPED_PRICES) or {}
    table.setdefault("models", {})
    table.setdefault("cache_multipliers", dict(DEFAULT_CACHE_MULTIPLIERS))
    sources = [SHIPPED_PRICES] if os.path.exists(SHIPPED_PRICES) else []
    for path in _overlay_paths(root, "prices.json", "SJCK_PRICES"):
        over = _read_json(path)
        if not over:
            continue
        sources.append(path)
        for k, v in over.items():
            if k == "models" and isinstance(v, dict):
                for name, m in v.items():
                    if m is None:
                        table["models"].pop(name, None)      # modello tolto: solo token
                    elif isinstance(m, dict):
                        cur = table["models"].get(name)
                        table["models"][name] = dict(cur, **m) if isinstance(cur, dict) else dict(m)
            elif k == "cache_multipliers" and isinstance(v, dict):
                table["cache_multipliers"].update(
                    {kk: vv for kk, vv in v.items() if isinstance(vv, (int, float))})
            else:
                table[k] = v
    table["sources"] = sources
    return table


def normalize_model(model):
    """Nome modello confrontabile: minuscolo, senza prefisso provider ne' suffisso di versione."""
    name = str(model or "").strip().lower()
    for p in _PREFIXES:
        if name.startswith(p):
            name = name[len(p):]
    for sep in ("@", ":"):
        if sep in name:
            name = name.split(sep, 1)[0]
    if name.endswith("-v1"):
        name = name[:-3]
    return name


def rates(model, table=None):
    """USD per singolo token, per tipo. None se il modello non e' in tabella."""
    table = table if isinstance(table, dict) else load_prices()
    models = table.get("models") or {}
    name = normalize_model(model)
    if not name or name.startswith("<"):
        return None
    entry = models.get(name)
    if not isinstance(entry, dict):
        # Snapshot con data in coda (claude-x-20260401, claude-x-latest): stesso prezzo.
        # Una versione in piu' NO: claude-opus-5-5 non e' claude-opus-5.
        best = ""
        for key, val in models.items():
            k = normalize_model(key)
            if not (isinstance(val, dict) and k and name.startswith(k) and len(k) > len(best)):
                continue
            if _SNAPSHOT.match(name[len(k):]):
                best, entry = k, val
        if not isinstance(entry, dict):
            return None
    try:
        inp = float(entry["input"])
        out = float(entry["output"])
    except (KeyError, TypeError, ValueError):
        return None
    mult = table.get("cache_multipliers") or DEFAULT_CACHE_MULTIPLIERS

    def _m(key):
        v = mult.get(key, DEFAULT_CACHE_MULTIPLIERS[key])
        return float(v) if isinstance(v, (int, float)) else DEFAULT_CACHE_MULTIPLIERS[key]

    cr = entry.get("cache_read")
    cw = entry.get("cache_write", entry.get("cache_creation"))
    cr = float(cr) if isinstance(cr, (int, float)) else inp * _m("cache_read")
    cw = float(cw) if isinstance(cw, (int, float)) else inp * _m("cache_creation")
    return {"input": inp / 1e6, "output": out / 1e6,
            "cache_read": cr / 1e6, "cache_creation": cw / 1e6}


def cost_of(counts, model, table=None):
    """Costo in USD di un gruppo di token. Ritorna (usd, priced)."""
    r = rates(model, table)
    if not r:
        return 0.0, False
    usd = 0.0
    for k in KEYS:
        v = (counts or {}).get(k, 0)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            usd += v * r[k]
    return usd, True


def load_config(root=None):
    """Configurazione effettiva del kit (sezione `validator` e future)."""
    conf = {k: dict(v) for k, v in DEFAULT_CONFIG.items()}
    sources = []
    for path in _overlay_paths(root, "config.json", "SJCK_CONFIG"):
        over = _read_json(path)
        if not over:
            continue
        sources.append(path)
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(conf.get(k), dict):
                conf[k].update(v)
            else:
                conf[k] = v
    env_model = os.environ.get("SJCK_VALIDATOR_MODEL")
    env_effort = os.environ.get("SJCK_VALIDATOR_EFFORT")
    if env_model:
        conf["validator"]["model"] = env_model
        sources.append("$SJCK_VALIDATOR_MODEL")
    if env_effort:
        conf["validator"]["effort"] = env_effort
        sources.append("$SJCK_VALIDATOR_EFFORT")
    conf["sources"] = sources
    return conf


def main(argv):
    root = os.getcwd()
    if "--cwd" in argv:
        root = argv[argv.index("--cwd") + 1]
    cmd = (argv[0] if argv and not argv[0].startswith("-") else "prices")
    if cmd == "validator":
        print(json.dumps(load_config(root), indent=1, ensure_ascii=False))
        return 0
    table = load_prices(root)
    if "--model" in argv:
        name = argv[argv.index("--model") + 1]
        r = rates(name, table)
        if not r:
            print("%s: nessun prezzo in tabella (verranno mostrati solo i token)" % name)
            return 1
        print(json.dumps({"model": name, "usd_per_million": {k: round(v * 1e6, 6) for k, v in r.items()}},
                         indent=1, ensure_ascii=False))
        return 0
    print(json.dumps(table, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
