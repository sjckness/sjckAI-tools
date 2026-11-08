#!/usr/bin/env python3
"""Token reali di un run sjck-graph -> .sjck/tokens.json (v0.4, parte A minima).

Legge i transcript di Claude Code (JSONL) e somma la `usage` dei messaggi
dell'assistente: input, output, cache_read, cache_creation, per modello.

Fonti:
  - transcript della sessione principale (`transcript_path` dell'hook Stop):
    attribuito a ORCH durante un run, a PLAN se lo stato è "planned";
  - transcript dei subagenti (`agent_transcript_path` dell'hook SubagentStop):
    attribuiti al nodo con lo stesso `agent_id` in state.json, oppure all'unico
    nodo running senza agent_id; altrimenti a `unattributed`.
Le fonti già viste restano in .sjck/token-sources.json, così ogni ricalcolo
riparte dai transcript (idempotente) e tokens.json si aggiorna a fine di ogni
nodo e a fine di ogni turno, mai a ogni tool call.

Privacy: legge solo i campi `usage`, `model`, `id` e `timestamp`; non copia
mai testo dei messaggi o contenuto dei file.

Il formato dei transcript non è un contratto stabile: righe malformate o campi
sconosciuti vengono ignorati. Verificato su transcript reali di Claude Code 2.x
contro l'evento `cost-state` (totali scritti da Claude Code stesso):
  - input/cache esatti; output entro ~±6%. Nei transcript dei subagenti la riga
    finale dello streaming spesso manca (resta la usage di message_start): in
    quel caso l'output si ricostruisce dal contenuto, thinking compreso
    (stimato dalla lunghezza della `signature`, perché il testo è oscurato);
  - gli eventi `api-request-blob` sono copie dei messaggi e si saltano;
  - `cost-state` dà il costo reale in USD, ripartito sui nodi.
Le categorie di contesto (card, interfacce, file nella card / fuori card,
output dei tool, messaggi dei subagenti, thinking, reminder, system) sono
STIMATE: il contesto si ricostruisce blocco per blocco, il fattore caratteri→
token si calibra su ogni transcript (regressione sull'input reale dei turni,
tipicamente 2,3-2,5 caratteri per token) e `system` è il resto, che risulta
vicino alla dimensione misurata di system prompt e tool.
Scrive anche .sjck/token-report.json con gli insight (dove si risparmia,
dove si spreca), conservando un eventuale confronto con la baseline.

Uso:
  tokens.py --hook            dall'hook Stop/SubagentStop (JSON su stdin)
  tokens.py [--cwd DIR]       ricalcola dalle fonti registrate
  tokens.py --add PATH LABEL  registra un transcript a mano e ricalcola
Non fallisce mai in modo rumoroso: un errore qui non deve bloccare Claude.
"""
import datetime
import json
import os
import sys
import tempfile

KEYS = ("input", "output", "cache_read", "cache_creation")
USAGE_FIELDS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_input_tokens",
    "cache_creation": "cache_creation_input_tokens",
}


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path, data):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


CATS = ("system", "card", "interfaces", "file_read_in_card", "file_read_outside_card",
        "tool_output", "agent_messages", "thinking", "reminders", "other")
AGENT_TOOLS = ("Task", "Agent")

# Il thinking viene salvato oscurato: resta solo la `signature`, la cui
# lunghezza è proporzionale ai token reali. Calibrato su transcript veri
# (Claude Code 2.x, opus): errore ~20% sul singolo messaggio, ~2% sul totale.
THINK_TOKENS_PER_SIG_CHAR = 0.322

# Eventi di servizio di Claude Code che non sono contesto della conversazione.
# `api-request-blob` contiene COPIE dei messaggi: contarle raddoppierebbe tutto.
SKIP_EVENTS = ("api-request", "api-request-blob", "api-request-shape", "queue-operation",
               "file-history-snapshot", "file-history-delta", "atis-latch", "last-prompt",
               "ai-title", "custom-title")


def _est(v):
    """Stima grezza in token (caratteri / 4) di un contenuto qualsiasi."""
    if isinstance(v, str):
        return len(v) // 4
    if isinstance(v, list):
        return sum(_est(x) for x in v)
    if isinstance(v, dict):
        if "text" in v:
            return _est(v.get("text"))
        if "content" in v:
            return _est(v.get("content"))
        if v.get("type") == "image":
            return 1500
        try:
            return len(json.dumps(v)) // 4
        except Exception:
            return 0
    return 0


