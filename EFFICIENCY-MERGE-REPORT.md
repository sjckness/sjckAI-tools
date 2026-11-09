# Fusione delle due implementazioni (SJCK + AUTO) — report

Branch: `feat/efficiency-merge`, partito da `main`. Fusione a mano dei sei file
condivisi, nessun `git merge`. Versione del plugin: **0.5.0** (un solo bump, una
sola voce di CHANGELOG).

## 1. Componente, origine effettiva, file finali

| Componente | Origine effettiva | File finali |
|---|---|---|
| Prezzi e configurazione | AUTO (verbatim) | `sjck-graph/scripts/config.py`, `sjck-graph/scripts/prices.json` |
| Costo per run, nodo, agente, modello | SJCK (`by_agent`, `_costs`) + prezzi di AUTO | `sjck-graph/scripts/tokens.py` (fuso a mano) |
| Due categorie più pesanti | AUTO | `sjck-graph/scripts/context.py` (`top`) |
| Riuso delle interfacce | AUTO | `context.py` (`interfaces record/check/reuse/skip`) |
| Card ridotta, stato a fetta, prompt a prefisso stabile | AUTO | `context.py` (`card`, `state`, `prompt`) |
| Parser delle card | `main` (invariato) | `sjck-graph/scripts/cards.py` |
| Agenti senza CLAUDE.md | SJCK | `omitClaudeMd: true` su tutti e 6 gli agenti; nota del planner sui comandi di test/lint/build |
| Card dello scout riusabili | AUTO | `sjck-graph/agents/sjck-planner.md` |
| Scope-check sul diff git (`--base`) | SJCK | `sjck-graph/scripts/checks.py` |
| Contratto verso il validator (`green`/`residual`) | SJCK | `checks.py`, `.sjck/out/<ID>.l1.json` |
| Criteri `comando -> esito` nelle card | SJCK | `sjck-graph/agents/sjck-planner.md`, `skills/sjck-orchestration/SKILL.md` |
| Modello/effort/timeout/always_llm del validator | AUTO (`config.load_config`) | `checks.py` (risoluzione), `sjck-graph/agents/sjck-validator.md` |
| Agente validator | fusione a mano (SJCK + AUTO) | `sjck-graph/agents/sjck-validator.md` |
| Skill di orchestrazione | fusione a mano (SJCK + AUTO) | `skills/sjck-orchestration/SKILL.md`, `reference/scripts.md` |
| Skill di pianificazione | AUTO | `skills/sjck-planning/SKILL.md` |
| Documentazione | AUTO (percorsi e base) + SJCK (livello 1, costo per agente) | `sjck-graph/docs/cost.md`, `context-diet.md`, `validation.md`, `limitations.md` |
| README, plugin.json, CHANGELOG | AUTO, adattati | `README.md`, `sjck-graph/.claude-plugin/plugin.json`, `CHANGELOG.md` |
| Test | SJCK + AUTO, adattati | `tests/test_checks.py`, `test_context.py`, `test_cost.py`, `test_prices.py`, `test_agents.py`, `test_install.py` |

I sei file condivisi (`scripts/tokens.py`, `skills/sjck-orchestration/SKILL.md`,
`agents/sjck-planner.md`, `agents/sjck-validator.md`, `CHANGELOG.md`,
`EFFICIENCY-REPORT.md`) sono stati trattati così: i primi quattro fusi a mano
riga per riga, `CHANGELOG.md` riscritto in una sola voce, `EFFICIENCY-REPORT.md`
di entrambi i branch **non portato**.

## 2. Cosa è stato scartato, e dove sono stati rimossi i riferimenti

Scartati del tutto:

- **`precheck.py` di AUTO** e la sua estrazione di comandi dalla prosa, più
  `tests/test_precheck.py` e il file di esito `.pre.json`.
- **`interfaces.py` di SJCK** e `tests/test_interfaces.py` (sostituiti da
  `context.py interfaces`).
