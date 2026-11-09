#!/usr/bin/env python3
"""Validazione a due livelli di un nodo sjck-graph (v0.5). Standard library, 3.9+.

Livello 1 (qui, gratis): i controlli DETERMINISTICI della card.
  - scope: i file dichiarati in `.sjck/out/<ID>.json` stanno dentro
    "## Puoi modificare"? e il watchdog ha contato scritture fuori card?
  - criteri: ogni criterio di accettazione che contiene un comando
    (`python3 -m unittest ...`, `npm test`, `ruff check .`, ...) viene eseguito.
Livello 2 (il validatore LLM): parte SOLO se l'esito e' ambiguo o la card lo
chiede. Esiti possibili:
  pass    tutti i criteri sono comandi e passano          -> exit 0, nessun LLM
  fail    scope violato o un comando fallisce             -> exit 1, nessun LLM
  unclear criteri non eseguibili, nessun comando, timeout,
          card che chiede il validatore, out JSON mancante -> exit 2, LLM
  errore  card o stato illeggibili                         -> exit 3

Il modello del validatore LLM e' configurabile (piu' piccolo se si vuole):
`validator.model` / `validator.effort` in `.sjck/config.json` (progetto),
`~/.sjck/config.json` (utente), `$SJCK_VALIDATOR_MODEL`, `$SJCK_VALIDATOR_EFFORT`;
default `sonnet`/`high`, come il frontmatter dell'agente. Il valore risolto
finisce in `.sjck/out/<ID>.pre.json` (`llm_validator_model`): l'orchestratore
lo passa come override al lancio.

Una card chiede esplicitamente il livello 2 scrivendo in un criterio
`validator: llm` (oppure "revisione umana", "giudizio"): vedi FORCE_WORDS.

Uso:
  precheck.py --id T01 [--cwd DIR] [--dry-run] [--force-llm] [--timeout 300]
I comandi girano in una shell con cwd = DIR: una card puo' quindi eseguire
codice, esattamente come l'agente che oggi li esegue (vedi docs/limitations.md).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from cards import section_items, section_paths  # noqa: E402

# Primo token (basename) di un comando che possiamo eseguire senza LLM.
RUNNERS = ("python", "python3", "py", "pytest", "unittest", "tox", "nox",
           "npm", "npx", "yarn", "pnpm", "node", "deno", "bun",
           "make", "cmake", "ctest", "colcon", "cargo", "go", "mvn", "gradle",
           "ruff", "flake8", "black", "isort", "mypy", "pyright", "eslint", "tsc", "prettier",
           "bash", "sh", "git", "pip", "pip3", "poetry", "uv", "shellcheck", "gcc", "g++", "clang")

# Parole che in un criterio impongono il livello 2 anche se un comando c'e'.
FORCE_WORDS = ("validator: llm", "validatore: llm", "giudizio", "revisione umana",
               "a giudizio del validatore")

MAX_OUTPUT = 1200     # caratteri di output conservati per ogni comando
_BACKTICK = re.compile(r"`([^`]+)`")


def _g(root, *p):
    return os.path.join(root, ".sjck", *p)


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
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def read_card(root, nid):
    try:
        with open(_g(root, "cards", nid + ".md"), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _runner_ok(cmd, extra=()):
    """True se il primo token del comando e' un runner noto (o configurato)."""
    tok = (cmd.strip().split() or [""])[0]
    tok = tok.strip("\"'")
    if tok.startswith("$"):
        return False
    base = os.path.basename(tok.replace("\\", "/")).lower()
    if base.endswith(".exe"):
        base = base[:-4]
    # python3.12, pip3 -> python, pip (interpreti di un venv)
    short = re.sub(r"[-\d.]+$", "", base)
    extra = tuple(extra or ())
    return base in RUNNERS or base in extra or short in RUNNERS or short in extra


def command_of(item, extra=()):
    """Il comando deterministico di un criterio, oppure None."""
    low = item.lower()
    if any(w in low for w in FORCE_WORDS):
        return None
    for span in _BACKTICK.findall(item):
        cmd = span.strip()
        if _runner_ok(cmd, extra):
            return cmd
    return None


def plan(root, nid, extra=()):
    """Criteri della card divisi in comandi eseguibili e criteri da LLM."""
    text = read_card(root, nid)
    if text is None:
        return None
    items = section_items(text, "Criteri di accettazione")
    cmds, llm = [], []
    for it in items:
        c = command_of(it, extra)
        (cmds if c else llm).append({"criterion": it, "cmd": c} if c else it)
    return {"criteria": items, "commands": cmds, "llm_criteria": llm,
            "allowed": section_paths(text, "Puoi modificare")}


def _norm(p):
    p = str(p or "").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/"), str(p or "").endswith("/")


def covered(path, allowed):
    """Il file sta dentro una voce di "Puoi modificare"? (una voce con / copre la dir)"""
    pa, _ = _norm(path)
    for a in allowed or ():
        ab, is_dir = _norm(a)
        if not ab:
            continue
        if pa == ab or pa.startswith(ab + "/") or (is_dir and pa.startswith(ab + "/")):
            return True
    return False


