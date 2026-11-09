# Task: fusione delle parti migliori di due implementazioni

La stessa rubrica (P1 costo in USD per nodo, agente e run; P2 dieta del contesto;
P3 validazione a due livelli: prima i controlli deterministici, poi l'LLM solo se serve)
è stata implementata due volte, in modo indipendente, partendo dallo stesso commit:

- **SJCK** = `origin/test/efficiency-sjck` (10 commit, 205 test)
- **AUTO** = `origin/test/efficiency-auto` (1 commit, 176 test)

Obiettivo: **un solo branch, partito da `main`, con il meglio di ciascuno.**
Le decisioni per componente sono già prese: non rifare l'analisi e non rivalutare le scelte.
Se un pezzo non si può portare come previsto, scegli la via più semplice e scrivilo nel report.

## Metodo

Il branch corrente parte da `main`. Lancia `git fetch origin`, poi porta i file con
`git checkout origin/<branch> -- <percorso>` oppure leggili con `git show origin/<branch>:<percorso>`.
I due branch toccano entrambi gli stessi sei file (`sjck-graph/scripts/tokens.py`,
`sjck-graph/skills/sjck-orchestration/SKILL.md`, `agents/sjck-planner.md`,
`agents/sjck-validator.md`, `CHANGELOG.md`, `EFFICIENCY-REPORT.md`): **non usare `git merge`**,
fondi a mano. `EFFICIENCY-REPORT.md` dei due branch non va portato.

## Decisioni per componente

| Componente | Prendi da | Note |
|---|---|---|
| Prezzi e configurazione | AUTO | `sjck-graph/scripts/config.py` e `sjck-graph/scripts/prices.json` |
| Costo per agente | SJCK | `by_agent` e `_costs` in `tokens.py` |
| Due categorie più pesanti | AUTO | `context.py top` |
| Riuso delle interfacce | AUTO | `context.py interfaces` (record, check, reuse, skip) |
| Card ridotta, stato a fetta, prompt a prefisso stabile | AUTO | `context.py card`, `state`, `prompt` |
| Agenti senza CLAUDE.md | SJCK | `omitClaudeMd: true` su tutti e 6 gli agenti, più la nota del planner su dove trovare i comandi di test |
| Scope-check | SJCK | `checks.py` sul diff git con `--base` |
| Contratto verso il validator | SJCK | `green` e `residual` nel file di esito del livello 1 |
| Criteri nelle card | SJCK | forma `comando -> esito atteso`, imposta dal planner |
| Modello del validator | AUTO | `config.py` (`validator.model`, `effort`, `timeout_s`, `always_llm`, variabili `SJCK_VALIDATOR_*`) |
| Estrazione di comandi dalla prosa | nessuno | **NON portare** `precheck.py` né quell'estrazione |

## Cosa fare, componente per componente

**P1 — costo.** `tokens.py` parte dalla versione SJCK (ha `by_agent`, `by_node[].cost_usd`,
`_costs`), ma sostituisci i suoi prezzi per famiglia (`load_prices`, `model_price`,
`estimate_usd`, il file `sjck-graph/config/prices.json`) con `config.load_prices`,
`config.rates` e `config.cost_of` di AUTO. Requisiti da mantenere: un modello senza prezzo
mostra solo i token (`unpriced_models`, mai un prezzo inventato); `estimated: true` quando il
costo non viene da `cost-state`; cache read e cache write con moltiplicatori o prezzi
espliciti; costo per run, nodo, agente e modello; i campi di costo e risparmio in dollari che
AUTO aggiunge agli insight di `token-report.json`. La chiamata HTTP per il cambio EUR
(`eur_per_usd`) esiste già in entrambi: **non modificarla né estenderla**.

**P2 — contesto.** Porta `context.py` di AUTO così com'è. **Scarta** `interfaces.py` e `cards.py`
di SJCK: prima cerca con `grep` ogni uso di quei moduli nel resto del repo
(agenti, skill, docs, test, `install.sh`) e sostituiscilo; verifica che le funzioni di
`cards.py` che servono davvero (card ridotta, fetta di stato, ordine del prompt) siano
coperte da `context.py card`, `state` e `prompt`. Agenti: `omitClaudeMd: true` su critic, planner,
reviewer, validator, scout, implementer; nel planner mantieni la nota di SJCK (non vede
CLAUDE.md: ricava i comandi di test, lint e build da `package.json`, Makefile, `pyproject.toml`,
workflow CI) e la regola di AUTO per le card dello scout (`.sjck/interfaces/<nome>.md` in
"Puoi modificare", i sorgenti in "Leggi").

**P3 — validazione.** `checks.py` di SJCK è la base: esegue solo i criteri `comando -> esito`,
la prosa resta al livello 2, lo scope si controlla sul diff git (`--base`), un controllo non
verificabile è `ambiguous`. Sostituisci la sua risoluzione del modello del validator con
`config.load_config` di AUTO e togli `sjck-graph/config/validation.json`, o tienilo solo come
default letto da `config.py` (scegli la via più semplice e documentala). Nome unico del file di
esito del livello 1: `.sjck/out/<ID>.l1.json`; aggiorna ogni riferimento (agente validator,
skill, docs). I codici di uscita sono già identici nei due branch (0 pass, 1 fail,
2 ambiguous, 3 configurazione non valida). Agente validator: una sola versione, che legge
`.l1.json`, non riesegue i comandi in `green`, giudica solo `residual`, scope e regressioni, e
legge la card ridotta prodotta da `context.py card`.

**Skill di orchestrazione.** Fusione manuale di `SKILL.md`: scout saltati con
`context.py interfaces skip`, prompt dei nodi con `context.py prompt`, validazione con
`checks.py run <ID> --base <sha>`, testo sul costo in denaro di SJCK (`estimated` sempre
citato). Aggiorna `reference/scripts.md` e `skills/sjck-planning/SKILL.md` con l'elenco finale
degli script. Alla fine nessun riferimento deve restare a `precheck.py`, `interfaces.py`,
`cards.py` né a `.pre.json`.

**Test.** Porta i test già esistenti dei pezzi scelti e adattali ai nomi e percorsi finali: da
SJCK `test_checks.py`, `test_prices.py`, `test_agents.py`, `test_install.py`; da AUTO
`test_context.py`, `test_cost.py`. Scarta quelli dei pezzi scartati (`test_interfaces.py`,
`test_precheck.py`). **Non scrivere test nuovi**, salvo il minimo per un buco creato dalla
fusione (dichiaralo nel report). Se due test verificano la stessa cosa, tieni il migliore.

**Installazione e documentazione.** Verifica che `install.sh` e `sjck update` copino tutto
ciò che serve nella posizione finale di `prices.json` e dei file di configurazione, e porta da
`install.sh` di SJCK solo quello che resta necessario. Una sola serie di documenti, in
`sjck-graph/docs/` (costi, contesto, validazione). Porta `limitations.md` di AUTO eliminando
i limiti legati a `precheck.py` e mantenendo l'avviso che i comandi delle card vengono
eseguiti da `checks.py`. Un solo bump di versione in `plugin.json` e una sola voce in
`CHANGELOG.md`.

## Vincoli

- Python 3.9, solo standard library, nessuna chiamata di rete dal codice.
- Non modificare `console/` né `vscode/`. Non modificare `evals/sum_usage.py`,
  `evals/by_transcript.py`, `evals/ctx_profile.py` né questo file.
- Non lanciare `claude -p` veri né le task di `evals/`.
- A fine lavoro lancia **una sola volta** `python3 -m unittest discover -s sjck-graph/tests` e
  compila ogni script con `python3 -m py_compile`. Tutti i test devono passare.
- Committa sul branch corrente: non fare push né merge.

## Consegna

`EFFICIENCY-MERGE-REPORT.md` nella root, in italiano:
1. Tabella componente, origine effettiva, file finali.
2. Cosa è stato scartato e dove sono stati rimossi i riferimenti.
3. Decisioni prese dove la task era ambigua o un pezzo non si portava come previsto.
4. Esito della suite (numero di test, quali sono stati scartati e perché) e comando per rilanciarla.
5. Cosa NON è stato verificato.
