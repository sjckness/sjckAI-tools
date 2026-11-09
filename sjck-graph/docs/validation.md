# Validazione a due livelli (P3)

Prima la validazione era una sola: un subagente LLM (`sjck-validator`,
sonnet/high) dopo ogni nodo, il cui primo compito era rieseguire i comandi dei
criteri di accettazione che l'implementer aveva già eseguito. Ora i due livelli
sono separati.

## Livello 1 — `precheck.py`, deterministico e gratis

```bash
python3 sjck-graph/scripts/precheck.py --id T01 --cwd .     # -> .sjck/out/T01.pre.json
```

Controlla:

1. **scope**: i file dichiarati in `.sjck/out/<ID>.json` stanno dentro
   "## Puoi modificare" della card? e il watchdog ha contato scritture fuori
   card (`usage.writes_outside_card`)?
2. **criteri**: ogni criterio di accettazione che contiene un comando viene
   eseguito nella cartella del run. È un comando se il primo token (basename,
   senza versione) è un runner noto: `python`, `pytest`, `npm`, `npx`, `make`,
   `cmake`, `ctest`, `colcon`, `cargo`, `go`, `ruff`, `flake8`, `mypy`,
   `eslint`, `tsc`, `bash`, `git`, … Altri si aggiungono con
   `validator.commands_allow`.

Esito e codice di uscita:

| exit | verdetto | cosa fa l'orchestratore |
| :- | :- | :- |
| 0 | `pass` | nodo `validated`, **nessuna chiamata al validatore LLM** |
| 1 | `fail` | i `findings` del pre.json vanno in "Correzioni richieste", **nessuna chiamata al validatore LLM** |
| 2 | `unclear` | lancia `sjck-validator` |
| 3 | errore | card o run illeggibili: si ferma |

Si passa al livello 2 quando: un criterio non è un comando ("il diff non lascia
TODO"), un comando va in timeout o non è eseguibile, manca l'out JSON del nodo,
un criterio dice `validator: llm`, oppure `validator.always_llm` è `true`.
Un timeout non condanna il nodo: diventa `unclear`, decide l'LLM.

I `findings` di un `fail` sono già azionabili senza LLM, es.:

```
criterio «`python3 -m unittest discover -s tests` esce 0»: `python3 -m unittest
discover -s tests` exit 1 — FAILED (failures=1) ... test_cost.py line 99
```

## Livello 2 — il validatore LLM, con modello configurabile

Il validatore parte solo su `unclear` e riceve nel pre.json ciò che è già stato
verificato: non rieseguire i comandi con un `rc`, valutare i criteri in
`llm_criteria` e quelli con esito incerto.

Modello ed effort del livello 2 (default `sonnet`/`high`, come il frontmatter
dell'agente), in ordine di precedenza:

```bash
# progetto
echo '{"validator": {"model": "haiku", "effort": "low"}}' > .sjck/config.json
# utente: ~/.sjck/config.json ; esplicito: $SJCK_CONFIG
export SJCK_VALIDATOR_MODEL=haiku SJCK_VALIDATOR_EFFORT=low   # vincono su tutto
python3 sjck-graph/scripts/config.py validator                # configurazione effettiva
```

Sezione `validator` completa: `model`, `effort`, `timeout_s` (per comando,
default 300), `always_llm` (tiene sempre il livello 2), `commands_allow`
(runner aggiuntivi). Il valore risolto finisce in
`llm_validator_model`/`llm_validator_effort` del pre.json: l'orchestratore lo
passa come override al lancio.

Quando conviene un modello piccolo: criteri quasi tutti deterministici, nodi
meccanici, repo con test veloci. Quando no: criteri scritti a parole, nodi
rischiosi (concorrenza, formati, sicurezza). `always_llm: true` riporta il
comportamento di prima.

## Affidabilità

Un `pass` del livello 1 richiede che **tutti** i criteri della card siano
comandi e che passino, più lo scope dentro la card. Un criterio a parole porta
sempre al livello 2, quindi il taglio non riguarda i nodi con criteri vaghi.
Il plan score già rifiuta le card senza criteri
(`sjck-graph/scripts/plan_score.py:162`), quindi un `pass` senza nessun criterio
non è raggiungibile da un run pianificato; una card senza criteri comunque
finisce in `unclear`, non in `pass`.

## Limiti

- I comandi girano in una **shell** nella cartella del run: chi scrive una card
  può eseguire codice. È lo stesso potere che ha oggi l'agente che li esegue,
  ma ora senza un LLM in mezzo: le card che arrivano da una change request
  vanno lette prima di avviare il run (`--dry-run` li elenca senza eseguirli).
- Lo scope si basa sui file **dichiarati** dall'implementer più i contatori del
  watchdog: senza watchdog (installazione senza plugin) resta la dichiarazione.
- Un test che passa non dice che il nodo ha fatto la cosa giusta: resta la
  review finale (`sjck-reviewer`) in modalità L.
- Il livello 1 non controlla stub vuoti, TODO e test disattivati (controllo 4
  del validatore): se la card non lo chiede come criterio, nessuno lo verifica.
  Metti un criterio a parole quando ti serve quel controllo.
