# Script e campi di stato v0.3

## Dove sono gli script
Come lo Step 0 della skill: `<script>` = prima cartella che contiene `plan_score.py`
(`test -f`), resa assoluta, tra `${CLAUDE_PLUGIN_ROOT}/scripts` (se espanso o non vuota in Bash),
`<base dir della skill>/../../scripts`, `~/.claude/sjck-scripts`, `.claude/sjck-scripts`.
Log `HH:MM script: <abs>`; nessuna → fermati. Nel prompt di OGNI agente metti `script: <abs>`.
Gli agenti con Bash usano quel valore; se manca: `${CLAUDE_PLUGIN_ROOT}/scripts` (se non vuota),
poi `~/.claude/sjck-scripts`, poi `.claude/sjck-scripts`. Python 3 standard library.

## plan_score.py
`python3 "<script>/plan_score.py" --cwd "$PWD"` — scrive `plan_score` in state.json e
stampa il JSON. Exit 0 = `ok`, 1 = `reject`, 2 = stato illeggibile o script mancante (python esce 2 se il file non esiste):
fermati, non avviare il loop, ricontrolla lo Step 0.
Rifiuta: ciclo, dep inesistente, overlap di file tra nodi paralleli, card mancante,
card oltre `budget.context_tokens`, card senza criteri.

## findings.py / watchdog.py
Vedi reference/findings.md e reference/watchdog.md.

## watchdog.py usage
`python3 "<script>"/watchdog.py usage --cwd "$PWD"` (default `--cwd .`): a nodo completato
scrive `nodes[].usage` in state.json (da watchdog_state.json) e le somme `tool_calls`,
`watchdog_warnings`, `watchdog_stops` in `metrics`; stampa `{"<id>": usage}`. Stato
illeggibile → exit 2. Dopo averlo lanciato rileggi state.json.

## Schema del nodo (aggiunte v0.3)
`model` (haiku|sonnet|opus|fable|inherit, def. inherit), `effort`
(low|medium|high|xhigh|max, def. medium), `budget` ({tool_calls:40, context_tokens:2000}),
`usage` (tool_calls, reads_outside_card, writes_outside_card, watchdog_warnings,
watchdog_stops: scritti da `watchdog.py usage`), `assumptions` ([str], copiate dall'out JSON).
Tabella indicativa (la compila il planner): scout haiku/low 20/1500; implementer facile
sonnet/medium 40/2000; medio sonnet/high 60/3000; difficile opus/high 80/4000;
validator sonnet/high 40/2000 (il validatore LLM è configurabile: vedi checks.py).

## checks.py (validazione livello 1)
`python3 "<script>"/checks.py run <ID> --cwd "$PWD" --base <sha>` → JSON su stdout e in
`.sjck/out/<ID>.l1.json`. Esegue i soli criteri della card nella forma
`` `comando` `` → esito atteso (`exit N`, `0 fallimenti`, `ok`; esito vuoto = exit 0) e
confronta il diff da `--base` (più i file non tracciati) con "Puoi modificare".
Campi: `outcome`, `checks`, `output`, `green` (comandi già verdi: il livello 2 NON li
riesegue), `residual` (i soli criteri da giudicare, voce `scope:` compresa),
`out_of_scope`, `action`, `invoke_llm`, `model`, `effort`.
Exit: 0 `pass` → `action: done`, nodo `validated` senza LLM · 1 `fail` → `retry`, niente
LLM, l'`output` va in "Correzioni richieste" · 2 `ambiguous` → `llm`, lancia
`sjck-validator` · 3 configurazione non valida (non è un `fail` del nodo).
La prosa resta sempre al livello 2: un criterio che il livello 1 non ha potuto eseguire
non è un criterio superato. `validator: llm` nei criteri forza il livello 2 anche su
`pass`; `validator.always_llm` lo forza sempre.
Modello ed effort del livello 2: `.sjck/config.json` →
`{"validator": {"model": "haiku", "effort": "low", "timeout_s": 300, "always_llm": false}}`
(oppure `~/.sjck/config.json`, `$SJCK_CONFIG`, `$SJCK_VALIDATOR_MODEL`,
`$SJCK_VALIDATOR_EFFORT`); default `sonnet`/`high`, come il frontmatter dell'agente.
Vanno passati come override al lancio: senza override vince il frontmatter e la
configurazione non ha effetto. `checks.py model` stampa il modello risolto.
I comandi girano in una shell nella cartella del run: vedi docs/limitations.md.

## context.py (dieta del contesto)
- `context.py top --cwd "$PWD"`: le due categorie di contesto più pesanti del run
  (da `tokens.json`) con l'intervento che le riduce.
- `context.py interfaces record --name <nome> --from-card <ID>`: registra l'hash dei
  file della sezione "Leggi" accanto all'interfaccia (`interfaces/<nome>.json`).
- `context.py interfaces check|reuse [--name <nome>]`: `fresh|stale|missing`; `reuse`
  ripesca anche da `.sjck/archive/*/interfaces/`. Exit 0 solo se tutte `fresh`.
- `context.py interfaces skip`: nodi `scout` pending con interfacce fresche
  (`reusable`) → `validated` senza lanciarli.
- `context.py card --id <ID> --role implementer|scout|validator|critic|reviewer
  [--attempt N]`: la card con le sole sezioni che quel ruolo usa.
- `context.py state --id <ID>`: goal + il nodo + le sue deps, invece di tutto lo stato.
- `context.py prompt --id <ID> --role <ruolo> --script "<script>" [--attempt N]`:
  prompt del nodo con la parte stabile in testa (prompt cache) e la card ridotta.

## config.py / prices.json (costo)
`config.py prices [--model NOME]` e `config.py validator` stampano la configurazione
effettiva e da quali file viene. Prezzi: `scripts/prices.json` (distribuito) →
`~/.sjck/prices.json` → `<run>/.sjck/prices.json` → `$SJCK_PRICES`; per modello
`input` e `output` in USD per milione, cache read/write dai moltiplicatori
(`cache_multipliers`: 0,1 e 1,25) o da un prezzo esplicito del modello. Un modello
assente non ha prezzo inventato: finisce in `cost.unpriced_models` e per lui si
mostrano solo i token. `tokens.py` scrive `cost` del run e `cost_usd` per nodo, per agente e per modello: reale se il
transcript ha `cost-state`, altrimenti `estimated: true`.

## Campi dello stato scritti da te
- `plan_score`: {width, critical_path, file_overlap, avg_card_tokens, verdict, reasons}.
- `sjck-critic`: [{at, round, verdict, points, resolution}] (reference/critic.md).
- `checkpoints`: [{after_level, findings_proposed, accepted, deferred, rejected}].
- `metrics`: subagents, validator_fails, tool_calls, watchdog_warnings, watchdog_stops,
  findings, findings_accepted, duration_s.
Riferimento completo: docs/state-schema.md del plugin.

## Lancio con override
Passa `model` ed `effort` del nodo come parametri del lancio (hanno priorità sul
frontmatter dell'agente; valgono anche a SendMessage). Ripieghi: con
`CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` il modello non è sovrascrivibile; `CLAUDE_CODE_EFFORT_LEVEL`
ha precedenza sull'effort; `xhigh`/`max` dipendono dal modello (ripiego `high`).
Il budget non ha parametro di lancio: scrivilo nel prompt ("max N tool call").

- `inbox.py`: change request e decisioni della console (pending, validate, next-id, apply [--dry-run], decisions [--apply]). Solo l'orchestratore esegue apply e decisions --apply: reference/inbox.md.
