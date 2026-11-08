"""Validazione a due livelli. Solo standard library, nessuna rete.

Livello 1 (questo script): esegue i controlli deterministici della sezione
"Criteri di accettazione" della card. Livello 2 (LLM): parte solo se il
livello 1 e' `ambiguous` o se la card lo richiede (`validator: llm`).

Un criterio e' eseguibile se ha la forma  `comando` -> esito atteso
(freccia `->` o `→`). Esiti attesi riconosciuti: `exit N`, `0 fallimenti`,
`0 failures`, `ok`, `pass`; esito assente dopo la freccia = exit 0.
Gli item senza `comando` + freccia sono prosa: non si eseguono.

Uso:  checks.py run <ID> [--cwd DIR]   -> JSON; exit 0 pass, 1 fail, 2 ambiguous
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
    """-> (lista di {'command','expect'}, numero di item prosa/non interpretabili)."""
    found, other = [], 0
    for item in cards.section_items(card_text, "Criteri di accettazione"):
        m = _CRIT.match(item)
        if not m:
            other += 1
            continue
        cmd, exp = m.group(1).strip(), m.group(2).strip()
        code = None
        if not exp:
            code = 0
        elif _EXIT.search(exp):
            code = int(_EXIT.search(exp).group(1))
        elif _OK.search(exp):
            code = 0
        found.append({"command": cmd, "expect": exp, "exit": code})
    return found, other


def requires_llm(card_text):
    body = cards.parse_card(card_text).get("Criteri di accettazione", "")
    return bool(_LLM.search(body))


def run_checks(card_text, cwd=".", timeout=600):
    """Esegue il livello 1. -> {'outcome','checks','output','llm_required'}."""
    found, _ = parse_checks(card_text)
    results, output = [], []
    for c in found:
        r = {"name": c["command"], "expect": c["expect"]}
        if c["exit"] is None:
            r["status"] = "ambiguous"
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
        if r["status"] == "fail":
            output.append("$ %s (atteso exit %d)\n%s" % (c["command"], c["exit"], text[-_TAIL:]))
    sts = [r["status"] for r in results]
    if "fail" in sts:
        outcome = "fail"
    elif not sts or "ambiguous" in sts:
        outcome = "ambiguous"  # controllo assente != controllo superato
    else:
        outcome = "pass"
    return {"outcome": outcome, "checks": results, "output": "\n\n".join(output),
            "llm_required": requires_llm(card_text)}


def validate(card_text, run_llm, cwd=".", config=None):
    """Orchestra i due livelli. `run_llm(model)` e' il lancio del validatore LLM
    (iniettato: nei test e' una spia). Su `fail` NON viene chiamato."""
    cfg = config or load_config(cwd)
    res = run_checks(card_text, cwd, cfg.get("timeout", 600))
    res["model"] = cfg["model"]
    if res["outcome"] == "fail":
        res.update(action="retry", llm_invoked=False, verdict="fail")
    elif res["outcome"] == "ambiguous" or res["llm_required"]:
        res.update(action="llm", llm_invoked=True, verdict=run_llm(cfg["model"]))
    else:
        res.update(action="done", llm_invoked=False, verdict="pass")
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
    cfg = load_config(a.cwd)
    if a.cmd == "model":
        print(cfg["model"])
        return 0
    path = os.path.join(a.cwd, ".sjck", "cards", a.id + ".md")
    with open(path, encoding="utf-8") as f:
        res = run_checks(f.read(), a.cwd, cfg.get("timeout", 600))
    res.update(id=a.id, model=cfg["model"],
               invoke_llm=res["outcome"] == "ambiguous" or
               (res["outcome"] == "pass" and res["llm_required"]))
    print(json.dumps(res, ensure_ascii=False))
    return {"pass": 0, "fail": 1, "ambiguous": 2}[res["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
