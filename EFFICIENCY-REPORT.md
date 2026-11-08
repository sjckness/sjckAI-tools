# Efficienza in token di sjck-graph

Report della task `evals/efficiency-task.md`. Questa prima parte è solo
analisi: nessun file di codice è stato toccato per scriverla.

## Analisi

Metodo: lettura degli agenti, della skill di orchestrazione, degli hook e di
`tokens.py`. Ogni affermazione ha l'evidenza in `percorso:riga`. Le categorie
di contesto citate sono quelle che `tokens.py` già stima per nodo
(`sjck-graph/scripts/tokens.py:87`), assegnate dal tool e dal file letto
(`sjck-graph/scripts/tokens.py:130`) e ripartite su ogni turno in proporzione
al contesto presente (`sjck-graph/scripts/tokens.py:331-334`). La quota non
spiegata dai blocchi visibili finisce in `system`
(`sjck-graph/scripts/tokens.py:335`): system prompt, definizioni dei tool,
prompt dell'agente e CLAUDE.md.

### 1. Il contratto funziona: il grosso dello spreco non è l'orchestratore

L'orchestratore legge solo stato e out JSON
(`sjck-graph/skills/sjck-orchestration/SKILL.md:7`, regola ferrea in
`sjck-graph/skills/sjck-orchestration/SKILL.md:177`) e il risparmio è già
misurato come insight `contract`
(`sjck-graph/scripts/tokens.py:607`). Il costo si concentra quindi nei
subagenti, e lì il moltiplicatore è il numero di lanci: un validator per ogni
nodo (`sjck-graph/skills/sjck-orchestration/SKILL.md:129`), più fino a due
retry (`sjck-graph/skills/sjck-orchestration/SKILL.md:131`).

### 2. `system` è la categoria più pesante per lancio, e in parte è evitabile

`omitClaudeMd: true` è presente solo su due agenti su sei
(`sjck-graph/agents/sjck-implementer.md:8`,
`sjck-graph/agents/sjck-scout.md:8`). Validator
(`sjck-graph/agents/sjck-validator.md:7`), reviewer
(`sjck-graph/agents/sjck-reviewer.md:6`), planner
(`sjck-graph/agents/sjck-planner.md:6`) e critic
(`sjck-graph/agents/sjck-critic.md:7`) non lo hanno: CLAUDE.md entra nel loro
contesto. Poiché il validator parte dopo ogni nodo
(`sjck-graph/skills/sjck-orchestration/SKILL.md:129`), CLAUDE.md viene pagato
una volta per nodo e per retry, in categoria `system`. Il critic non legge
nemmeno codice (`sjck-graph/agents/sjck-critic.md:10`), quindi per lui è puro
sovraccarico.

Allo stesso blocco `system` appartiene il boilerplate sui findings, duplicato
alla lettera in tre agenti (`sjck-graph/agents/sjck-implementer.md:14`,
`sjck-graph/agents/sjck-validator.md:35`,
`sjck-graph/agents/sjck-reviewer.md:13`).

### 3. I controlli deterministici si pagano due volte

L'implementer esegue da sé i comandi dei criteri di accettazione
(`sjck-graph/agents/sjck-implementer.md:24`). Subito dopo, il validator LLM
li riesegue (`sjck-graph/agents/sjck-validator.md:21`) con `model: sonnet`,
`effort: high`, `maxTurns: 40` (`sjck-graph/agents/sjck-validator.md:5`) e un
contesto che comprende card, out JSON e `git diff`
(`sjck-graph/agents/sjck-validator.md:12`). Il kit non ha nessuna via per
decidere senza LLM: `pass`/`fail` esistono solo dentro il `.val.json`
(`sjck-graph/agents/sjck-validator.md:27`) e il loop lo pretende
(`sjck-graph/skills/sjck-orchestration/SKILL.md:156`). Quando un comando di
accettazione esce diverso da zero l'esito non è ambiguo: il lancio del
validator è interamente spreco. Categorie colpite: `system` + `tool_output`.
Questo è il punto P3.

