# Efficienza in token del kit sjck-graph

Analisi e interventi sul costo in token di un run, senza ridurne l'affidabilità.
Baseline: commit `58bf6a1`, 138 test verdi
(`python3 -m unittest discover -s sjck-graph/tests`).

Nota sui riferimenti: i `percorso:riga` della sezione "Analisi" sono al commit
di partenza `58bf6a1` (`git show 58bf6a1:<percorso>`), perché descrivono il
codice prima degli interventi. I riferimenti nelle sezioni P1-P3 e "Altri
sprechi" sono allo stato attuale del branch.

Nota sulla misura: i numeri di run usati qui sono quelli già registrati in
`examples/demo/.sjck/tokens.json` (unico run completo con dati di categoria
presente nel repo). Non ho lanciato run di sjck: la misura esterna la fa
`evals/sum_usage.py`.

## Analisi

### Da dove viene il costo di un run

Ripartizione per categoria del run demo (`examples/demo/.sjck/tokens.json`,
7 nodi, 418k token di input+cache):

| categoria | token | quota |
| :- | -: | -: |
| `system` | 132k | 31,6% |
| `file_read_in_card` | 80k | 19,1% |
| `tool_output` | 74k | 17,7% |
| `agent_messages` | 55k | 13,2% |
| `card` | 28k | 6,7% |
| `file_read_outside_card` | 28k | 6,7% |
| `interfaces` | 21k | 5,0% |

`system` è il costo d'avvio: prompt di sistema, definizione dell'agente,
definizioni dei tool, reminder. Si paga **una volta per subagente** e in questo
run vale 15-21k per nodo (`examples/demo/.sjck/tokens.json:5-11`). Non si
riduce ottimizzando le card: si riduce solo **lanciando meno subagenti**.
`file_read_in_card` è la seconda voce, e si paga di nuovo ogni volta che un
agente nuovo rilegge gli stessi file.

### A1 — Il validatore LLM parte sempre, anche quando la risposta è deterministica

`sjck-graph/skills/sjck-orchestration/SKILL.md:129` lancia `sjck-validator`
dopo OGNI nodo completato; in modalità S lo lancia anche quando il lavoro lo ha
fatto l'orchestratore (`sjck-graph/skills/sjck-orchestration/SKILL.md:52`). Il
validatore è `sonnet`/`effort: high`/`maxTurns: 40`
(`sjck-graph/agents/sjck-validator.md:5-7`): un subagente nuovo, quindi un
`system` intero (15-21k nel run demo) più le letture di card, out JSON e diff
(`sjck-graph/agents/sjck-validator.md:12-15`).

Il punto è che il suo primo lavoro è **rieseguire i comandi dei criteri di
accettazione** (`sjck-graph/agents/sjck-validator.md:21-22`), comandi che
l'implementer ha già eseguito prima di chiudere
(`sjck-graph/agents/sjck-implementer.md:24`). Quando quei comandi passano o
falliscono in modo netto, il verdetto non richiede un LLM: è un exit code.
Stessa cosa per il controllo 1 del validatore, "i file modificati sono solo
quelli permessi dalla card?" (`sjck-graph/agents/sjck-validator.md:20`), che è
un confronto fra `git diff --name-only` e la sezione "Puoi modificare".

I dati per farlo sono già leggibili a macchina ma non vengono mai eseguiti:
`cards.py` sa estrarre gli item di una sezione
(`sjck-graph/scripts/cards.py:35-46`), i path di una sezione
(`sjck-graph/scripts/cards.py:49-55`) e conta i criteri
(`sjck-graph/scripts/cards.py:58`) — li conta soltanto, per il plan score
(`sjck-graph/scripts/plan_score.py:162`).

Sul percorso di retry il conto raddoppia: `fail` con `attempts < 2` riprende
l'implementer e poi rilancia il validatore
(`sjck-graph/skills/sjck-orchestration/SKILL.md:130-133`), quindi fino a 3
validatori per nodo. Nel run demo, con le stime di
`sjck-graph/skills/sjck-planning/SKILL.md:56` (validator ≈ 15-30k), i 7 nodi
pagano 105-210k di sola validazione: il 25-50% del run.