def _norm(p):
    p = str(p or "").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def classify(tool, inp, card_files, root=""):
    """Categoria del risultato di un tool, in base al tool e al file letto."""
    if tool in AGENT_TOOLS:
        return "agent_messages"
    if tool in ("Read", "NotebookRead"):
        fp = _norm((inp or {}).get("file_path") or (inp or {}).get("notebook_path"))
        if root:
            r = _norm(root).rstrip("/") + "/"
            if fp.startswith(r):
                fp = fp[len(r):]
        if ".sjck/cards/" in fp:
            return "card"
        if ".sjck/interfaces/" in fp:
            return "interfaces"
        for f in card_files or ():
            f = _norm(f).rstrip("/")
            if f and (fp == f or fp.startswith(f + "/") or fp.endswith("/" + f)):
                return "file_read_in_card"
        return "file_read_outside_card"
    return "tool_output"


DEFAULT_FACTOR = 1.5   # mediana misurata; usata quando i turni sono troppo pochi


def calibrate(pts):
    """Fattore b di input_reale = a + b * stimato (minimi quadrati), limitato a [1, 2.5].

    Con meno di 4 turni, o una regressione degenere, usa DEFAULT_FACTOR.
    """
    n = len(pts)
    if n < 4:
        return DEFAULT_FACTOR
    mx = sum(x for x, _ in pts) / n
    my = sum(y for _, y in pts) / n
    sxx = sum((x - mx) ** 2 for x, _ in pts)
    if sxx <= 0:
        return DEFAULT_FACTOR
    b = sum((x - mx) * (y - my) for x, y in pts) / sxx
    if my - b * mx < 0:   # intercetta negativa: il fit non è credibile
        return DEFAULT_FACTOR
    return min(2.5, max(1.0, b))