Il modello del validator non è configurabile per nodo: lo stato ha `model` e
`effort` solo sul nodo (`sjck-graph/scripts/state_schema.py:109`) e
l'orchestratore passa l'override al nodo, non al suo validator
(`sjck-graph/skills/sjck-orchestration/SKILL.md:119`,
`sjck-graph/skills/sjck-orchestration/reference/scripts.md:45`).

### 4. Le interfacce non vengono riusate tra run

Lo scout riscrive `.sjck/interfaces/<nome>.md` ogni volta
(`sjck-graph/agents/sjck-scout.md:11`) e nulla nel kit confronta un hash del
file sorgente per saltare l'estrazione: il planner crea un nodo scout ogni
volta che più nodi usano la stessa API
(`sjck-graph/agents/sjck-planner.md:21`). Il costo è tracciato nella
categoria `interfaces` (`sjck-graph/scripts/tokens.py:141`), quello evitato
nella categoria `file_read_outside_card`
(`sjck-graph/scripts/tokens.py:148`), già usata dall'insight `card`
(`sjck-graph/scripts/tokens.py:573`). È il candidato principale di P2 insieme
al punto 2.

### 5. Thinking e retry: contesto che si rilegge a ogni turno

`effort: high` su validator, reviewer, planner e critic
(`sjck-graph/agents/sjck-validator.md:6`,
`sjck-graph/agents/sjck-critic.md:6`) produce thinking che resta nel contesto
e viene riletto a ogni turno successivo; `tokens.py` lo riconosce già come
spreco sopra il 25% dell'input (`sjck-graph/scripts/tokens.py:585`). I retry
hanno lo stesso effetto su scala di nodo e sono già quantificati
dall'insight `waste` (`sjck-graph/scripts/tokens.py:593`). Nota positiva: la
sezione "Correzioni richieste" è l'ultima della card
(`sjck-graph/skills/sjck-orchestration/SKILL.md:96`), quindi appendervi i
findings non invalida il prefisso in prompt cache; lo stesso vale per la riga
`script:` messa in testa a ogni prompt
(`sjck-graph/skills/sjck-orchestration/reference/scripts.md:7`).

### 6. Il costo in denaro non è calcolabile oggi

`tokens.py` somma già input, output, cache read e cache write per modello
(`sjck-graph/scripts/tokens.py:50`, `sjck-graph/scripts/tokens.py:323`), ma
`PRICE_WEIGHT` contiene solo rapporti di prezzo, non prezzi
(`sjck-graph/scripts/tokens.py:430`). Il campo `cost` esiste solo se un
transcript porta un evento `cost-state`
(`sjck-graph/scripts/tokens.py:517`); altrimenti `build` ricopia il valore
del run precedente (`sjck-graph/scripts/tokens.py:536`) e nessun campo dice
che il dato è vecchio o stimato. Non esiste file di configurazione dei
prezzi, quindi non c'è modo di cambiarli senza toccare il codice. Mancano
quindi, per P1: prezzi per modello configurabili, moltiplicatori di cache
read/write distinti dall'input, e il flag `estimated: true` quando il costo
non viene da `cost-state`. I conteggi necessari ci sono già tutti:
`by_node[].types` e `by_model` (`sjck-graph/scripts/tokens.py:509`).

### 7. Attribuzione: token che nessuno paga

Con più di un nodo `running` senza `agent_id` i token finiscono in
`unattributed`: è il valore di ritorno di `node_for_agent`
(`sjck-graph/scripts/tokens.py:503`; la `def` è a
`sjck-graph/scripts/tokens.py:493`), e proprio il lancio in
parallelo è la norma del loop
(`sjck-graph/skills/sjck-orchestration/SKILL.md:118`). Ogni costo per nodo
calcolato su quelle quote (`sjck-graph/scripts/tokens.py:521`) è sottostimato
per i nodi reali e concentrato su un nodo fittizio: P1 deve dichiararlo come
limite noto.

## Interventi P1-P3

Questa parte è la consegna: cosa è stato cambiato, il comando esatto con cui si
verifica (eseguiti tutti, da questa radice di repo) e i limiti noti. Nessuna
cifra di risparmio: in questo run **non è stata misurata** nessuna riduzione. I
numeri di `docs/context-diet.md` sono stime dichiarate come tali.

