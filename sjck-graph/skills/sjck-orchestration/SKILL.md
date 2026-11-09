---
name: sjck-orchestration
description: Usa questa skill per task di sviluppo non banali che toccano più file, più package o richiedono più step (feature nuove, refactor, migrazioni, integrazione di componenti), oppure quando l'utente chiede di lavorare "a grafo", "con gli agenti", "in parallelo" o nomina planner/validator. Sceglie da sola tra lavoro inline, catena breve o DAG parallelo, valida ogni step e tiene lo stato in .sjck/state.json. Non usarla per domande, spiegazioni o modifiche di poche righe.
---
# Orchestrazione a grafo

Sei l'ORCHESTRATORE. Il tuo contesto è la risorsa più preziosa: non leggere
codice oltre il minimo per il triage; leggi solo .sjck/state.json e
.sjck/out/*.json.

## Override dell'utente (hanno sempre la precedenza)
L'utente può indicare nel prompt, in qualsiasi forma:
- la modalità: "modalità S/M/L", "--mode M", "fallo da solo", "usa il DAG";
- gli agenti: "usa solo scout e validator", "niente planner", "senza validator";
- il parallelismo: "max 2 agenti in parallelo".
Rispettali alla lettera. Se un override è chiaramente inefficiente
(es. DAG per una modifica di 2 righe), eseguilo comunque ma segnalalo in UNA
riga in `mode_reason`. Unica eccezione: senza validator un nodo non diventa
`validated` ma `done-unverified`, e lo dici nel riepilogo finale.

## Step 0 — Setup e ripresa
- Se .sjck/ non esiste, crea .sjck/{cards,out,interfaces,archive}/ e
  aggiungi `.sjck/` al .gitignore del repo, se manca.
- Script (plan_score, findings, watchdog): una volta sola, `<script>` = la prima
  cartella che contiene `plan_score.py` (`test -f <cartella>/plan_score.py`), resa assoluta, tra:
  `${CLAUDE_PLUGIN_ROOT}/scripts` (se espanso o non vuota in Bash); `<base dir della skill>/../../scripts`;
  `~/.claude/sjck-scripts`; `.claude/sjck-scripts`. Scrivi nel log `HH:MM script: <abs>`.
  Nessuna trovata → fermati e dillo all'utente. Metti la riga `script: <abs>` nel prompt di
  OGNI agente (dettagli: reference/scripts.md).
- Sessione non interattiva (`claude -p`, o AskUserQuestion non disponibile): niente domande,
  segui le regole di reference/findings.md e reference/critic.md; ogni altro
  "chiedi all'utente" diventa run `failed` con il motivo nel log.
- Se esiste .sjck/state.json con `status: running`, NON ripianificare:
  riprendi dal primo nodo non `validated` (Step 3).
- Se esiste con `status: planned` (preparato da `sjck-planning`), NON rifare
  triage e piano: controlla solo che le card esistano, che i nodi paralleli
  abbiano file disgiunti e che non ci siano cicli; poi imposta
  `status: running` e vai allo Step 3. Rispetta `model`, `effort` e `budget`
  di ogni nodo. Se il task dell'utente è diverso dal `goal` del piano, chiedi
  quale eseguire.
- Se esiste con `status: done|failed`, sposta state.json, cards/, out/,
  findings.jsonl, watchdog.jsonl e watchdog_state.json in
  .sjck/archive/<YYYYMMDD-HHMM>/ e riparti. `backlog.md` resta.
  `interfaces/` NON si archivia: è la cache tra run (hash in `<nome>.json`).
- Leggi CLAUDE.md e .claude/map/ (se esistono) SOLO per scegliere i file
  rilevanti: non copiarli nelle card, cita i percorsi.

## Step 1 — Triage
Stima con al massimo 3 chiamate Grep/Glob, senza leggere file interi.

| Modalità | Quando | Come |
|---|---|---|
| S — inline | ≤3 file, un solo concern, nessuna incognita | Fai tu la task. Poi UN `sjck-validator` (salta solo per typo, rename, config di 1 riga). |
| M — catena | 2-4 step sequenziali, o serve esplorare prima | Card scritte da te: scout → implementer → validator. Niente planner. |
| L — DAG | ≥2 sottoparti indipendenti, >5 file o più package | planner → DAG → nodi paralleli, validator dopo OGNI nodo. |

Se la task è grande e vaga (obiettivo poco chiaro, nessun modo evidente di
verificarla), proponi in una riga di passare prima da `/sjck-plan`.

Nel dubbio scegli la modalità PIÙ PICCOLA. Puoi salire (S→M→L) se emergono
incognite, registrandolo nel log; non scendere mai durante un run.

## Step 2 — Piano
Scrivi .sjck/state.json (JSON valido, 2 spazi di indentazione):

```json
{
  "goal": "",
  "mode": "S|M|L",
  "mode_reason": "1 riga",
  "status": "running",
  "started": "ISO-8601",
  "nodes": [
    {"id": "T01", "title": "", "agent": "self|scout|implementer",
     "deps": [], "files": [], "status": "pending", "attempts": 0, "agent_id": "",
     "model": "inherit", "effort": "medium",
     "budget": {"tool_calls": 40, "context_tokens": 2000}}
  ],
  "log": ["HH:MM T01 pending → running"],
  "metrics": {"subagents": 0, "validator_fails": 0}
}
```
`model`, `effort`, `budget` sono opzionali (default sopra). Campi che scrivi tu
nel corso del run (`plan_score`, `sjck-critic`, `checkpoints`, metriche nuove, `usage`,
`assumptions`): reference/scripts.md.
Stati nodo: pending → running → done → validated (oppure blocked, failed,
done-unverified).

Ogni card in .sjck/cards/<ID>.md:
```markdown
# <ID> — <titolo>
## Obiettivo
## Puoi modificare
## Leggi
## Criteri di accettazione   (comando + esito atteso, o condizione sul diff)
## Fuori scope              (cosa il nodo NON deve sistemare: lo annota nei findings)
## Correzioni richieste      (vuota; la compili coi findings del validator)
```

- S: un nodo T01 (agent: self).
- M: scrivi tu le card.
- L: lancia `sjck-planner` passandogli i due schemi qui sopra, poi controlla:
  nodi paralleli con file disgiunti? criteri verificabili? niente cicli?

### Plan score e critico del piano
Dopo il piano (L; anche M quando scrivi tu le card) esegui
`python3 "<script>/plan_score.py" --cwd "$PWD"`; poi rileggi state.json prima di
modificarlo (lo script vi scrive `plan_score`). Rilancialo dopo ogni nodo aggiunto a run avviato.
- Exit 0 (`ok`): in L, passa il piano al critico, punto `plan` (reference/critic.md).
- Exit 1 (`reject`): rimanda al planner con i `reasons` (max 2 volte), poi chiedi
  all'utente. MAI avviare il loop con `verdict: reject`.
- Exit 2 (stato illeggibile o script mancante): fermati, non avviare il loop,
  ricontrolla lo Step 0.

## Step 3 — Loop di esecuzione
Ripeti finché tutti i nodi sono `validated`/`done-unverified`, oppure uno è `failed`,
oppure c'è stallo (nessun nodo running né pronto → chiedi all'utente):
1. Pronti = `pending` con TUTTE le deps `validated` (`done` non basta).
2. Nodi `scout`: prima `python3 "<script>"/context.py interfaces skip --cwd "$PWD"`;
   un ID in `reusable` diventa `validated` senza lancio (log `HH:MM <ID> skip:
   interfacce fresche`). Gli altri: segnali `running` in state.json, POI lanciali
   tutti insieme in background (`isolation: worktree` se più di uno scrive file).
   Il prompt lo costruisce `python3 "<script>"/context.py prompt --id <ID> --role
   <ruolo> --script "<script>" --cwd "$PWD"` (parte stabile in testa, card ridotta
   al ruolo); `model` ed `effort` del nodo vanno come override al lancio
   (reference/scripts.md). Subito dopo il lancio scrivi in `nodes[].agent_id`
   l'id restituito dal tool di lancio.
3. A completamento leggi solo .sjck/out/<ID>.json → `done`. Copia
   `assumptions` nel nodo; esegui `python3 "<script>"/watchdog.py usage --cwd "$PWD"`
   (scrive `usage` dei nodi e le somme in metrics) e RILEGGI state.json prima di
   modificarlo. Per ogni voce di `findings` di `.sjck/out/<ID>.json` e di `PLAN.json`
   esegui `findings.py add --from <ID>`; i `findings` di `.val.json` e `REVIEW.json`
   sono correzioni, non si registrano. Per ogni nome in `new_interfaces`:
   `context.py interfaces record --name <nome> --from-card <ID> --cwd "$PWD"`
   (è l'hash che permette di saltare quel nodo al prossimo run).
4. Validazione a due livelli: prima i controlli deterministici con
   `python3 "<script>"/precheck.py --id <ID> --cwd "$PWD"` (scrive
   .sjck/out/<ID>.pre.json; dettagli in reference/scripts.md):
   - exit 0 (`pass`) → `validated`, senza validatore LLM
   - exit 1 (`fail`) → usa i suoi `findings` come quelli del validatore, sotto
   - exit 2 (`unclear`) → lancia `sjck-validator` sull'ID, con `model` ed `effort`
     dai campi `llm_validator_model`/`llm_validator_effort` del pre.json
     → .sjck/out/<ID>.val.json
   - exit 3 → card o run illeggibili: fermati e ricontrolla lo Step 2
   Poi, col verdetto (pre.json o .val.json):
   - `pass` → `validated`
   - `fail`, `attempts < 2` → findings nella card sotto "Correzioni richieste",
     attempts += 1, riprendi lo STESSO implementer con SendMessage → `running`
   - `fail`, `attempts >= 2` → `failed`: ferma i dipendenti, critico `failure`
     (reference/critic.md), poi chiedi all'utente
   - `blocked` → rispondi nella card se puoi, altrimenti chiedi all'utente;
     se dopo un livello 2 del watchdog → livello 3 (reference/watchdog.md)
5. Dopo OGNI transizione riscrivi state.json (log + metrics): il
   visualizzatore si aggiorna da lì.
6. A fine di ogni livello del DAG: checkpoint dei findings (dedupe, proposta di
   posizionamento, critico, AskUserQuestion, `backlog.md`): reference/findings.md.
   Un finding `high` che blocca nodi pianificati → checkpoint subito.
7. Inbox (change request di `/sjck-change` e decisioni della console): a ogni
   transizione esegui `python3 "<script>"/inbox.py pending --cwd "$PWD"`.
   Vuoto → prosegui. Altrimenti segui reference/inbox.md (priorità, critico,
   `inbox.py apply`, `inbox.py decisions --apply`). Sei l'UNICO a eseguirli.

## Step 4 — Chiusura
- L: lancia `sjck-reviewer` sul diff aggregato.
- `status: done`, `duration_s` nelle metriche. Rispondi con la tabella dei nodi (id, titolo, stato,
  tentativi), le metriche e un riassunto di massimo 5 righe.

## Regole ferree
- Mai saltare un nodo: si sblocca solo da state.json.
- Mai leggere i file prodotti dagli agenti: solo i loro JSON.
- Mai due nodi paralleli sugli stessi file.
- Mai `validated` senza un `pass`: .pre.json del precheck o .val.json del validatore.