def parse_transcript(path, card_files=(), root=""):
    """Somma la usage dei messaggi assistant di un transcript e la divide per categoria.

    In streaming lo stesso messaggio compare su più righe con lo stesso
    `message.id`: vale l'ultima riga, così niente doppi conteggi.

    Categorie (stimate): il contesto viene ricostruito blocco per blocco
    (caratteri/4) e l'input reale di ogni turno (input + cache) viene diviso
    in proporzione a ciò che c'era nel contesto in quel momento; la parte non
    spiegata dai blocchi visibili va a `system` (prompt di sistema, agenti,
    CLAUDE.md, definizioni dei tool). Una compattazione azzera il contesto.
    Ritorna anche `heavy`: i 5 risultati di tool più grandi (tool, categoria,
    file, token stimati), senza contenuto.
    """
    by_msg = {}
    order = []
    snap = {}          # message id -> contesto stimato prima della risposta
    ctx = {c: 0 for c in CATS}
    tools = {}         # tool_use id -> (nome, input)
    heavy = []
    seen_blocks = {}   # message id -> blocchi già contati (lo streaming ripete le righe)
    vis = {}           # message id -> output visibile stimato (testo, tool_use, thinking)
    cost_state = None
    first = last = None
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with f:
        for n, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except ValueError:
                continue
            if not isinstance(evt, dict):
                continue
            etype = evt.get("type")
            if etype == "cost-state":
                cost_state = evt  # l'ultimo vince: totali della sessione, subagenti inclusi
                continue
            if etype in SKIP_EVENTS:
                continue
            if etype == "attachment":
                # system-reminder e simili: entrano nel contesto come testo renderizzato.
                ctx["reminders"] += _est([r for r in (evt.get("rendered") or []) if isinstance(r, dict)])
                continue
            if evt.get("isCompactSummary") or (etype == "system" and evt.get("subtype") == "compact_boundary"):
                ctx = {c: 0 for c in CATS}
            msg = evt.get("message")
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            if role == "user" or evt.get("type") == "user":
                if isinstance(content, str):
                    ctx["other"] += _est(content)
                elif isinstance(content, list):
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get("type") == "tool_result":
                            name, tin = tools.get(b.get("tool_use_id"), ("?", {}))
                            cat = classify(name, tin, card_files, root)
                            size = _est(b.get("content"))
                            ctx[cat] += size
                            fp = (tin or {}).get("file_path") or ""
                            heavy.append((size, name, cat, _norm(fp)[-120:]))
                        else:
                            ctx["other"] += _est(b)
                continue
            if role not in (None, "assistant") or evt.get("type") not in (None, "assistant"):
                continue
            usage = msg.get("usage")
            mid = msg.get("id") or evt.get("requestId") or "line-%d" % n
            if isinstance(usage, dict):
                if mid not in by_msg:
                    order.append(mid)
                    snap[mid] = dict(ctx)
                by_msg[mid] = {
                    "model": msg.get("model") if isinstance(msg.get("model"), str) else "unknown",
                    # Senza stop_reason la riga è un pezzo dello streaming: la sua
                    # usage è quella di message_start (output quasi zero).
                    "final": bool(msg.get("stop_reason")),
                    **{k: _int(usage.get(USAGE_FIELDS[k])) for k in KEYS},
                }
            # La risposta resta nel contesto dei turni successivi. Ogni blocco
            # si conta una volta sola anche se la riga viene ripetuta.
            if isinstance(content, list):
                done = seen_blocks.setdefault(mid, set())
                for i, b in enumerate(content):
                    if not isinstance(b, dict):
                        continue
                    key = b.get("id") or "%s:%d:%d" % (b.get("type"), i, len(json.dumps(b, default=str)))
                    if key in done:
                        continue
                    done.add(key)
                    t = b.get("type")
                    if t == "tool_use":
                        tools[b.get("id")] = (b.get("name") or "?", b.get("input") if isinstance(b.get("input"), dict) else {})
                        size = _est(b.get("input"))
                        ctx["other"] += size
                    elif t == "text":
                        size = _est(b.get("text"))
                        ctx["other"] += size
                    elif t in ("thinking", "redacted_thinking"):
                        sig = b.get("signature") or b.get("data") or ""
                        size = _est(b.get("thinking")) + int(len(sig) * THINK_TOKENS_PER_SIG_CHAR)
                        ctx["thinking"] += size
                    else:
                        continue
                    vis[mid] = vis.get(mid, 0) + size
            ts = evt.get("timestamp")
            if isinstance(ts, str):
                first = first or ts
                last = ts
    out = {k: 0 for k in KEYS}
    cats = {c: 0.0 for c in CATS}
    models = {}
    out_est = 0
    # caratteri/4 sottostima i token di codice e output di shell (fattore 1,4-1,8
    # misurato su transcript reali). Ogni turno ha l'input reale, quindi il
    # fattore si calibra sul transcript stesso: input = a + b * stimato, dove a
    # è la parte fissa (system prompt e tool) e b il fattore del tokenizer.
    pts = []
    for mid in order:
        u = by_msg[mid]
        if u["model"] == "<synthetic>":
            continue
        s = snap.get(mid) or {}
        # Il thinking è già in token reali (dalla signature): fuori dal fit.
        x = sum(s.get(c, 0) for c in CATS if c not in ("system", "thinking"))
        y = u["input"] + u["cache_read"] + u["cache_creation"] - s.get("thinking", 0)
        if x > 0 and y > 0:
            pts.append((x, y))
    factor = calibrate(pts)
    for mid in order:
        u = by_msg[mid]
        if u["model"] == "<synthetic>":
            continue
        if not u["final"] and vis.get(mid, 0) > u["output"]:
            # Riga finale mai scritta (succede nei transcript dei subagenti):
            # l'output si ricostruisce da ciò che il messaggio contiene.
            out_est += vis[mid] - u["output"]
            u["output"] = vis[mid]
        for k in KEYS:
            out[k] += u[k]
        m = models.setdefault(u["model"], {k: 0 for k in KEYS})
        for k in KEYS:
            m[k] += u[k]
        real_in = u["input"] + u["cache_read"] + u["cache_creation"]
        seen = {c: v * (1 if c == "thinking" else factor) for c, v in (snap.get(mid) or {}).items()}
        est = sum(seen.get(c, 0) for c in CATS if c != "system")
        if real_in <= 0:
            continue
        scale = min(1.0, real_in / est) if est else 0.0
        for c in CATS:
            if c != "system":
                cats[c] += seen.get(c, 0) * scale
        cats["system"] += real_in - est * scale
    for m in models.values():
        m["total"] = sum(m[k] for k in KEYS)
    out["total"] = sum(out[k] for k in KEYS)
    out["turns"] = len(order)
    out["models"] = models
    out["categories"] = {c: int(round(v)) for c, v in cats.items() if round(v)}
    heavy.sort(key=lambda h: -h[0])
    out["heavy"] = [{"tokens": h[0], "tool": h[1], "category": h[2], "file": h[3]} for h in heavy[:5] if h[0]]
    out["output_estimated"] = out_est
    out["chars_per_token"] = round(4 / factor, 2)
    out["cost_state"] = _cost_state(cost_state)
    out["first"] = first
    out["last"] = last
    return out