I riferimenti `percorso:riga` della sezione `## Analisi` sono una fotografia
presa prima degli interventi: P1 ha modificato `tokens.py`, quindi alcune righe
citate lì ora contengono altro codice (per esempio `PRICE_WEIGHT`, rimosso da
P1). Le righe esistono tutte, ma vanno lette come la diagnosi di partenza.

### P1 — costo in denaro per nodo, agente e run

Cosa è cambiato:
- `sjck-graph/scripts/tokens.py`: `load_prices`, `model_price`, `estimate_usd`,
  `_costs`; `cost.usd`/`estimated` nel run, `by_node[].cost_usd`, nuovo
  `by_agent`; `PRICE_WEIGHT` sostituito dai prezzi configurabili;
  `by_node[].models` diventa un dict per modello.
- `sjck-graph/config/prices.json` (default versionati, override
  `.sjck/prices.json`), `sjck-graph/tests/test_prices.py`, `docs/costs.md`.
- Cablaggio: `sjck-graph/skills/sjck-orchestration/SKILL.md`, Step 3 punto 3,
  dove la skill già esegue `watchdog.py usage`.

Come si verifica:

```sh
python3 -c "import sys; sys.path.insert(0, 'sjck-graph/scripts'); import tokens; p = tokens.load_prices('.'); print(tokens.estimate_usd(p, 'claude-opus-4-5', {'input': 1000000, 'output': 0, 'cache_read': 0, 'cache_creation': 0}))"
python3 -m unittest sjck-graph.tests.test_prices
```

Esito ottenuto: `5.0` (5 USD per 1M token di input su opus, dal prezzo
configurato) e `Ran 8 tests ... OK`.

Limiti noti:
- I costi `estimated: true` dipendono dai prezzi configurati: i default
  invecchiano, un modello sconosciuto cade sul prezzo `default`.
- Con `cost-state` il costo per nodo/agente è una **ripartizione** del totale
  reale pesata sui prezzi, non un costo misurato; nodi con più modelli sono
  approssimati.
- **F002** (`sjck-graph/scripts/tokens.py:378`): `eur_per_usd()` fa una
  richiesta HTTP alla BCE dentro il `refresh` dell'hook, mentre i vincoli della
  task vietano le chiamate di rete. È preesistente ed è stata **lasciata
  invariata per scelta** in fase di piano: il percorso del costo USD è offline e
  non la chiama (`sjck-graph/scripts/tokens.py:533`, `_costs`). Resta una tensione
  dichiarata, non risolta.
- **F005** (`sjck-graph/scripts/tokens.py:644`): conseguenza della stessa
  scelta — i costi stimati sono solo in USD, senza `cost_eur`; l'EUR esiste solo
  sul percorso `cost-state`.
- **F001** (`sjck-graph/scripts/tokens.py:580`): `build()` riparsa tutti i
  transcript a ogni hook, con timeout 15 s. P1 non aggiunge parse (è
  O(token già aggregati)), ma su un run lungo le misure di costo possono
  perdersi in silenzio.