### A2 — Le interfacce dello scout si rigenerano a ogni run

Lo scout riscrive `.sjck/interfaces/<nome>.md` ogni volta
(`sjck-graph/agents/sjck-scout.md:10-13`), e il suo scopo è proprio evitare che
gli altri esplorino (`sjck-graph/agents/sjck-scout.md:3`). Il riuso tra run è
scritto come buona intenzione — "interfacce e card di run archiviati ancora
valide (file non cambiati) si riusano"
(`sjck-graph/skills/sjck-planning/SKILL.md:82-83`) — ma non c'è niente che
renda verificabile "file non cambiati": nessun hash dei file sorgente viene
registrato accanto all'interfaccia. L'unico sha1 del kit è quello del watchdog,
che serve a rilevare il drift di un file durante il run
(`sjck-graph/scripts/watchdog.py:144-149`), non a datare un'interfaccia.

Intanto l'archiviazione sposta via tutto a ogni nuovo run
(`sjck-graph/skills/sjck-orchestration/SKILL.md:41-43`): `.sjck/interfaces/`
non è nemmeno nell'elenco di ciò che viene archiviato, quindi il materiale
riusabile resta sul disco ma senza un modo di sapere se è ancora valido — e il
nodo scout viene rifatto. Costo: un `system` intero (15-21k) più le letture che
lo scout fa per riscrivere lo stesso file (`file_read_in_card`, 19,1% del run).

### A3 — Nessun costo in valuta per nodo, e i prezzi non esistono

`tokens.py` calcola il costo solo se il transcript contiene l'evento
`cost-state` (`sjck-graph/scripts/tokens.py:516-529`); se manca, `cost` resta
quello del calcolo precedente o `None`
(`sjck-graph/scripts/tokens.py:536-537`), e `cost_usd` per nodo non viene
scritto affatto. `cost-state` è un totale **di sessione**, quindi: niente run
senza sessione chiusa, niente costo per modello che il kit possa controllare,
e la ripartizione per nodo usa rapporti di prezzo cablati nel codice
(`sjck-graph/scripts/tokens.py:428-434`), uguali per tutti i modelli e non
modificabili.

Non esiste alcuna tabella prezzi: la spec la prevedeva
(`docs/specs/v0.4-token-analytics.md:45-48`, sezione B mai implementata) e la
skill di pianificazione già si appoggia a un file che non c'è — "Mai cifre in
valuta se non esiste `prices.json`"
(`sjck-graph/skills/sjck-planning/SKILL.md:57`). Risultato: il kit misura i
token ma non sa dire quali 10k token costano più di altri 100k, che è
l'informazione che serve per scegliere il modello di un nodo.

### A4 — Le categorie si misurano ma non cambiano il comportamento del run

`tokens.py` stima sette categorie di contesto
(`sjck-graph/scripts/tokens.py:87-88`) e produce insight precisi: letture fuori
card (`sjck-graph/scripts/tokens.py:570-575`), cache hit bassa
(`sjck-graph/scripts/tokens.py:576-581`), thinking riletto a ogni turno
(`sjck-graph/scripts/tokens.py:582-587`), opus su nodi piccoli
(`sjck-graph/scripts/tokens.py:596-601`). Nessuno di questi file viene però
riletto durante un run: in tutte le skill e in tutti gli agenti l'unico
riferimento a `tokens.json` è la stima del planner sui run archiviati
(`sjck-graph/skills/sjck-planning/SKILL.md:52`). Il kit si auto-diagnostica e
poi ignora la diagnosi.

### A5 — Card intera a ogni consumatore, e nessuna regola sull'ordine del prompt

La card ha sei sezioni (`sjck-graph/skills/sjck-orchestration/SKILL.md:88-97`),
tra cui "Fuori scope" e "Correzioni richieste". Il validatore la legge intera
(`sjck-graph/agents/sjck-validator.md:13`) pur non avendo bisogno della sezione
"Leggi", che è l'elenco di file per l'implementer; nel run demo `card` vale
28k (6,7%) e viene pagata due o tre volte per nodo (implementer, validatore,
eventuale retry).