def _cost_state(evt):
    """Costo reale scritto da Claude Code (evento `cost-state`): USD per modello."""
    if not isinstance(evt, dict):
        return None
    mu = evt.get("modelUsage")
    models = {}
    if isinstance(mu, dict):
        for name, m in mu.items():
            if isinstance(m, dict) and isinstance(m.get("costUSD"), (int, float)):
                models[name] = float(m["costUSD"])
    total = evt.get("totalCostUSD")
    if not isinstance(total, (int, float)):
        total = sum(models.values()) if models else None
    if total is None:
        return None
    return {"usd": float(total), "by_model": models, "session": evt.get("sessionId"),
            "unknown_model_cost": bool(evt.get("hasUnknownModelCost"))}


ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"


def _fx_cache_path():
    return os.path.join(os.path.expanduser("~"), ".sjck", "fx.json")


def eur_per_usd(fetch=True):
    """Tasso USD->EUR: {"rate", "date", "source"} oppure None.

    Ordine: SJCK_EUR_PER_USD (manuale) > cache di oggi > tasso di riferimento
    BCE (una richiesta al giorno, timeout 3 s, nessun dato inviato) > ultima
    cache, anche vecchia. Mai un errore: senza tasso il costo resta in USD.
    """
    env = os.environ.get("SJCK_EUR_PER_USD")
    if env:
        try:
            return {"rate": float(env), "date": None, "source": "SJCK_EUR_PER_USD"}
        except ValueError:
            pass
    cp = _fx_cache_path()
    cached = read_json(cp)
    today = datetime.date.today().isoformat()
    if isinstance(cached, dict) and cached.get("checked") == today and cached.get("rate"):
        return cached
    now = datetime.datetime.now().timestamp()
    recently_failed = isinstance(cached, dict) and now - (cached.get("failed_at") or 0) < 3600
    if fetch and not recently_failed and not os.environ.get("SJCK_FX_OFFLINE"):
        try:
            import re
            import urllib.request
            with urllib.request.urlopen(ECB_URL, timeout=3) as r:
                xml = r.read(20000).decode("utf-8", "replace")
            usd = re.search(r"currency=['\"]USD['\"]\s+rate=['\"]([0-9.]+)", xml)
            day = re.search(r"time=['\"](\d{4}-\d{2}-\d{2})", xml)
            if usd and float(usd.group(1)) > 0:
                fx = {"rate": round(1 / float(usd.group(1)), 6), "date": day.group(1) if day else None,
                      "source": "ECB", "checked": today}
                try:
                    os.makedirs(os.path.dirname(cp), exist_ok=True)
                    write_json(cp, fx)
                except OSError:
                    pass
                return fx
        except Exception:
            pass
        # Fallito: niente nuovi tentativi per un'ora (ogni hook pagherebbe il timeout).
        try:
            os.makedirs(os.path.dirname(cp), exist_ok=True)
            write_json(cp, dict(cached if isinstance(cached, dict) else {}, failed_at=int(now)))
        except OSError:
            pass
    if isinstance(cached, dict) and cached.get("rate"):
        return cached  # vecchio ma meglio di niente: la data lo dice
    return None


def prices_default_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "prices.json")


def _merge_prices(base, over):
    """Merge per chiave a due livelli (multipliers, models.<m>): l'override vince."""
    out = {"multipliers": dict(base.get("multipliers") or {}),
           "models": {m: dict(v) for m, v in (base.get("models") or {}).items() if isinstance(v, dict)}}
    if isinstance(over, dict):
        if isinstance(over.get("multipliers"), dict):
            out["multipliers"].update(over["multipliers"])
        for m, v in (over.get("models") or {}).items():
            if isinstance(v, dict):
                out["models"].setdefault(m, {}).update(v)
    return out