def scope_check(root, nid, allowed):
    """Scope del nodo: dichiarato nell'out JSON + scritture fuori card del watchdog."""
    out = read_json(_g(root, "out", nid + ".json"))
    if not isinstance(out, dict):
        return {"name": "scope", "ok": None, "detail": "out JSON mancante: .sjck/out/%s.json" % nid}
    changed = [c for c in (out.get("changed") or []) if isinstance(c, str)]
    bad = [c for c in changed if not covered(c, allowed)]
    state = read_json(_g(root, "state.json")) or {}
    writes = 0
    for n in state.get("nodes", []) or []:
        if isinstance(n, dict) and n.get("id") == nid:
            writes = (n.get("usage") or {}).get("writes_outside_card") or 0
    if bad or writes:
        detail = []
        if bad:
            detail.append("fuori da «Puoi modificare»: " + ", ".join(bad[:10]))
        if writes:
            detail.append("watchdog: %d scritture fuori card" % writes)
        return {"name": "scope", "ok": False, "detail": "; ".join(detail), "files": bad}
    return {"name": "scope", "ok": True, "detail": "%d file, tutti nella card" % len(changed)}


def run_command(root, cmd, timeout):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, shell=True, cwd=root, timeout=timeout,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           universal_newlines=True)
        rc, out = p.returncode, p.stdout or ""
    except subprocess.TimeoutExpired:
        return {"cmd": cmd, "rc": None, "ok": None, "timeout": True,
                "output": "timeout dopo %ss" % timeout, "elapsed_s": round(time.time() - t0, 2)}
    except OSError as e:
        return {"cmd": cmd, "rc": None, "ok": None, "output": "non eseguibile: %s" % e,
                "elapsed_s": round(time.time() - t0, 2)}
    return {"cmd": cmd, "rc": rc, "ok": rc == 0, "output": out[-MAX_OUTPUT:],
            "elapsed_s": round(time.time() - t0, 2)}


def precheck(root, nid, dry_run=False, force_llm=False, timeout=None, conf=None):
    """Livello 1 completo. Ritorna il dict da scrivere in .sjck/out/<ID>.pre.json."""
    conf = conf if isinstance(conf, dict) else config.load_config(root)
    vc = conf.get("validator") or {}
    pl = plan(root, nid, vc.get("commands_allow") or ())
    if pl is None:
        return None
    tmo = timeout or vc.get("timeout_s") or 300
    res = {"id": nid, "source": "precheck", "verdict": "unclear", "llm_validator": True,
           "llm_validator_model": vc.get("model") or "sonnet",
           "llm_validator_effort": vc.get("effort") or "high",
           "checks": [], "llm_criteria": pl["llm_criteria"], "findings": [], "reason": ""}
    checks = [scope_check(root, nid, pl["allowed"])]
    if dry_run:
        for c in pl["commands"]:
            checks.append({"name": "criterio", "cmd": c["cmd"], "ok": None, "dry_run": True,
                           "criterion": c["criterion"]})
    else:
        for c in pl["commands"]:
            r = run_command(root, c["cmd"], tmo)
            r.update({"name": "criterio", "criterion": c["criterion"]})
            checks.append(r)
    res["checks"] = checks
    res["commands"] = len(pl["commands"])
    if dry_run:
        res["reason"] = "dry-run: nessun comando eseguito"
        return res
    failed = [c for c in checks if c.get("ok") is False]
    unknown = [c for c in checks if c.get("ok") is None]
    forced = bool(force_llm) or bool(vc.get("always_llm"))
    if failed:
        # Esito netto: il nodo torna all'implementer senza spendere un LLM.
        res.update({"verdict": "fail", "llm_validator": False,
                    "reason": "controllo deterministico fallito"})
        for c in failed:
            if c["name"] == "scope":
                res["findings"].append("scope: %s" % c.get("detail", ""))
            else:
                tail = " ".join((c.get("output") or "").split())[-400:]
                res["findings"].append("criterio «%s»: `%s` exit %s — %s"
                                       % (c.get("criterion"), c.get("cmd"), c.get("rc"), tail))
        return res
    if forced or unknown or pl["llm_criteria"] or not pl["commands"]:
        why = ("richiesto dalla configurazione o da --force-llm" if forced else
               "controlli senza esito certo: %s" % ", ".join(
                   c.get("name") for c in unknown) if unknown else
               "criteri non eseguibili: %d" % len(pl["llm_criteria"]) if pl["llm_criteria"] else
               "nessun comando nei criteri di accettazione")
        res.update({"verdict": "unclear", "llm_validator": True, "reason": why})
        return res
    res.update({"verdict": "pass", "llm_validator": False,
                "reason": "tutti i criteri sono comandi e passano (%d)" % len(pl["commands"])})
    return res


EXIT = {"pass": 0, "fail": 1, "unclear": 2}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Controlli deterministici prima del validatore LLM")
    ap.add_argument("--id", required=True)
    ap.add_argument("--cwd", default=".")
    ap.add_argument("--dry-run", action="store_true", help="elenca i comandi senza eseguirli")
    ap.add_argument("--force-llm", action="store_true")
    ap.add_argument("--timeout", type=int)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    root = os.path.abspath(args.cwd)
    if not os.path.isdir(_g(root)):
        print("nessun run sjck qui: %s" % _g(root), file=sys.stderr)
        return 3
    res = precheck(root, args.id, args.dry_run, args.force_llm, args.timeout)
    if res is None:
        print("card mancante: .sjck/cards/%s.md" % args.id, file=sys.stderr)
        return 3
    if not args.dry_run:
        write_json(_g(root, "out", args.id + ".pre.json"), res)
    if not args.quiet:
        print(json.dumps(res, indent=1, ensure_ascii=False))
    return 2 if args.dry_run else EXIT.get(res["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