Sul lato cache: l'insight a `sjck-graph/scripts/tokens.py:576-581` dice
"keep the card and stable instructions first", ma nessuna regola operativa lo
impone. Le istruzioni di lancio parlano solo di `model`/`effort`/`budget`
(`sjck-graph/skills/sjck-orchestration/SKILL.md:122-123`,
`sjck-graph/skills/sjck-orchestration/reference/scripts.md:44-49`): l'ordine
del prompt è lasciato al caso, quindi la parte volatile (attempt, correzioni)
può finire in testa e invalidare il prefisso cacheato.

### A6 — Il modello del validatore è fisso

`model: sonnet`, `effort: high` sono nel frontmatter
(`sjck-graph/agents/sjck-validator.md:5-6`) e la tabella del planner li ripete
come unica scelta possibile (`sjck-graph/agents/sjck-planner.md:38`,
`sjck-graph/skills/sjck-orchestration/reference/scripts.md:33-34`).
L'orchestratore passa override di modello ed effort solo ai nodi del grafo
(`sjck-graph/skills/sjck-orchestration/SKILL.md:122`): per il validatore non
c'è alcun punto di configurazione, quindi anche una verifica meccanica (un
comando che passa, un diff di 3 righe) paga sonnet/high.

### Cosa seguirà da questa analisi

Le due categorie più pesanti sono `system` (31,6%, cioè il numero di subagenti
lanciati) e `file_read_in_card` (19,1%, cioè le letture ripetute dagli agenti
nuovi). A1+A6 riducono la prima, A2 riduce entrambe, A5 riduce `card` e
migliora la cache. A3 e A4 non riducono token da soli: rendono misurabile in
dollari dove stanno, che è il presupposto per decidere il modello per nodo.

---

## P1 — Costo in dollari per nodo, agente e run

### Cosa è cambiato