# Default interno (specchio di config/prices.json): se il file versionato manca
# l'installazione degrada, non azzera i costi in silenzio.
BUILTIN_PRICES = {
    "multipliers": {"input": 1.0, "output": 5.0, "cache_read": 0.1, "cache_creation": 1.25},
    "models": {"default": {"input_per_mtok": 3.0}, "opus": {"input_per_mtok": 5.0},
               "sonnet": {"input_per_mtok": 3.0}, "haiku": {"input_per_mtok": 1.0}},
}


def load_prices(root=None):
    """Prezzi: default versionati (config/prices.json) + override <root>/.sjck/prices.json."""
    base = read_json(prices_default_path(), {})
    if not isinstance(base, dict) or not base.get("models"):
        base = BUILTIN_PRICES
    over = read_json(os.path.join(root, ".sjck", "prices.json"), {}) if root else {}
    return _merge_prices(base if isinstance(base, dict) else {}, over)


def _mult(prices):
    m = prices.get("multipliers") or {}
    return {k: float(m[k]) if isinstance(m.get(k), (int, float)) else 1.0 for k in KEYS}


def model_price(prices, model):
    """Voce prezzi del modello: chiave esatta, poi la chiave piu' lunga contenuta nel nome, poi 'default'."""
    models = prices.get("models") or {}
    name = (model or "").lower()
    if model in models:
        return models[model]
    hits = [k for k in models if k != "default" and k.lower() in name]
    if hits:
        return models[max(hits, key=len)]
    return models.get("default")


def estimate_usd(prices, model, usage):
    """USD stimati da token gia' aggregati; None se il modello non ha prezzo. Nessun I/O."""
    mp = model_price(prices, model)
    if not isinstance(mp, dict) or not isinstance(mp.get("input_per_mtok"), (int, float)):
        return None
    mult = _mult(prices)
    mult.update({k: float(mp["multipliers"][k]) for k in KEYS
                 if isinstance(mp.get("multipliers"), dict) and isinstance(mp["multipliers"].get(k), (int, float))})
    per_tok = float(mp["input_per_mtok"]) / 1e6
    return sum(_int(usage.get(k)) * mult[k] * per_tok for k in KEYS)


def _weight(e, mult=None):
    mult = mult or {k: 1.0 for k in KEYS}
    return sum(e.get(k, 0) * w for k, w in mult.items())


def _mtotal(v):
    """Totale di una voce `models`: forma dict {.., total} oppure intero (vecchio tokens.json)."""
    if isinstance(v, dict):
        return _int(v.get("total"))
    return _int(v)


def node_for_agent(state, agent_id):
    """Nodo di un subagente: stesso agent_id, oppure l'unico running senza agent_id."""
    nodes = [n for n in (state or {}).get("nodes", []) if isinstance(n, dict)]
    if agent_id:
        for n in nodes:
            if n.get("agent_id") == agent_id:
                return n.get("id")
    free = [n for n in nodes if n.get("status") == "running" and not n.get("agent_id")]
    if len(free) == 1:
        return free[0].get("id")
    return "unattributed"


def sources_path(root):
    return os.path.join(root, ".sjck", "token-sources.json")


def add_source(root, path, label, kind):
    """Registra un transcript. La prima etichetta vince (un subagente non cambia nodo)."""
    sp = sources_path(root)
    src = read_json(sp, {})
    if not isinstance(src, dict):
        src = {}
    if path not in src:
        src[path] = {"label": label, "kind": kind}
        write_json(sp, src)
    return src


def _costs(prices, sessions, by_node, by_agent, by_model):
    """Costo USD per agente, nodo e run, scritto in place. Solo aritmetica sui token gia' aggregati.

    Con cost-state il totale e' reale e viene ripartito per peso di prezzo (estimated=False);
    altrimenti si stima dai prezzi (estimated=True). Mai rete: l'EUR e' a carico di build().
    """
    if sessions:
        usd = sum(s["usd"] for s in sessions.values())
        mult = _mult(prices)
        wsum = sum(_weight(e, mult) for e in by_node.values()) or 1.0
        for grp in (by_node, by_agent):
            for e in grp.values():
                e["cost_usd"] = round(usd * _weight(e, mult) / wsum, 4)
                e["estimated"] = False
        bym = {}
        for s in sessions.values():
            for m, v in s["by_model"].items():
                bym[m] = round(bym.get(m, 0.0) + v, 4)
        return {"usd": round(usd, 4), "by_model": bym, "source": "cost-state", "estimated": False,
                "split": "per-node shares weighted by token price ratios",
                "complete": not any(s.get("unknown_model_cost") for s in sessions.values())}
    complete = True

    def est(models):
        nonlocal complete
        tot = 0.0
        for name, m in models.items():
            c = estimate_usd(prices, name, m)
            if c is None:
                complete = False
            else:
                tot += c
        return tot
    for grp in (by_node, by_agent):
        for e in grp.values():
            e["cost_usd"] = round(est(e["models"]), 4)
            e["estimated"] = True
    bym = {}
    for name, m in by_model.items():
        c = estimate_usd(prices, name, m)
        if c is not None:
            bym[name] = round(c, 4)
    return {"usd": round(sum(e["cost_usd"] for e in by_node.values()), 4), "by_model": bym,
            "source": "prices", "estimated": True, "split": "per-model token usage x configured prices",
            "complete": complete}


