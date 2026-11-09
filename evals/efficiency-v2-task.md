# Task: esecutore deterministico per sjck-graph (efficienza in token)

Obiettivo: **ridurre il costo in token di un run di sjck-graph senza ridurne
l'affidabilità**. Su un run reale (task di sviluppo, 6 nodi, Opus 5 + Sonnet 5.5)
il costo era circa 2,3 volte quello della stessa task in auto mode
($26 contro $11, prezzi di listino, un solo run per lato).

## Dati misurati (non rifare l'analisi)

| Voce | Costo | Quota |
|---|---|---|
| Orchestratore (sessione principale, Opus) | $14,61 | 56% |
| Implementer T01-T06 | $8,01 | 31% |
| Validator (8 run) | $1,65 | 6% |
| Review finale | $1,80 | 7% |
| Checkpoint dei findings | $0,14 | 1% |

- L'orchestratore ha fatto 112 turni (l'intera sessione in auto mode ne ha fatti 77),
  con contesto da 42k a 266k token (medio 153k). La cache read è il 57% del suo costo.
- I 112 turni: 22 per lanciare o riprendere agenti, 34 di bookkeeping
  (`findings.py` 12, `watchdog.py` 8, `checks` 5, `tokens.py` 3, `plan_score.py` 3,
  `state_schema.py` 2, `interfaces.py` 1), 8 domande all'utente, circa 48 non classificati.
- Costo dell'orchestratore per nodo: circa $2,2-2,4. Un implementer piccolo costa $0,15-0,53.
- Retry: circa il 12% dei token (stima di `tokens.py`) su T04, T05, T06.
- T01 (nodo piccolo, passato al primo colpo) ha girato su Opus senza motivo.
- Console (`console/src/runner.js`) ed estensione VS Code lanciano entrambe
  `claude -p "/sjck-run ..."`: oggi il loop lo esegue un LLM. Non esiste un esecutore deterministico.
- Stima di tetto: senza orchestratore restano circa $14 contro $11,4 dell'auto
  (circa 1,2 volte), circa 1,1 con le mosse piccole. Sono ordini di grandezza, non misure.

## Fase 0 — Analisi (prima di modificare file)

Leggi `sjck-graph/skills/sjck-orchestration/SKILL.md` e i suoi `reference/`, gli agenti, gli
script in `sjck-graph/scripts/` e `docs/state-schema.md`. Poi verifica nella documentazione
ufficiale (https://code.claude.com/docs) come lanciare da `claude -p` **un singolo agente
definito dal plugin** con: modello, effort, numero massimo di turni, permessi, plugin
caricato da cartella e output JSON con `usage` e costo. Annota nel report i flag esatti con il
link alla pagina. Se un flag non esiste, scrivi l'alternativa scelta e perché.

## Parte A — runner deterministico (priorità 1)

Nuovo `sjck-graph/scripts/run_graph.py` (Python 3.9, solo standard library) che esegue il loop
degli Step 3-4 della skill senza LLM:

1. Legge `.sjck/state.json` (`status` `planned` o `running`; se `planned` controlla card, file
   disgiunti e assenza di cicli, poi imposta `running`).
2. Nodi pronti = `pending` con tutte le deps `validated`. Segna `running` nello stato e li
   lancia con `claude -p` come da Fase 0, rispettando `model`, `effort`, `budget` del nodo.
   Parallelismo: `--max-parallel` (default 1); sopra 1 solo per nodi con `files` disgiunti,
   nella stessa working tree (nessun worktree nella v1: documentalo come limite).
3. A fine nodo legge `.sjck/out/<ID>.json`, aggiorna stato, log e metriche, registra i
   `findings` con `findings.py add`, poi lancia il validator come LLM e legge `<ID>.val.json`.
4. Esito del validator: `pass` -> `validated`; `fail` con `attempts < 2` -> findings nella
   card sotto "Correzioni richieste", `attempts += 1`, nuovo tentativo dello stesso nodo;
   `fail` con `attempts >= 2` -> `failed`.
5. Al termine (o a ogni nodo) aggiorna `tokens.json` con `tokens.py`, tenendo il
   formato di `state.json` compatibile (viewer e console lo leggono): solo campi opzionali nuovi.

L'LLM interviene solo per le eccezioni. Il runner **non decide** niente di ambiguo: si
ferma con un codice di uscita e un messaggio, lasciando lo stato riprendibile.

| Codice | Significato |
|---|---|
| 0 | tutti i nodi `validated` o `done-unverified` |
| 10 | serve una decisione: nodo `blocked`, findings `high` che bloccano nodi pianificati, inbox con elementi in attesa |
| 11 | nodo `failed` dopo 2 tentativi |
| 12 | stallo (nessun nodo pronto né in corso) |
| 2 | stato o configurazione non validi |

Questa è una task di **sola implementazione**: non scrivere nuovi test (li scriviamo noi
dopo, con un `claude` finto). Rendi però il codice facile da testare: logica del loop in
funzioni pure separate dalle chiamate a `claude`, con il comando da lanciare iniettabile
(variabile d'ambiente o argomento), così un `claude` finto può sostituirlo.

## Parte B — integrazione nella skill (priorità 2)

In `sjck-orchestration/SKILL.md`: se `status` è `planned` o `running`, l'orchestratore esegue
`run_graph.py` e interpreta solo il codice di uscita (0: riepilogo finale; 10-12: gestisce
l'eccezione come oggi, poi rilancia il runner). I Step 0-2 e la chiusura (reviewer in L) restano
come sono. `/sjck-run` deve continuare a funzionare così com'è per console ed estensione.
Obiettivo misurabile: l'orchestratore passa da 112 turni a una decina per run.

## Parte C — mosse piccole (solo dopo A e B completate)

- **C1, politica dei modelli** in `agents/sjck-planner.md`: Opus per un implementer solo se
  molti nodi dipendono da lui o il rischio è alto; altrimenti Sonnet.
- **C2, granularità**: `plan_score.py` segnala (warning, non reject) i nodi troppo piccoli da
  accorpare, perché l'overhead per nodo (circa $2,2-2,4 oggi) supera il lavoro del nodo.
- **C3, retry**: il planner e la skill di pianificazione impongono nelle card criteri nella
  forma `comando -> esito atteso`.

Una riga in `CHANGELOG.md` per ogni parte, documentazione in `docs/` dove serve.

## Vincoli

- Python 3.9, solo standard library, nessuna chiamata di rete dal codice (leggere la
  documentazione in Fase 0 è consentito).
- Non rompere i test esistenti: a fine lavoro lancia **una sola volta**
  `python3 -m unittest discover -s sjck-graph/tests` (138 al commit di partenza) e
  compila ogni script nuovo con `python3 -m py_compile`. Nient'altro in termini di test.
- Non modificare `console/` né `vscode/`. Non modificare i file di misura
  `evals/sum_usage.py`, `evals/by_transcript.py`, `evals/ctx_profile.py` né questo file.
- Non leggere altri branch del repo. Lavora sul branch corrente: committa, non fare push né merge.
- Non lanciare `claude -p` veri né le task di `evals/`: la prova reale la facciamo noi dopo.

## Consegna

`EFFICIENCY-V2-REPORT.md` nella root, in italiano, con:
1. Flag di `claude -p` verificati, con link alla documentazione.
2. Per ciascuna parte: cosa è cambiato (file), comando esatto per verificarlo, limiti noti.
3. Come provare il runner a mano su una task di `evals/` (comandi esatti), senza
   averlo eseguito tu.
4. Cosa NON è stato verificato, e i rischi (in particolare: cosa faceva l'LLM
   orchestratore che il runner non fa).