- **Le aggiunte di SJCK a `cards.py`** (CLI `sections`/`state`/`prompt`): coperte
  da `context.py card` (`select_sections` → `card_slice`, con in più il filtro
  per ruolo e `--attempt`), `context.py state` (`select_state` → `state_slice`) e
  `context.py prompt` (`build_prompt` → `node_prompt`, prefisso stabile in testa).
  `cards.py` resta quello di `main`.
- **Il modello di prezzi di SJCK** in `tokens.py` (`load_prices`, `model_price`,
  `estimate_usd`, `prices_default_path`, `BUILTIN_PRICES`, `_merge_prices`) e la
  cartella **`sjck-graph/config/`** (`prices.json`, `validation.json`).
- **I documenti di SJCK nella root** (`docs/costs.md`, `docs/context-diet.md`,
  `docs/validation.md`): una sola serie resta in `sjck-graph/docs/`.

Dove sono stati rimossi i riferimenti (verificato con `grep` su tutto il repo,
esclusi `console/`, `vscode/`, `evals/`):

| Riferimento | Rimosso da |
|---|---|
| `precheck.py` | `context.py` (testo di `ACTIONS["system"]` → `checks.py`), `tests/test_context.py` (asserzione), `skills/sjck-orchestration/SKILL.md` (Step 3.4), `reference/scripts.md` (sezione riscritta come `checks.py`), `agents/sjck-validator.md`, `docs/limitations.md`, `docs/validation.md`, `README.md`, `CHANGELOG.md` |
| `.pre.json` | `agents/sjck-validator.md`, `SKILL.md`, `reference/scripts.md`, `docs/validation.md` |
| `interfaces.py` | `agents/sjck-scout.md` (ora `context.py interfaces check|record`), `SKILL.md` (Step 3.2/3.3). I docs finali vengono da AUTO e non lo citavano; quelli di SJCK che lo citavano (`docs/context-diet.md` nella root) non sono stati portati |
| CLI di `cards.py` | `agents/sjck-validator.md` (card ridotta via `context.py card`), `SKILL.md` (Step 3.4); `.sjck/out/<ID>.card.md` non esiste più. Come sopra per i docs |
| `config/validation.json`, `config/prices.json` | `checks.py` (ora `config.load_config`), `tokens.py` (ora `config.load_prices`), `tests/test_checks.py`, `tests/test_install.py`, `install.sh` (il blocco che copiava `config/` non è stato portato), `docs/*`, `SKILL.md` |

Resta `import cards` dentro `checks.py`, `context.py` e `plan_score.py`, e la
riga «Parser delle card: `sjck-graph/scripts/cards.py`» in
`docs/state-schema.md` (già in `main`): il divieto è stato letto come «nessun
riferimento alla *CLI* `cards.py` di SJCK in agenti, skill e docs», non come
rimozione del modulo di `main`, che serve a tre script.

## 3. Decisioni prese dove la task era ambigua o un pezzo non si portava

1. **`sjck-graph/config/` eliminata invece che tenuta come default** (la task
   lasciava la scelta): i default del validatore sono già nel codice
   (`config.DEFAULT_CONFIG`) e il listino è `scripts/prices.json`, distribuito
   accanto agli script. Di conseguenza da `install.sh` di SJCK **non serviva
   niente**: `install.sh` copia già tutti i file di `scripts/`, quindi
   `prices.json` arriva in `<DEST>/sjck-scripts/` dove `config.py` lo cerca.
2. **Nome del flag per voce: `estimated`, non `cost_estimated`.** SJCK usa
   `by_node[].estimated`/`by_agent[].estimated`, AUTO `by_node[].cost_estimated`.
   Poiché `tokens.py` parte da SJCK (contratto di `_costs`), è rimasto
   `estimated`; le asserzioni di `test_cost.py` sono state adattate.
3. **Forma di `cost` in `token-report.json`: quella di SJCK** (`by_node` e
   `by_agent` come `{usd, estimated}`), arricchita con i campi di AUTO (`eur`,
   `source`, `by_model`, `unpriced_models`) e con `cost_usd`/`saving_usd` su ogni
   insight. Una sola asserzione di `test_cost.py` è stata adattata di conseguenza.