def build(root):
    """Ricalcola tokens.json dalle fonti registrate."""
    src = read_json(sources_path(root), {}) or {}
    state = read_json(os.path.join(root, ".sjck", "state.json"), {}) or {}
    files_of = {n.get("id"): n.get("files") or [] for n in state.get("nodes", []) if isinstance(n, dict)}
    by_node = {}
    by_model = {}
    heavy = []
    totals = {k: 0 for k in KEYS}
    out_est = 0
    sessions = {}      # sessionId -> cost-state (dal transcript principale)
    by_agent = {}      # un transcript = un agente (o la sessione principale)
    prices = load_prices(root)
    for path, meta in src.items():
        if not isinstance(meta, dict):
            continue
        label = meta.get("label") or "unattributed"
        r = parse_transcript(path, files_of.get(label, ()), root)
        if not r or not r["turns"]:
            continue
        if r.get("cost_state"):
            sessions[r["cost_state"].get("session") or path] = r["cost_state"]
        out_est += r.get("output_estimated", 0)
        e = by_node.setdefault(label, {k: 0 for k in KEYS})
        e.setdefault("turns", 0)
        e.setdefault("agents", 0)
        e.setdefault("models", {})
        e.setdefault("categories", {})
        for k in KEYS:
            e[k] += r[k]
            totals[k] += r[k]
        e["turns"] += r["turns"]
        if meta.get("kind") == "agent":
            e["agents"] += 1
        for c, v in r["categories"].items():
            e["categories"][c] = e["categories"].get(c, 0) + v
        for h in r["heavy"]:
            heavy.append(dict(h, node=label))
        ag_id = os.path.splitext(os.path.basename(path))[0] or path
        if ag_id in by_agent:
            ag_id = path
        ag = by_agent[ag_id] = {"node": label, "kind": meta.get("kind") or "", "models": {}}
        ag.update({k: r[k] for k in KEYS})
        ag["total"] = sum(r[k] for k in KEYS)
        for name, m in r["models"].items():
            em = e["models"].setdefault(name, {k: 0 for k in KEYS})
            ag["models"][name] = {k: m[k] for k in KEYS}
            ag["models"][name]["total"] = sum(m[k] for k in KEYS)
            bm = by_model.setdefault(name, {k: 0 for k in KEYS})
            for k in KEYS:
                em[k] += m[k]
                bm[k] += m[k]
    for e in by_node.values():
        e["total"] = sum(e[k] for k in KEYS)
        e["types"] = {k: e[k] for k in KEYS}
        for m in e["models"].values():
            m["total"] = sum(m[k] for k in KEYS)
    for m in by_model.values():
        m["total"] = sum(m[k] for k in KEYS)
    totals["total"] = sum(totals[k] for k in KEYS)
    totals["output_estimated"] = out_est
    prev = read_json(os.path.join(root, ".sjck", "tokens.json"), {}) or {}
    heavy.sort(key=lambda h: -h["tokens"])
    cost = _costs(prices, sessions, by_node, by_agent, by_model)
    if cost.get("source") == "cost-state":
        fx = eur_per_usd()
        if fx:
            cost["eur"] = round(cost["usd"] * fx["rate"], 4)
            cost["fx"] = {"eur_per_usd": fx["rate"], "date": fx.get("date"), "source": fx.get("source")}
            for e in by_node.values():
                e["cost_eur"] = round(e["cost_usd"] * fx["rate"], 4)
    return {
        "source": "transcripts",
        "categories_estimated": True,
        "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totals": totals,
        "cost": cost,
        "by_node": by_node,
        "by_agent": by_agent,
        "by_model": by_model,
        "heavy": heavy[:5],
    }