- Attribuzione: i token dei nodi lanciati in parallelo senza `agent_id`
  finiscono in `unattributed` (punto 7 dell'analisi), quindi i costi per nodo
  che ne derivano sono sottostimati.
- **F010** (`sjck-graph/scripts/watchdog.py`): `watchdog.py usage` sottostima i
  tool call (su T03: 5 contro 10 reali; su T02: 2 contro 11). Rilevante proprio
  qui: i budget per nodo e `metrics.tool_calls` non sono una misura affidabile.
- Il `.sjck/tokens.json` vivo di questo run è stato scritto dalla `tokens.py`
  **installata** (vecchia): non ha `by_agent` né `by_node[].cost_usd`, e ha
  `models` a interi. Il percorso dell'hook esercita il plugin installato, non il
  codice del repo, finché il plugin non viene aggiornato; fino ad allora i
  `cost_usd` citati in `SKILL.md` non sono disponibili su questo run.
- Forma di `tokens.json` cambiata (`by_node[].models` è un dict): nessun
  consumatore noto lo legge, i file vecchi restano leggibili.

### P2 — dieta del contesto: riuso delle interfacce, card e stato selettivi

Cosa è cambiato:
- `sjck-graph/scripts/interfaces.py` (nuovo): `register|check|invalidate <nome>
  [file...]` con hash sha256 in `.sjck/interfaces/.hashes.json`; exit 0 =
  `fresh`.
- `sjck-graph/scripts/cards.py`: `select_sections`, `select_state`,
  `build_prompt`; `sjck-graph/agents/sjck-scout.md` (riporta `sources`);
  `sjck-graph/tests/test_interfaces.py`; `docs/context-diet.md`.
- Cablaggio: `SKILL.md` Step 0 (ordine del prompt), Step 3 punto 2
  (`interfaces.py check` **prima** di lanciare uno scout: `fresh` → lo scout non
  parte), punto 3 (`interfaces.py register` **dopo**, con i `sources` dell'out
  JSON) e punto 4 (card ridotta e fetta di stato per il validator).

Come si verifica:

```sh
python3 sjck-graph/scripts/interfaces.py register state sjck-graph/scripts/state_schema.py && python3 sjck-graph/scripts/interfaces.py check state
python3 -m unittest sjck-graph.tests.test_interfaces
```

Esito ottenuto: `fresh` con exit 0 (prima della `register` la stessa `check`
dava `stale`, exit 1 → lo scout sarebbe partito) e `Ran 8 tests ... OK`.

Limiti noti:
- Il risparmio è **stimato**, non misurato: dipende dal fatto che il repo abbia
  interfacce stabili tra run. Alla prima esecuzione tutto è `stale`.
- Lo scout non ha Bash: `check`/`register` li esegue l'orchestratore. Se
  l'orchestratore salta quei due comandi il riuso non si attiva e il risparmio è
  zero; per lo stesso motivo `select_sections`/`select_state`/`build_prompt`
  valgono solo se la skill li usa.
- L'invalidazione è per hash dei file dichiarati in `sources`: se
  un'interfaccia dipende da un file non registrato, un `fresh` può essere falso.
- `build_prompt` non riduce i token: li sposta su cache read.
- `omitClaudeMd` sugli agenti è stato completato da P3, non da P2.

### P3 — validazione a due livelli: prima i comandi, poi (se serve) l'LLM

Cosa è cambiato:
- `sjck-graph/scripts/checks.py` (nuovo): esegue i criteri
  `` `comando` `` → esito della card; `decide()` condivisa; `green` (comandi già
  verdi, da non rilanciare) e `residual` (i soli criteri da giudicare) salvati in
  `.sjck/out/<ID>.l1.json`; exit 0 `pass`, 1 `fail`, 2 `ambiguous`, 3 config non
  valida.
- `sjck-graph/config/validation.json` (modello del validatore, override
  `.sjck/validation.json`), `sjck-graph/agents/sjck-validator.md` (contratto
  `green`/`residual`), `omitClaudeMd: true` su validator, reviewer, planner,
  critic; `sjck-graph/tests/test_checks.py`, `sjck-graph/tests/test_agents.py`,
  `docs/validation.md`, `.sjck/interfaces/cards.md`.
- Cablaggio: `SKILL.md` Step 3 punto 4 (`checks.py run` prima del validatore,
  ramo su `action`: `done`/`retry`/`llm`, override del modello) e la regola
  ferrea su `validated`.
- `sjck-graph/agents/sjck-planner.md`: formato `comando -> esito` e, poiché con
  `omitClaudeMd` il planner non vede più CLAUDE.md, la riga che gli dice da dove
  ricavare i comandi di test/build del progetto (F009, regressione introdotta da
  questo run e chiusa qui).

Come si verifica:

```sh
python3 sjck-graph/scripts/checks.py run T05 --cwd "$PWD"; echo "exit=$?"
python3 -m unittest sjck-graph.tests.test_checks
```

Esito ottenuto: JSON con `outcome: ambiguous`, un criterio in `green`
(`python3 -m unittest discover -s sjck-graph/tests`, eseguito e verde), sei
criteri in `residual`, `action: llm`, `model: sonnet`, `exit=2`; e
`Ran 30 tests ... OK`.

Limiti noti:
- **Il risparmio di P3 non è misurato su questo run.** Le card di questo run
  sono scritte in prosa: `checks.py run` su T02, T03 e T05 restituisce
  `ambiguous`, quindi il validatore LLM sarebbe partito comunque — in forma
  ridotta (senza rieseguire i comandi già verdi), non saltato. La direttiva
  `comando -> esito` è fissata in `.sjck/interfaces/cards.md` e nelle istruzioni
  del planner e vale dai run futuri.
- Il livello 1 non assolve mai ciò che non ha controllato: se resta prosa
  l'esito è `ambiguous`. Il guadagno è il **non rieseguire** i comandi, non il
  saltare il validatore.
- `checks.py` esegue i comandi della card: una card può far girare comandi
  arbitrari, come già faceva l'implementer.
- Exit 3 (config non valida) va segnalato all'utente: non è un `fail` del nodo e
  non deve sbloccarlo.
- **Scope-check (F016).** Sul ramo `done` il livello 1 chiudeva il nodo
  `validated` senza guardare il diff: il controllo di scope che prima faceva il
  validatore LLM era perso, quindi un nodo poteva scrivere fuori dai suoi file
  restando verde. Ripristinato in `checks.py`: `git diff --name-only <base>` più
  i file non tracciati contro `## Puoi modificare`; se esce dallo scope l'esito
  degrada a `ambiguous` (mai `fail`) e parte il livello 2. Anche lo scope non
  verificabile (manca la sezione, non è un repo git, base inesistente) dà
  `ambiguous`. Limite: senza `--base <sha>` il confronto è con HEAD e i commit
  fatti dal nodo non si vedono, quindi l'orchestratore deve passare il commit di
  partenza (`SKILL.md`). Il controllo di regressioni (stub, TODO, test
  disattivati) resta solo al livello 2, quindi non è coperto sul ramo `done`.
- **F008** (`sjck-graph/tests/test_install.py`): ogni `unittest discover` di
  questo run ha toccato l'installazione reale della macchina (stampa
  `VS Code extension (code): ok`). Preesistente e fuori rubrica.