4. **Cambio EUR non toccato né esteso**, come chiesto: la chiamata resta solo sul
   percorso del costo reale (`cost-state`), come in `main` e in SJCK. AUTO
   l'aveva estesa anche al costo stimato; quella asserzione di `test_cost.py` è
   stata sostituita con una sul costo per agente. Il costo stimato resta in USD:
   è documentato in `docs/cost.md`.
5. **Timeout del livello 1: `timeout_s` di `config.py` (300 s)**, non il
   `timeout: 600` di `config/validation.json`, che non esiste più. `checks.py`
   valida anche `effort` e `timeout_s`: un valore non valido resta exit 3, come
   il modello non valido.
6. **`always_llm` di AUTO applicato senza toccare `decide()`**: `checks.py`
   alza `llm_required` prima di chiamare `decide`, così la decisione
   `invoke_llm` resta un'unica funzione usata da CLI e `validate()` (invariante
   di SJCK).
7. **`.l1.json` porta anche `effort`** (prima solo `model`): la configurazione di
   AUTO ha due campi da passare come override al lancio del validatore, e
   l'orchestratore legge entrambi da quel file.
8. **`SKILL.md` fusa in modo compatto** per restare sotto il limite di 180 righe
   di `test_skill.py` (è a 176): il punto «ordine del prompt» che SJCK metteva
   nello Step 0 non è stato duplicato, perché lo Step 3.2 già impone
   `context.py prompt` (che mette il prefisso stabile in testa e include il
   budget).
