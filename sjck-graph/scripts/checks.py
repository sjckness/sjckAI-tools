"""Validazione a due livelli. Solo standard library, nessuna rete.

Livello 1 (questo script): esegue i controlli deterministici della sezione
"Criteri di accettazione" della card. Livello 2 (LLM): parte solo se il
livello 1 e' `ambiguous` o se la card lo richiede (`validator: llm`).

Un criterio e' eseguibile se ha la forma  `comando` -> esito atteso
(freccia `->` o `→`). Esiti attesi riconosciuti: `exit N`, `0 fallimenti`,
`0 failures`, `ok`, `pass`; esito assente dopo la freccia = exit 0.
Gli item senza `comando` + freccia sono prosa: non si eseguono e restano
al livello 2 (`residual`). Un esito con "oppure" e' ambiguo: non si esegue.
Il livello 1 NON assolve mai cio' che non ha controllato: se resta anche
un solo criterio non eseguibile l'esito e' `ambiguous`; il livello 2 riceve
`green` (comandi gia' verdi, da non rieseguire) e `residual` (da giudicare).

Uso:  checks.py run <ID> [--cwd DIR]   -> JSON (+ .sjck/out/<ID>.l1.json);
                                          exit 0 pass, 1 fail, 2 ambiguous,
                                          3 configurazione non valida
      checks.py model [--cwd DIR]      -> modello del validatore LLM
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cards  # noqa: E402

DEFAULT_CONFIG = os.path.join(HERE, "..", "config", "validation.json")
MODELS = ("haiku", "sonnet", "opus", "fable", "inherit")
_CRIT = re.compile(r"^\**`([^`]+)`\**\s*(?:→|->)\s*(.*)$")
_EXIT = re.compile(r"\bexit(?:\s+code)?\s*(\d+)", re.I)
_OK = re.compile(r"\b0\s+(?:fallimenti|failures|errori|errors)\b|\b(?:ok|pass|passa)\b", re.I)
_LLM = re.compile(r"^\s*(?:[-*]\s*)?validator\s*:\s*llm\b", re.I | re.M)
_TAIL = 4000


def load_config(cwd="."):
    """Default versionato + override `.sjck/validation.json` (vince)."""
    with open(DEFAULT_CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    over = os.path.join(cwd, ".sjck", "validation.json")
    if os.path.isfile(over):
        with open(over, encoding="utf-8") as f:
            cfg.update(json.load(f))
    if cfg.get("model") not in MODELS:
        raise ValueError("modello non valido: %r (ammessi: %s)"
                         % (cfg.get("model"), ", ".join(MODELS)))
    return cfg


def parse_checks(card_text):
    """-> (lista di {'command','expect','exit'}, item prosa non eseguibili)."""
    found, other = [], []
    for item in cards.section_items(card_text, "Criteri di accettazione"):
        if _LLM.match(item):
            continue  # marcatore, non un criterio
        m = _CRIT.match(item)
        if not m:
            other.append(item)
            continue
        cmd, exp = m.group(1).strip(), m.group(2).strip()
        code = None
        if not exp:
            code = 0
        elif re.search(r"\boppure\b", exp, re.I):
            code = None
        elif _EXIT.search(exp):
            code = int(_EXIT.search(exp).group(1))
        elif _OK.search(exp):
            code = 0
        found.append({"command": cmd, "expect": exp, "exit": code})
    return found, other


def requires_llm(card_text):
    body = cards.parse_card(card_text).get("Criteri di accettazione", "")
    return bool(_LLM.search(body))


def decide(res):
    """Unica decisione livello 1 -> livello 2: (action, invoke_llm).
    fail -> mai LLM; ambiguous o card che lo richiede -> LLM; altrimenti done."""
    if res["outcome"] == "fail":
        return "retry", False
    if res["outcome"] == "ambiguous" or res["llm_required"]:
        return "llm", True
    return "done", False


def run_checks(card_text, cwd=".", timeout=600):
    """Esegue il livello 1.
    -> {'outcome','checks','output','green','residual','llm_required'}."""
    found, other = parse_checks(card_text)
    results, output, green = [], [], []
    residual = list(other)
    for c in found:
        r = {"name": c["command"], "expect": c["expect"]}
        if c["exit"] is None:
            r["status"] = "ambiguous"
            residual.append("`%s` -> %s" % (c["command"], c["expect"]))
            results.append(r)
            continue
        try:
            p = subprocess.run(c["command"], shell=True, cwd=cwd, timeout=timeout,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True)
            r["code"], text = p.returncode, p.stdout or ""
            r["status"] = "pass" if p.returncode == c["exit"] else "fail"
        except subprocess.TimeoutExpired:
            r["status"], text = "fail", "timeout dopo %ss" % timeout
        results.append(r)
        if r["status"] == "pass":
            green.append(c["command"])
        else:
            output.append("$ %s (atteso exit %d)\n%s" % (c["command"], c["exit"], text[-_TAIL:]))
    if any(r["status"] == "fail" for r in results):
        outcome = "fail"
    elif residual or not results:
        outcome = "ambiguous"  # un controllo assente non e' un controllo superato
    else:
        outcome = "pass"
    return {"outcome": outcome, "checks": results, "output": "\n\n".join(output),
            "green": green, "residual": residual,
            "llm_required": requires_llm(card_text)}


def validate(card_text, run_llm, cwd=".", config=None):
    """Orchestra i due livelli. `run_llm(model, green, residual)` e' il lancio del
    validatore LLM (iniettato: nei test e' una spia). Su `fail` NON viene chiamato."""
    cfg = config or load_config(cwd)
    res = run_checks(card_text, cwd, cfg.get("timeout", 600))
    res["model"] = cfg["model"]
    res["action"], res["invoke_llm"] = decide(res)
    res["llm_invoked"] = res["invoke_llm"]
    res["verdict"] = {"retry": "fail", "done": "pass"}.get(res["action"])
    if res["invoke_llm"]:
        res["verdict"] = run_llm(cfg["model"], res["green"], res["residual"])
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("id")
    r.add_argument("--cwd", default=".")
    m = sub.add_parser("model")
    m.add_argument("--cwd", default=".")
    a = ap.parse_args(argv)
    try:
        cfg = load_config(a.cwd)
    except (ValueError, OSError) as e:
        print("checks.py: configurazione non valida: %s" % e, file=sys.stderr)
        return 3
    if a.cmd == "model":
        print(cfg["model"])
        return 0
    path = os.path.join(a.cwd, ".sjck", "cards", a.id + ".md")
    with open(path, encoding="utf-8") as f:
        res = run_checks(f.read(), a.cwd, cfg.get("timeout", 600))
    res["action"], res["invoke_llm"] = decide(res)
    res.update(id=a.id, model=cfg["model"])
    out = os.path.join(a.cwd, ".sjck", "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, a.id + ".l1.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    print(json.dumps(res, ensure_ascii=False))
    return {"pass": 0, "fail": 1, "ambiguous": 2}[res["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