def _k(n):
    return "%dk" % round(n / 1000) if n >= 1000 else str(int(n))


def analyze(tokens_data, state):
    """Dove si risparmia e dove si spreca: lista di insight per il Run Viewer.

    Ogni insight: {kind, node, tokens, saving_estimate, title, suggestion}.
    saving_estimate > 0 = token che si potevano risparmiare; < 0 = risparmio
    già ottenuto (mostrato in verde).
    """
    nodes = {n.get("id"): n for n in (state or {}).get("nodes", []) if isinstance(n, dict)}
    bn = tokens_data.get("by_node") or {}
    out = []
    for nid, e in bn.items():
        n = nodes.get(nid) or {}
        cats = e.get("categories") or {}
        inp = e.get("input", 0) + e.get("cache_read", 0) + e.get("cache_creation", 0)
        if not inp:
            continue
        # Card povere: il nodo esplora file che non erano nella card.
        outside = cats.get("file_read_outside_card", 0)
        if nid not in ("ORCH", "PLAN", "unattributed") and outside > 0.2 * inp and outside > 5000:
            out.append({"kind": "card", "node": nid, "tokens": outside, "saving_estimate": int(outside * 0.7),
                        "title": "%s reads files outside its card (%s, %d%% of its input)" % (nid, _k(outside), round(outside / inp * 100)),
                        "suggestion": "Add the files it needed to the card's files list or extract an interface: the next run skips the exploration."})
        # Cache: un agente che non riusa la cache paga tutto il contesto ogni turno.
        hit = e.get("cache_read", 0) / inp
        if e.get("turns", 0) >= 4 and hit < 0.5:
            out.append({"kind": "cache", "node": nid, "tokens": inp, "saving_estimate": int(inp * (0.5 - hit) * 0.9),
                        "title": "%s cache hit only %d%%" % (nid, round(hit * 100)),
                        "suggestion": "Context changes at the top each turn (e.g. edited files re-read early): keep the card and stable instructions first."})
        # Thinking: resta nel contesto e viene riletto a ogni turno successivo.
        think = cats.get("thinking", 0)
        if think > 0.25 * inp and think > 20000:
            out.append({"kind": "thinking", "node": nid, "tokens": think, "saving_estimate": int(think * 0.5),
                        "title": "%s: past thinking is %d%% of its input (%s re-read every turn)" % (nid, round(think / inp * 100), _k(think)),
                        "suggestion": "Thinking stays in context: lower the effort for this node, or split it so each agent starts with a short context."})
        # Spreco: nodi falliti o con tentativi ripetuti.
        att = n.get("attempts") or 0
        if n.get("status") in ("failed", "blocked") or att:
            share = e.get("total", 0) if n.get("status") in ("failed", "blocked") else int(e.get("total", 0) * att / (att + 1))
            if share:
                out.append({"kind": "waste", "node": nid, "tokens": share, "saving_estimate": share,
                            "title": "%s: %s spent on %s" % (nid, _k(share), "a failed node" if n.get("status") in ("failed", "blocked") else "%d retried attempt(s)" % att),
                            "suggestion": "Check the validator feedback: a sharper acceptance criterion in the card usually removes the retry."})
        # Modello: opus su un nodo piccolo approvato al primo colpo.
        big = sum(_mtotal(v) for m, v in (e.get("models") or {}).items() if "opus" in m)
        if big and n.get("status") == "validated" and not att and len(n.get("files") or []) <= 2:
            out.append({"kind": "model", "node": nid, "tokens": big, "saving_estimate": int(big * 0.4),
                        "title": "%s used opus on a small node that passed first time" % nid,
                        "suggestion": "Next time plan it with sonnet/medium; keep opus for nodes many others depend on."})
    # Il guadagno del contratto: l'orchestratore riceve JSON, non i file.
    orch = bn.get("ORCH") or {}
    sub_reads = sum((e.get("categories") or {}).get("file_read_in_card", 0) for k2, e in bn.items() if k2 not in ("ORCH", "PLAN"))
    msgs = (orch.get("categories") or {}).get("agent_messages", 0)
    if sub_reads and msgs < sub_reads:
        out.append({"kind": "contract", "node": "ORCH", "tokens": msgs, "saving_estimate": -(sub_reads - msgs), "good": True,
                    "title": "Orchestrator context kept small: agent reports %s vs %s of files read by the nodes" % (_k(msgs), _k(sub_reads)),
                    "suggestion": "This is what the node contract saves compared to one agent reading everything."})
    for h in tokens_data.get("heavy") or []:
        if h.get("tokens", 0) >= 8000:
            out.append({"kind": "heavy", "node": h.get("node"), "tokens": h["tokens"], "saving_estimate": int(h["tokens"] * 0.5),
                        "title": "Largest tool output: %s %s (%s, ~%s)" % (h.get("tool"), h.get("file") or "", h.get("category"), _k(h["tokens"])),
                        "suggestion": "Read a range (offset/limit) or grep first instead of the whole output."})
    out.sort(key=lambda i: -abs(i.get("saving_estimate") or 0))
    cost = tokens_data.get("cost") or {}
    cbn = {nid: {"usd": e.get("cost_usd", 0.0), "estimated": bool(e.get("estimated", cost.get("estimated", False)))}
           for nid, e in bn.items() if "cost_usd" in e}
    cba = {aid: {"usd": e.get("cost_usd", 0.0), "node": e.get("node"), "estimated": bool(e.get("estimated", False))}
           for aid, e in (tokens_data.get("by_agent") or {}).items() if "cost_usd" in e}
    rep = {"insights": out[:8], "estimated": True}
    if cost:
        rep["cost"] = {"usd": cost.get("usd", 0.0), "estimated": bool(cost.get("estimated", False)),
                       "by_node": cbn, "by_agent": cba}
    return rep