9. **`agents/sjck-scout.md`**: il paragrafo di riuso di SJCK è stato mantenuto ma
   riscritto su `context.py interfaces check|record`; il campo `sources` nell'out
   JSON resta (`context.py interfaces record --from-card` usa la sezione «Leggi»
   della card, `sources` serve all'orchestratore quando la card non basta).
10. **`README.md`**: la task non lo citava, ma AUTO lo aggiornava e descriveva
    `precheck.py`. Le sue aggiunte sono state portate e riscritte su `checks.py`,
    per non lasciare la 0.5.0 descritta da nessuna parte in inglese.
11. **`docs/cost.md`** (nome di AUTO, non `costs.md` di SJCK) documenta anche il
    costo per agente e la chiave di `by_agent` (nome del transcript).

## 4. Esito della suite

```
python3 -m unittest discover -s sjck-graph/tests
Ran 212 tests — OK
```
Compilazione: `python3 -m py_compile sjck-graph/scripts/*.py sjck-graph/tests/*.py`, senza errori.

Dei 212, **73 vengono dai pezzi scelti**: `test_checks.py` 47 (SJCK),
`test_context.py` 11 (AUTO), `test_cost.py` 10 (AUTO), `test_prices.py` 5 (SJCK,
ridotto). I test già presenti su `main` (`test_tokens.py` compreso, con le sue
due prove sulla ripartizione del costo reale e sull'EUR) passano invariati.

Test scartati e perché:

| Test | Perché |
|---|---|
| `test_interfaces.py` (SJCK) | `interfaces.py` scartato |
| `test_precheck.py` (AUTO) | `precheck.py` scartato |
| `test_prices.py::test_defaults_and_override_change_cost`, `test_cache_multipliers`, `test_unknown_model_uses_default_and_no_prices_gives_none` (SJCK) | provano `tokens.load_prices`/`estimate_usd`, sostituiti da `config.py`; gli stessi fatti (default, moltiplicatori di cache, modello sconosciuto) sono coperti meglio da `test_cost.py`, che inoltre verifica che un modello ignoto **non** prenda un prezzo di default |
| `test_prices.py::test_real_cost_vs_estimated` (SJCK) | duplicato di `test_cost.py::test_real_cost_wins_and_is_split_with_the_price_table` + `test_estimated_cost_per_node_and_model_without_cost_state`, che verificano anche la ripartizione dal listino |
| `test_checks.py::TestMissingConfig::test_load_prices_not_empty` (SJCK) | provava il default interno dei prezzi di SJCK, che non esiste più |
| `test_install.py::test_copies_config` (SJCK) | `config/` non esiste più |

Adattamenti ai test portati (nomi e percorsi finali):

- `test_checks.py`: `TestConfig` e `TestCli` lavorano su `.sjck/config.json`
  (`{"validator": {...}}`) invece di `.sjck/validation.json`; `timeout` →
  `timeout_s`; aggiunta la classe base `Hermetic` che isola `HOME` e le variabili
  `SJCK_*`, **necessaria** perché `config.py` legge `~/.sjck/config.json` e
  l'ambiente (senza, la suite dipenderebbe dalla configurazione di chi la lancia);
  aggiunte le prove sui nuovi percorsi di configurazione (env che vince sul file,
  `effort`/`timeout_s` non validi → errore, `always_llm` che tiene il livello 2).
- `test_cost.py`: `cost_estimated` → `estimated`; `cost.by_node[nid]` →
  `cost.by_node[nid]["usd"]` nel report; l'asserzione sull'EUR del costo stimato
  è diventata un'asserzione sul costo per agente (decisione 4).
- `test_prices.py`: ribasato sul listino reale (`claude-opus-5-5`,
  `claude-sonnet-5-5`), isolamento di `HOME`, e tiene solo ciò che non è
  duplicato: `by_agent`, `by_node[].models` come dict per modello, `_mtotal`
  (forma vecchia, intera), override di progetto che arriva fino a `tokens.json`.
- `test_context.py`: l'asserzione sul testo di `ACTIONS["system"]` ora cerca
  `checks.py`.
- `test_install.py`: il test sulla copia della configurazione punta a
  `sjck-scripts/prices.json`.

**Un solo test è nuovo**: `test_prices.py::test_by_agent_splits_the_real_cost_too`.
Buco creato dalla fusione: `_costs` ripartisce il costo reale anche su `by_agent`
(non solo su `by_node`), e il test di SJCK che copriva il percorso reale è stato
scartato come duplicato; senza questo, la ripartizione per agente con `cost-state`
non sarebbe stata coperta da nessun test.

## 5. Cosa NON è stato verificato

- **Nessun run reale**: non è stato lanciato `claude -p` né una task di `evals/`.
  Il flusso dell'orchestratore (`SKILL.md`: scout saltati, prompt da
  `context.py prompt`, override di `model`/`effort` al lancio del validatore,
  `--base` preso dal log) è prosa per un agente: non è coperto da test automatici
  e non è stato eseguito end-to-end.
- **I risparmi**: le percentuali in `docs/context-diet.md` (`system` 31,6%,
  `file_read_in_card` 19,1%, scout T00 ~9% del run) vengono dalla misura di AUTO
  sul run di esempio e **non sono state rimisurate** dopo la fusione. Il risparmio
  del livello 1 (validatore LLM non lanciato) non è stato misurato.
- **I prezzi di `prices.json`** sono quelli di AUTO, presi così come sono: non
  sono stati confrontati con un listino esterno (nessuna rete dal codice).
- **La chiamata HTTP alla BCE** non è stata esercitata: i test girano con
  `SJCK_FX_OFFLINE=1`.
- **Installazione reale**: `install.sh` è verificato solo dal suo test con un
  tarball finto; `sjck update` / `claude plugin update` non sono stati eseguiti.
  Nota pre-esistente (non introdotta qui): `install.sh` non copia `sjck-graph/docs/`,
  quindi i rimandi a `docs/*.md` dalla skill si risolvono solo nel repo.
- **Il visualizzatore** (`scripts/viewer.html`) legge `cost.usd` e continua a
  funzionare, ma non mostra il flag `estimated` né il costo per agente: non è
  stato toccato (fuori dallo scope della fusione) e non è stato aperto.
- `console/` e `vscode/` non sono stati toccati né rilanciati; `evals/` non è
  stato modificato.