## Altri sprechi

Trovati ma **non** implementati (fuori dalla rubrica P1-P3), salvo il punto 4,
chiuso da P1.

1. **`build` rilegge tutti i transcript a ogni hook.** `tokens.py --hook` gira
   su ogni `Stop` e `SubagentStop`
   (`sjck-graph/hooks/hooks.json:54`, `sjck-graph/hooks/hooks.json:65`) e
   `build` riparte da zero su tutte le fonti registrate
   (`sjck-graph/scripts/tokens.py:580`). Il costo cresce col quadrato della
   lunghezza del run; col timeout di 15 s
   (`sjck-graph/hooks/hooks.json:55`) un run lungo perde silenziosamente le
   misure. Rimedio: cache per fonte con `mtime`/offset.
2. **Chiamata di rete dentro un hook.** `eur_per_usd` interroga la BCE
   (`sjck-graph/scripts/tokens.py:378`,
   `sjck-graph/scripts/tokens.py:371`) durante il `refresh` innescato
   dall'hook, mentre i vincoli della task vietano le chiamate di rete
   (`evals/efficiency-task.md:51`). È mitigata (cache giornaliera, timeout
   3 s, back-off di un'ora) ma resta un I/O di rete sul percorso caldo.
3. **Il reviewer legge `git diff` intero con opus.** Nessun limite di
   dimensione (`sjck-graph/agents/sjck-reviewer.md:8`,
   `sjck-graph/agents/sjck-reviewer.md:5`): su un DAG largo è il singolo
   contesto più grande del run. Rimedio: diff per file o solo i file toccati
   da più nodi.
4. **Forma incoerente di `models`: chiuso da P1.** `by_node[].models` ora è un
   dict per modello, come in `parse_transcript` (vedi sezione P1 e CHANGELOG).
5. **`graph_view.py` rigenerato a ogni Write/Edit**
   (`sjck-graph/hooks/hooks.json:21`) e di nuovo dentro `refresh`, ma solo se il
   viewer esiste già: il render è dietro la guardia
   `if os.path.exists(".sjck/view.html")` (`sjck-graph/scripts/tokens.py:752`).
   Nessun token, ma latenza su ogni tool call che scrive.
6. **`validate` ignora i campi sconosciuti**
   (`sjck-graph/scripts/state_schema.py:168`): campi nuovi (per esempio un
   `validator_model`) non verrebbero validati né segnalati.