| file | cosa |
| :- | :- |
| `sjck-graph/scripts/prices.json` (nuovo) | listino distribuito: USD per milione per modello (`input`, `output`), `cache_multipliers` (cache read 0,1 · cache write 1,25 rispetto all'input), `updated`, note |
| `sjck-graph/scripts/config.py` (nuovo) | carica e fonde i listini, normalizza i nomi dei modelli, calcola il costo di un gruppo di token; carica anche la configurazione del kit (serve a P3). CLI `config.py prices [--model N]` / `config.py validator` |
| `sjck-graph/scripts/tokens.py` | `build()` calcola il costo per nodo e per modello; `cost` in `tokens.json` con `estimated`, `source`, `by_model`, `unpriced_models`; `analyze()` mette `cost` e, su ogni insight, `cost_usd`/`saving_usd` in `token-report.json`; la CLI marca la stima |
| `sjck-graph/docs/cost.md` (nuovo) | documentazione d'uso e limiti |
| `sjck-graph/tests/test_cost.py` (nuovo) | 10 test |

Scelte:

- **Prezzi fuori dal codice, con override a quattro livelli** (ultimo vince, fusione
  campo per campo): `scripts/prices.json` → `~/.sjck/prices.json` →
  `<run>/.sjck/prices.json` → `$SJCK_PRICES`. Un modello messo a `null` viene
  rimosso: per lui si mostrano solo i token. Nessun prezzo viene inventato: un
  modello fuori listino finisce in `cost.unpriced_models` e i suoi nodi restano
  senza `cost_usd` (spec `docs/specs/v0.4-token-analytics.md:48`).
- **Cache come moltiplicatori dell'input** (0,1 e 1,25), con la possibilità di un
  prezzo esplicito `cache_read`/`cache_write` per modello, che vince: diversi
  modelli recenti hanno un cache read che non è 0,1× l'input.
- **Costo reale se c'è, stima altrimenti.** Con l'evento `cost-state` il totale è
  quello di Claude Code (`estimated: false`) e la ripartizione per nodo usa il
  costo da listino quando il listino copre tutti i nodi (prima erano rapporti
  cablati); la stima resta accanto come `cost.estimate_usd`, così si vede subito
  se il listino è vecchio. Senza `cost-state` il costo è calcolato token per
  token e marcato `estimated: true` sia sul totale sia su ogni nodo
  (`cost_estimated`).

### Come si verifica

```bash
# test del punto (10) e suite completa (176)
python3 -m unittest discover -s sjck-graph/tests -p 'test_cost.py'
python3 -m unittest discover -s sjck-graph/tests

# listino effettivo e prezzo di un modello
python3 sjck-graph/scripts/config.py prices --model claude-opus-5-5
# override senza toccare il codice
echo '{"models": {"claude-opus-5-5": {"input": 3.2}}}' > /tmp/listino.json
SJCK_PRICES=/tmp/listino.json python3 sjck-graph/scripts/config.py prices --model claude-opus-5-5
```

Atteso dal primo comando: `input 4.0`, `output 20.0`, `cache_read 0.2`,
`cache_creation 5.0` (= 4,0 × 1,25); dal secondo: `input 3.2`, `cache_creation
4.0`, il resto invariato.

### Limiti noti

- La stima vale quanto il listino: `cost.prices_updated` dice di quando è.
- Cache a 1 ora, scaglioni per prompt lunghi (alcuni modelli cambiano prezzo
  oltre 100k token), fast mode e batch non sono modellati.
- Il costo per nodo eredita i limiti dell'attribuzione dei token: subagenti non
  collegabili restano in `unattributed`, e l'output ricostruito dei subagenti ha
  un errore misurato di ~6%.
- Con `cost-state` il totale è reale ma la ripartizione per nodo resta una
  stima: `cost-state` è un totale di sessione.
- Bedrock/Vertex: il nome del modello viene riconosciuto senza il prefisso del
  provider, il prezzo no (listini diversi, da mettere in un override).

---

## P2 — Dieta del contesto

Categorie più pesanti nel run misurato (`context.py top --cwd examples/demo`):
**`system` 31,6%** e **`file_read_in_card` 19,1%**. `system` è l'avvio a freddo
di un subagente (15-21k per nodo): non si riduce con card migliori, si riduce
lanciando meno subagenti. `file_read_in_card` si ripaga a ogni agente nuovo che
rilegge gli stessi file.

### Cosa è cambiato

| file | cosa |
| :- | :- |
| `sjck-graph/scripts/context.py` (nuovo) | `top` (categorie più pesanti + intervento), `interfaces record/check/reuse/skip` (riuso per hash), `card --role` (sezioni per ruolo), `state --id` (goal + nodo + deps), `prompt` (parte stabile in testa) |
| `sjck-graph/skills/sjck-orchestration/SKILL.md` | Step 3: i nodi scout riusabili diventano `validated` senza lancio; il prompt lo costruisce `context.py prompt`; a nodo chiuso si registrano gli hash delle interfacce; Step 0: `interfaces/` non si archivia (è la cache tra run) |
| `sjck-graph/skills/sjck-orchestration/reference/scripts.md` | riferimento dei comandi |
| `sjck-graph/agents/sjck-planner.md` | la card di uno scout deve elencare l'interfaccia in "Puoi modificare" e i sorgenti in "Leggi", altrimenti il riuso non è verificabile |
| `sjck-graph/skills/sjck-planning/SKILL.md` | il riuso si verifica (`interfaces reuse`) invece di supporlo; il costo in valuta viene dal listino |
| `sjck-graph/docs/context-diet.md` (nuovo) | documentazione d'uso e limiti |
| `sjck-graph/tests/test_context.py` (nuovo) | 11 test |

### Le tre riduzioni, categoria colpita e risparmio atteso

1. **Interfacce riusate per hash** → `system` + `file_read_in_card`.
   Quando lo scout scrive `.sjck/interfaces/<nome>.md`, l'orchestratore registra
   lo sha1 dei file della sezione "Leggi" in `interfaces/<nome>.json` (le
   cartelle si espandono nei loro file). Al run successivo
   `context.py interfaces skip` elenca i nodi scout le cui interfacce sono
   ancora `fresh` e quel nodo non parte (`reuse` ripesca anche da
   `.sjck/archive/*/interfaces/`).
   *Risparmio atteso*: un nodo scout intero. Nel run misurato T00 vale 38k token
   su 418k, **circa il 9% del run**, di cui 16k di `system` e 11k di
   `file_read_in_card`. Vale dal secondo run in poi e solo se i sorgenti non
   sono cambiati; se cambiano, costo zero e il nodo si rifà.
2. **Card per ruolo** → `card`.
   Il validatore riceve Obiettivo, Puoi modificare, Criteri, Fuori scope: non la
   sezione "Leggi" (elenco di file per l'implementer) e non "Correzioni
   richieste" al primo tentativo; il critico solo Obiettivo e Criteri.
   *Risparmio atteso*: `card` è 6,7% del run e si paga 2-3 volte per nodo; il
   taglio è il peso delle sezioni non pertinenti, nella card di esempio il 22%
   (273 → 213 caratteri), tipicamente 30-50% su card reali con una sezione
   "Leggi" lunga. Ordine di grandezza **1-2% del run**, a rischio zero.
3. **Prompt con la parte stabile in testa** → `input`/`cache_creation` via
   prompt cache. `context.py prompt` emette prima ciò che non cambia tra nodi
   (ruolo, percorso degli script, contratto), poi `--- nodo ---` e la parte
   volatile (ID, budget, tentativo, card ridotta).
   *Risparmio atteso*: il prefisso stabile è di 2-400 token, quindi il guadagno
   diretto è **sotto l'1%**; il valore vero è evitare il caso contrario (parte
   volatile in testa che invalida la cache per tutti i turni del nodo), che è
   l'insight `cache` già misurato in `token-report.json`.

Totale atteso sul run misurato: **~10-11%**, quasi tutto dal punto 1 e solo dal
secondo run in poi.

### Come si verifica

```bash
python3 -m unittest discover -s sjck-graph/tests -p 'test_context.py'

# le due categorie più pesanti del run di esempio
python3 sjck-graph/scripts/context.py top --cwd examples/demo
# card intera vs card del validatore
python3 sjck-graph/scripts/context.py card --id T01 --role validator --cwd <run>
```

Atteso: `top` elenca `system` (31,6%) e `file_read_in_card` (19,1%) con
l'intervento; la card del validatore non contiene `## Leggi`.

### Limiti noti

- Le categorie sono stime (`categories_estimated: true`): ordinano gli
  interventi, non certificano il risparmio. La misura esterna resta
  `evals/sum_usage.py`.
- `interfaces skip` si fida della sezione "Leggi": uno scout che legge file non
  elencati può essere saltato a torto (per questo il planner ora deve elencarli).
- Hash sul contenuto: un file riformattato rende `stale` l'interfaccia. Oltre
  400 file per voce l'hash è parziale (`partial: true`).
- Le interfacce non si archiviano: per forzare la rigenerazione si cancellano a
  mano.
- `context.py` non lancia e non ferma nulla: decide l'orchestratore.

---

## P3 — Validatori a due livelli

### Cosa è cambiato

| file | cosa |
| :- | :- |
| `sjck-graph/scripts/precheck.py` (nuovo) | livello 1: scope + criteri eseguibili, scrive `.sjck/out/<ID>.pre.json`; exit 0 `pass`, 1 `fail`, 2 `unclear`, 3 errore |
| `sjck-graph/scripts/config.py` (nuovo) | sezione `validator`: `model`, `effort`, `timeout_s`, `always_llm`, `commands_allow` |
| `sjck-graph/skills/sjck-orchestration/SKILL.md` | Step 3 punto 4: prima il precheck, il validatore LLM solo su `unclear`, con model/effort dal pre.json; regola ferrea aggiornata |
| `sjck-graph/agents/sjck-validator.md` | parte solo quando serve, legge il pre.json e **non riesegue** i comandi già eseguiti: valuta `llm_criteria` e gli esiti incerti |
| `sjck-graph/skills/sjck-orchestration/reference/scripts.md` | riferimento di `precheck.py` e della configurazione |
| `sjck-graph/docs/validation.md` (nuovo) | documentazione d'uso, affidabilità e limiti |
| `sjck-graph/tests/test_precheck.py` (nuovo) | 17 test |

Livello 1 (deterministico, nessun token): **scope** (i file dichiarati
nell'out JSON stanno in "Puoi modificare"? `usage.writes_outside_card` del
watchdog è 0?) e **criteri**: ogni criterio di accettazione il cui primo token
è un runner noto (`python`, `pytest`, `npm`, `make`, `ruff`, `tsc`, `go`,
`cargo`, `git`, …; altri via `validator.commands_allow`) viene eseguito.

Livello 2 solo se l'esito è ambiguo o la card lo chiede: criterio a parole,
timeout, comando non eseguibile, out JSON mancante, `validator: llm` in un
criterio, `always_llm: true`. Un timeout non condanna il nodo: diventa
`unclear`.

Modello del validatore configurabile e più piccolo se si vuole:
`.sjck/config.json` → `{"validator": {"model": "haiku", "effort": "low"}}`,
oppure `~/.sjck/config.json`, `$SJCK_CONFIG`, `$SJCK_VALIDATOR_MODEL`,
`$SJCK_VALIDATOR_EFFORT`. Default `sonnet`/`high`: identico al frontmatter
dell'agente, così chi non configura nulla non cambia comportamento. Il valore
risolto finisce in `llm_validator_model`/`llm_validator_effort` del pre.json e
l'orchestratore lo passa come override al lancio.

*Risparmio atteso*: un validatore LLM è un subagente nuovo, 15-30k token
(`sjck-graph/skills/sjck-planning/SKILL.md:56`). Sui nodi i cui criteri sono
tutti comandi — tipicamente i nodi meccanici e i retry, dove il fallimento è un
exit code — la validazione passa da 15-30k a zero. Sul run misurato, se metà dei
7 nodi avesse criteri interamente deterministici, sono **50-100k token su 418k
(12-25%)**, e un nodo che falla il precheck torna all'implementer senza spendere
nulla per scoprirlo.

### Come si verifica

```bash
python3 -m unittest discover -s sjck-graph/tests -p 'test_precheck.py'
```

I due test richiesti dalla rubrica:

- controllo deterministico fallito → nessuna chiamata al validatore LLM:
  `test_failed_deterministic_check_means_no_llm_validator_call`
  (verdetto `fail`, `llm_validator: false`, exit 1, findings già azionabili);
  stessa cosa per lo scope: `test_scope_violation_fails_without_the_llm`,
  `test_watchdog_writes_outside_card_fail_the_scope`.
- modello configurabile:
  `test_validator_model_is_configurable_and_can_be_smaller`
  (default `sonnet`/`high` → progetto `haiku`/`low` → l'env vince su tutto).

A mano, su un run esistente:

```bash
python3 sjck-graph/scripts/precheck.py --id T01 --cwd <run> --dry-run   # elenca i comandi
python3 sjck-graph/scripts/precheck.py --id T01 --cwd <run>; echo "exit $?"
echo '{"validator": {"model": "haiku", "effort": "low"}}' > <run>/.sjck/config.json
python3 sjck-graph/scripts/config.py validator --cwd <run>
```

### Limiti noti

- I comandi girano in una **shell** nella cartella del run: chi scrive una card
  esegue codice. È lo stesso potere dell'agente che li eseguiva, ma senza un LLM
  in mezzo: le card che arrivano da una change request vanno lette prima di
  avviare il run (`--dry-run` le elenca senza eseguirle).
- Lo scope si basa sui file dichiarati dall'implementer più i contatori del
  watchdog: senza plugin (installazione con `install.sh`) resta la dichiarazione.
- Il livello 1 non cerca stub vuoti, TODO o test disattivati (controllo 4 del
  validatore): se serve, va messo come criterio a parole nella card — allora
  parte il livello 2.
- `pass` richiede che **tutti** i criteri siano comandi e passino: le card con
  criteri scritti a parole non risparmiano nulla.
- Nessun hook: il precheck lo lancia l'orchestratore. Una sessione che non segue
  la skill continua a lanciare il validatore LLM com'è sempre stato.

---

## Verifica complessiva

```bash
python3 -m unittest discover -s sjck-graph/tests      # 176 test, OK (138 di partenza + 38)
```

Non ho lanciato run di sjck: la misura dei token la fa `evals/sum_usage.py`
dall'esterno. `console/` e `vscode/` non sono stati toccati: il campo `cost` di
`tokens.json` conserva la forma che il viewer già legge
(`sjck-graph/scripts/viewer.html:92-98`), i campi nuovi (`estimated`,
`unpriced_models`, `cost_usd` per nodo) sono additivi. Versione del plugin
portata a `0.5.0` (`sjck-graph/.claude-plugin/plugin.json`) perché il CHANGELOG
di questo repo lega ogni sezione a una versione rilasciata.

## Altri sprechi trovati (non implementati)

Fuori dalla rubrica, in ordine di peso stimato.

1. **`tool_output` 17,7% e `agent_messages` 13,2% del run misurato** (terza e
   quarta categoria). Il kit nota solo i casi estremi (insight `heavy`,
   `sjck-graph/scripts/tokens.py:659-663`). Interventi possibili: un limite
   deterministico sulla dimensione di un out JSON (lo schema c'è già:
   `sjck-graph/agents/sjck-implementer.md:29-32`, "summary ≤3 righe", ma nessuno
   lo verifica), e una regola di lettura a range per i tool output grandi.
2. **Il critico gira su `fable`** (`sjck-graph/agents/sjck-critic.md:5`), che
   nel listino è il modello più caro ($10/$50 per milione), per un
   approve/object read-only su testo che non è codice
   (`sjck-graph/agents/sjck-critic.md:9-10`). Ora che il costo per modello è
   calcolato, questa scelta è misurabile: va rivista con i dati di un run vero.
3. **La review finale legge tutto il diff aggregato con opus/high**
   (`sjck-graph/agents/sjck-reviewer.md:5-8`): su un grafo largo è il singolo
   input più grande del run. Alternativa: review per livello del DAG, o sul solo
   diff dei file toccati da più nodi.
4. **Nessun anello di retroazione dalle misure alle scelte.** `token-report.json`
   contiene già l'insight "opus su un nodo piccolo approvato al primo colpo"
   (`sjck-graph/scripts/tokens.py:646-651`), ma nulla lo rilegge: il planner usa
   solo le medie dei run archiviati
   (`sjck-graph/skills/sjck-planning/SKILL.md:52`). Un `model`/`effort`
   suggerito per tipo di nodo dai run precedenti è il risparmio più grande
   rimasto, ed è anche il più rischioso: tocca la qualità, non solo il costo.
5. **Il `thinking` resta in contesto e si rilegge a ogni turno**
   (`sjck-graph/scripts/tokens.py:632-637`): l'insight esiste, l'intervento no.
   Serve una scelta di effort per nodo, che ricade nel punto 4.
6. **`tokens.py` fa raccolta, costo e analisi in un file solo** (740 righe). La
   spec prevedeva `tokens/collect.py`, `tokens/cost.py`, `tokens/analyze.py`
   (`docs/specs/v0.4-token-analytics.md:21,45,52`). Debito strutturale, non
   spreco di token: ho aggiunto il costo in `config.py` per non peggiorarlo.
7. **Chiamata di rete in un hook**: `eur_per_usd()` interroga la BCE
   (`sjck-graph/scripts/tokens.py:380-434`) dentro gli hook `Stop`/`SubagentStop`,
   mentre la spec dice "nessuna chiamata di rete"
   (`docs/specs/v0.4-token-analytics.md:8`). È mitigata (cache giornaliera,
   timeout 3 s, nessun nuovo tentativo per un'ora, `SJCK_FX_OFFLINE`), ma resta
   una dipendenza esterna in un percorso che gira a ogni turno. Il costo in USD
   introdotto qui non ne ha bisogno: tutti i prezzi sono locali.
