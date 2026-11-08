# Changelog

## sjck-graph — non rilasciato · efficienza in token (P1-P3)
- P1: costo in USD per nodo, per agente e per run in `tokens.json` / `token-report.json`; prezzi configurabili (`sjck-graph/config/prices.json`, override `.sjck/prices.json`); flag `estimated` (costo reale da `cost-state` vs stima dai prezzi); `by_node[].models` è ora un dict per modello. Dettagli in `docs/costs.md`.
- P2: dieta del contesto — riuso delle interfacce via hash (`scripts/interfaces.py check|register|invalidate`: con `fresh` lo scout non parte), card e stato selettivi per il validator (`cards.select_sections`, `cards.select_state`) e ordine del prompt stabile per la prompt cache (`cards.build_prompt`). Dettagli e riduzioni (stime) in `docs/context-diet.md`.
- P3: validazione a due livelli — `scripts/checks.py` esegue i criteri `comando -> esito` della card (mai rieseguiti dall'LLM) e passa al validatore LLM solo i criteri residui non eseguibili (`green`/`residual` in `.sjck/out/<ID>.l1.json`); su `fail` l'LLM non parte; modello del validatore in `config/validation.json` (override `.sjck/validation.json`); `omitClaudeMd: true` su tutti gli agenti. Dettagli in `docs/validation.md`.

## sjck-graph 0.4.0 — 2026-10-28 · `/sjck-graph:sjck-update`
- Nuovo comando `/sjck-graph:sjck-update` (`scripts/update.py`, solo libreria standard): confronta l'installato con l'ultima release GitHub e aggiorna plugin (marketplace `sjck`), estensione VS Code (`sjck.vsix`, solo se indietro; code/cursor/codium) e console (`sjck-console.tgz`, solo se già installata). `check` per il solo confronto, `--only`, `--editor`. Ricorda di riavviare Claude Code / ricaricare VS Code.
- Versione del plugin portata a 0.4.0: era ferma a 0.3.2 nonostante planner interattivo, token reali e costo in euro, e con la stessa versione `claude plugin update` poteva non scaricare niente.
- 5 test nuovi (`claude` e `code` finti nel PATH).

## vscode 0.1.5 — 2026-10-28 · planning interattivo e token reali
- `/sjck-plan` è una conversazione: ogni scelta che cambia il piano passa da AskUserQuestion (domande iniziali se la task è vaga, scelta dell'alternativa, conferma delle ottimizzazioni che toccano lo scope, approvazione finale). In `claude -p` resta senza domande, con default dichiarati in `assumptions`.
- Handoff all'estensione: dopo l'approvazione il planner scrive le card e per ultimo `state.json` (`status: "planned"`, nuovo campo `planned_at`). L'estensione lo vede col file watcher, apre la vista sjck e notifica "plan ready" con nodi, modalità e stima token → *Approve and run*.
- Estensione: si attiva all'avvio (anche in workspace senza `.sjck/`), annuncia il primo piano e ogni ri-piano (`planned_at` diverso), *Plan a task* apre `claude "/sjck-plan …"` interattivo in un terminale (`sjck.plan.interactive`, default on), *Approve and run* usa la modalità del piano senza richiederla. Nuova impostazione `sjck.revealOnPlan`.
- Token reali (v0.4 parte A, minima): `scripts/tokens.py` legge i transcript di Claude Code (sessione principale + un transcript per subagente) e scrive `.sjck/tokens.json` con input, output, cache letta/scritta per nodo e per modello. Gira negli hook `SubagentStop` (fine di ogni nodo, attribuito tramite `agent_id`) e `Stop` (fine di ogni turno; la sessione di planning finisce sotto `PLAN`). Le righe in streaming dello stesso messaggio contano una volta; nessun testo dei messaggi esce dai transcript. Categorie di contesto (stimate): l'input reale di ogni turno viene diviso tra `system`, `card`, `interfaces`, `file_read_in_card`, `file_read_outside_card`, `tool_output`, `agent_messages`, `other` in proporzione a ciò che c'era nel contesto (caratteri/4, azzerato dalle compattazioni); il resto non spiegato è `system`. Il viewer lo segnala come "estimated split of real input".
- `.sjck/token-report.json` con gli insight: letture fuori card (card povere), cache hit bassa, token spesi in nodi falliti o tentativi ripetuti, opus su nodi piccoli approvati al primo colpo, il risparmio del contratto (report dei subagenti vs file letti dai nodi), i tool output più grandi. Un eventuale confronto con la baseline già presente viene conservato.
- Estensione: totale token del run nella riga in cima alla vista Graph, con tooltip (tipi, cache hit, nodi più costosi); i token per nodo compaiono nell'albero appena esiste `tokens.json`.
- Verifiche: 122 test plugin (9 nuovi sui token), 16 console, 7 estensione; type-check ok; tab Tokens renderizzato in jsdom con dati prodotti dal raccoglitore (categorie + insight, nessun errore JS). Non ancora provata dentro un VS Code reale né su transcript veri.
- Token verificati su transcript reali (4 sessioni, 14 subagenti) contro l'evento `cost-state` di Claude Code: input e cache esatti, output entro ±6% (prima −35%: nei transcript dei subagenti manca spesso la riga finale dello streaming; ora l'output si ricostruisce dal contenuto, thinking stimato dalla `signature`). Saltati gli `api-request-blob` (copie dei messaggi, contate due volte). Nuove categorie `thinking` (il thinking passato resta nel contesto) e `reminders`; fattore caratteri→token calibrato su ogni transcript (≈2,3-2,5, non 4), così `system` torna alla dimensione reale del system prompt. Nuovo insight sul thinking.
- Costo reale da `cost-state`, ripartito per nodo e convertito in euro col tasso di riferimento BCE (una richiesta al giorno, cache in `~/.sjck/fx.json`, nessun nuovo tentativo per un'ora dopo un errore, override `SJCK_EUR_PER_USD`). Run Viewer: KPI costo in €.

## console 0.3.0 — 2026-10-27 · installazione senza clone
- Installer in un comando: `get.sh` (Linux/macOS) e `get.ps1` (Windows) controllano i requisiti, installano la console dal pacchetto della release, i plugin e l'estensione.
- Console: nuovi comandi `sjck setup`, `sjck doctor`, `sjck vscode [--editor]`, `sjck update` (`src/setup.js`, 3 test nuovi).
- Release unica (`.github/workflows/release.yml`, tag `v*` o `vscode-v*`) con asset a nome fisso `sjck-console.tgz` e `sjck.vsix`, scaricabili da `releases/latest/download/`. Prima la console funzionava solo da una copia locale perché `ui/viewer.html` è generato.
- README: nuova guida di installazione (one-liner, passi manuali, aggiornamento, opzioni, disinstallazione, troubleshooting).

## vscode 0.1.4 — 2026-10-26 · Mission Control
- Estensione VS Code: nuovo pannello Mission Control (grafo animato live con pan/zoom, anello di avanzamento, statistiche, drawer per nodo, inbox interattiva, plan score, timeline) aggiornato via `postMessage`; chat del planner ridisegnata.

## vscode 0.1.0 — 2026-10-26
- Estensione VS Code nativa (`vscode/`): vista Graph nell'activity bar (livelli e nodi con stato, modello/effort, tool call vs budget, tentativi, token; card al clic; diff dei file cambiati da un nodo), barra di stato, decorazioni nell'Explorer, Run Viewer in una tab (CSP con nonce), chat col planner nella sidebar, Inbox con approvazioni, Plan/Run/Stop con log nell'output, notifiche.
- Riusa i moduli della console (`data`, `inbox`, `runner`, `chat`), copiati in `lib/` al packaging; non scrive mai lo stato del run.
- Verifiche: type-check con `@types/vscode`, 5 test (logica e attivazione con un `vscode` finto), pacchetto `.vsix` generato con `vsce`. Non ancora provata dentro un VS Code reale.

## 0.3.2 + console 0.2.0 — 2026-10-26 · live change requests
- sjck-graph: `scripts/inbox.py` (pending, validate, next-id, apply [--dry-run], decisions [--apply]): change request con op add_node, edit_card, set, remove_node, add_dep, rerun (a cascata sui dipendenti, output precedente in `.prev.json`), accept_finding, kit_change (solo proposta in `.sjck/kit-proposals/`). Rollback se il plan score diventa `reject`; exit 3 se tocca un nodo in esecuzione.
- sjck-graph: skill e comando `/sjck-change` per discutere modifiche a un run in corso in una seconda sessione; l'orchestratore controlla l'inbox a ogni transizione (`reference/inbox.md`), unico a scrivere lo stato.
- console: tab Chat (planner via `claude -p` con sessione ripresa, tool limitati a lettura + scrittura in `.sjck/changes/`), tab Inbox (apply/reject CR, accept/defer/reject findings, approva il piano), notifiche nella pagina, desktop e webhook (ntfy).
- Test: 11 nuovi per inbox.py (124 nel plugin), 16 nella console.

## console 0.1.0 — 2026-10-26
- Nuova app `console/` (Node ≥ 20, zero dipendenze): `sjck serve`, `sjck add/remove/list`.
- Home con tutti i progetti registrati e stato live; pagina di progetto con Run Viewer aggiornato via SSE, pannello Task (Plan/Run con `claude -p`, modalità S/M/L, stop) e log del run in streaming.
- Sicurezza: solo localhost, token casuale (cookie HttpOnly/SameSite=Strict), controllo dell'header Host contro il DNS rebinding, limite sul body, tipi di run in whitelist.
- La console non scrive lo stato del run: legge `.sjck/` e salva i propri log in `.sjck/console/runs/`.
- 12 test (`npm test` in `console/`); spec in `docs/specs/console.md`.

## 0.3.1 — 2026-10-26 · rebranding sjck
- Marketplace `sjck` (repo `sjckness/sjckAI-tools`); plugin `graph-kit` → `sjck-graph`, `project-onboard` → `sjck-onboard`.
- Comandi: `/sjck-run`, `/sjck-plan`, `/sjck-status`, `/sjck-view`, `/sjck-eval`, `/sjck-onboard`.
- Skill: `sjck-orchestration`, `sjck-planning`, `sjck-onboarding`. Agenti: `sjck-planner`, `sjck-scout`, `sjck-implementer`, `sjck-validator`, `sjck-reviewer`, `sjck-critic` (niente conflitti con agenti di altri plugin).
- Cartella di lavoro `.sjck/` al posto di `.graph/`; script installati in `~/.claude/sjck-scripts`; variabili `SJCK_REPO`, `SJCK_REF`.
- Watchdog: riconosce i ruoli degli agenti anche con il prefisso `sjck-`.
- Migrazione: `/plugin uninstall graph-kit@aitools` e `project-onboard@aitools`, poi `/plugin marketplace add sjckness/sjckAI-tools` e installa i nuovi. Un run in corso in `.graph/` si riprende rinominando la cartella in `.sjck/`.

## 0.3.0 — 2026-10-26
- graph-kit: schema di stato v0.3 (`docs/state-schema.md`) con validazione in `scripts/state_schema.py`.
- graph-kit: plan score del DAG (`scripts/plan_score.py`): larghezza per livello, percorso critico, overlap di file, token per card; `reject` (exit 1) impedisce l'avvio ed è rilanciato sui nodi aggiunti a run avviato.
- graph-kit: watchdog a hook (livelli 1-2 nel plugin, livello 3 all'orchestratore); blocca le scritture fuori dai `files` della card. Attribuzione per `agent_id`; gli `agent_type` validator, critic, reviewer, planner sono ignorati; il ciclo modifica→test non scala (le scritture con contenuto nuovo azzerano i contatori di comandi ed errori). La usage è in `watchdog_state.json` e `watchdog.py usage` la copia in `state.json` a nodo completato.
- graph-kit: la skill risolve gli script allo Step 0 e li passa agli agenti con `script: <abs>`; exit 2 di plan_score = stato illeggibile o script mancante; il livello 3 "rimanda" non blocca il run; nelle sessioni non interattive niente domande (findings in backlog `deferred`, altrimenti run `failed`).
- graph-kit: findings (`.graph/findings.jsonl`, `scripts/findings.py`) con backlog e checkpoint a fine livello; `assumptions` nell'out JSON degli agenti.
- graph-kit: agente `critic` read-only (model `fable`, effort `high`) che approva o contesta piani e findings senza leggere codice.
- graph-kit: `model`, `effort` e budget per nodo.
- Eval harness `evals/` e comando `/graph-eval`: usa il plugin del checkout (`--plugin-dir`) e permessi non interattivi di default (`--no-default-flags` per toglierli).
- `install.sh`: copia solo file regolari; crea il `.bak` solo se l'utente ha modificato il file installato.
- graph-kit: il Run Viewer della 0.2.1 integrato con i campi v0.3 (modello/effort, budget, usage live da `watchdog_state.json`, eventi del watchdog, critico, plan score); `graph_view.collect()` prepara e pulisce i dati, il rendering avviene nel browser.
- Integrati anche `/graph-plan` (0.2.2) e la demo `examples/demo/`.
- graph-kit: `docs/limitations.md` con le limitazioni note.

### Limiti noti / da fare
- `attempts` conta ancora i fail del validator e le riprese "rispondi"; contatore `resumes` separato non introdotto (findings[8]).
- Il campo `findings` di `.val.json`/`REVIEW.json` non è rinominato; la risposta del critic non ha `assumptions` (findings[9], spec_gaps[1]).
- `view.html` non si rigenera sulle scritture di watchdog.py, plan_score.py, findings.py (findings[10]).
- `install.sh` non copia `docs/` (state-schema.md, limitations.md) citati dalla skill (findings[12] punto 3).
- Nodi in worktree: l'out JSON resta nel worktree e il validator non ha Write per `.val.json` (findings[14]).
- Eval: nessun esito per trap (rabbit_hole, out_of_scope_bug); compare.py vede solo i totali (spec_gaps[4]).
- Tra il lancio e la scrittura di `agent_id` i nodi lanciati insieme condividono il secchio comune; l'uguaglianza tra `agent_id` dell'hook e del tool di lancio non è documentata (residuo di spec_gaps[3]).
- Formato di REVIEW.json in reviewer.md (`pass|fail`, findings stringhe) diverso da quello usato nell'ultima review (`ok|issues`, oggetti, `spec_gaps`, `checks`).

## 0.2.2 — 2026-10-26
- Nuova skill e comando `/graph-plan`: pianificazione guidata con domande mirate, alternative con stime di token e tempo, checklist di ottimizzazione e piano `planned` pronto per `/run-graph`.
- `graph-orchestration` esegue un piano `planned` senza rifare triage e planner, rispettando modello, effort e budget per nodo; per task grandi e vaghe suggerisce `/graph-plan`.
- Run Viewer: stato `planned` in ambra.

## 0.2.1 — 2026-10-26
- Nuovo Run Viewer (`.graph/view.html`): una pagina con viste Grafo, Token e Findings, tema scuro, leggibile da telefono, nessuna libreria esterna (niente più Mermaid).
- Il viewer legge in modo opzionale `tokens.json`, `token-report.json`, `findings.jsonl` e `watchdog.jsonl`; con uno stato v0.2 mostra solo il grafo.
- Scrittura atomica della pagina; si ricarica da sola solo mentre il run è in corso.
- Demo in `examples/demo/` e README con screenshot.

## 0.2.0 — 2026-10-26
- graph-kit: la logica è ora una skill (`graph-orchestration`) che Claude attiva da solo per task grandi; `/run-graph` resta come scorciatoia.
- graph-kit: override dell'utente su modalità e agenti (`--mode M`, "usa solo implementer e validator").
- graph-kit: stato in `.graph/state.json`; visualizzatore live `.graph/view.html` aggiornato da hook, comando `/graph-view`.
- Nuovo plugin `project-onboard`: `/onboard` genera CLAUDE.md compatto + `.claude/map/<modulo>.md`.

## 0.1.0 — 2026-10-26
- Prima versione: triage S/M/L, planner, scout, implementer, validator, reviewer.
- Stato persistente in `.graph/state.yaml` con ripresa automatica.
- Installazione come plugin Claude Code o via `install.sh`.