def refresh(root):
    data = build(root)
    write_json(os.path.join(root, ".sjck", "tokens.json"), data)
    rp = os.path.join(root, ".sjck", "token-report.json")
    prev = read_json(rp, {}) or {}
    report = analyze(data, read_json(os.path.join(root, ".sjck", "state.json"), {}) or {})
    if isinstance(prev, dict) and prev.get("compare"):
        report["compare"] = prev["compare"]  # confronto con la baseline (evals), se esiste
    write_json(rp, report)
    # Il Run Viewer statico si rigenera solo se esiste già (/sjck-view).
    if os.path.exists(os.path.join(root, ".sjck", "view.html")):
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import graph_view
            graph_view.render(root)
        except Exception:
            pass
    return data


def from_hook(inp):
    root = inp.get("cwd") or os.getcwd()
    state = read_json(os.path.join(root, ".sjck", "state.json"))
    if not isinstance(state, dict):
        return None  # nessun run sjck qui: niente da fare
    event = inp.get("hook_event_name") or ""
    if event == "SubagentStop" or inp.get("agent_transcript_path"):
        path = inp.get("agent_transcript_path")
        if not path:
            return None
        add_source(root, path, node_for_agent(state, inp.get("agent_id")), "agent")
    else:
        path = inp.get("transcript_path")
        if not path:
            return None
        add_source(root, path, "PLAN" if state.get("status") == "planned" else "ORCH", "main")
    return refresh(root)


def main(argv):
    try:
        if "--hook" in argv:
            raw = sys.stdin.read()
            from_hook(json.loads(raw) if raw.strip() else {})
            return 0
        root = os.getcwd()
        if "--cwd" in argv:
            root = argv[argv.index("--cwd") + 1]
        if "--add" in argv:
            i = argv.index("--add")
            add_source(root, os.path.abspath(argv[i + 1]), argv[i + 2], "manual")
        data = refresh(root)
        t = data["totals"]
        print("tokens: %d total (input %d, output %d, cache read %d, cache write %d), %d nodes"
              % (t["total"], t["input"], t["output"], t["cache_read"], t["cache_creation"], len(data["by_node"])))
        c = data.get("cost")
        if isinstance(c, dict) and c.get("eur") is not None:
            print("cost: EUR %.2f (USD %.2f, 1 USD = %s EUR, %s %s)" % (c["eur"], c["usd"], c["fx"]["eur_per_usd"],
                  c["fx"].get("source") or "", c["fx"].get("date") or ""))
        elif isinstance(c, dict):
            print("cost: USD %.2f (no EUR rate)" % c["usd"])
        return 0
    except Exception as e:  # mai bloccare Claude
        if "--hook" not in argv:
            print("tokens: %s" % e, file=sys.stderr)
            return 1
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
